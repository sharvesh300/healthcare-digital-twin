"""CGM fusion on synthetic data where the true glucose is known."""

import numpy as np
import pandas as pd
import pytest

from twin.analytics import cgm_fusion as cf
from twin.models.base import FusionSource, LagKind

T0 = pd.Timestamp("2026-05-01 00:00", tz="America/Chicago")
DAYS = 4


def truth() -> pd.Series:
    """Minute-resolution glucose: baseline + circadian drift + three meal responses a day."""
    t = pd.date_range(T0, T0 + pd.Timedelta(days=DAYS), freq="min")
    minutes = np.arange(len(t))
    g = 130 + 15 * np.sin(2 * np.pi * minutes / 1440)
    for day in range(DAYS):
        for hour, size in ((8, 70), (13, 90), (19, 110)):
            start = day * 1440 + hour * 60
            x = np.clip(minutes - start, 0, None)
            g += size * (x / 60) * np.exp(1 - x / 60) * (minutes >= start)
    return pd.Series(g, index=t)


def sensor(true: pd.Series, every: int, delay: int, scale: float, offset: float, noise: float,
           warmup_noise: float, seed: int) -> pd.Series:
    rng = np.random.default_rng(seed)
    s = true.shift(delay, freq="min").reindex(true.index).dropna().iloc[::every]
    in_warmup = s.index < s.index.min() + pd.Timedelta(hours=24)
    sd = np.where(in_warmup, warmup_noise, noise)
    return (scale * s + offset + rng.normal(0, sd)).round()


@pytest.fixture(scope="module")
def streams():
    true = truth()
    reference = sensor(true, every=5, delay=8, scale=1.0, offset=0, noise=4, warmup_noise=4, seed=1)
    secondary = sensor(true, every=15, delay=0, scale=0.8, offset=-10, noise=4, warmup_noise=16, seed=2)
    return true, reference, secondary


def test_lag_secondary_leads_by_8_minutes(streams):
    _, reference, secondary = streams
    lag, corr = cf.estimate_lag(reference, secondary)
    assert lag == pytest.approx(-8, abs=1) and corr > 0.95


def test_alignment_rules():
    a = cf.decide_alignment(-8, None, None, None)
    assert (a.lag_kind, a.reference_shift_minutes, a.secondary_shift_minutes) == (LagKind.sensor_lag, -8, 0)
    a = cf.decide_alignment(12, None, None, None)
    assert (a.reference_shift_minutes, a.secondary_shift_minutes) == (0, -12)
    # Clock offset: the secondary's meal response is an hour late -> the secondary is moved.
    a = cf.decide_alignment(60, reference_peak=70, secondary_peak=130, cohort_peak=72)
    assert (a.lag_kind, a.reference_shift_minutes, a.secondary_shift_minutes) == (LagKind.clock_offset, 0, -60)
    # ...unless it is the reference whose timing is implausible.
    a = cf.decide_alignment(60, reference_peak=15, secondary_peak=75, cohort_peak=72)
    assert (a.reference_shift_minutes, a.secondary_shift_minutes) == (60, 0)


def test_deming_is_not_attenuated_by_noise_in_x():
    rng = np.random.default_rng(0)
    x_true = rng.uniform(70, 250, 5000)
    x = x_true + rng.normal(0, 15, x_true.size)
    y = 10 + 1.25 * x_true + rng.normal(0, 15, x_true.size)
    _, ols_slope = np.polyfit(x, y, 1)
    _, slope = cf.deming(x, y)
    assert abs(slope - 1.25) < 0.03 < abs(ols_slope - 1.25)


def test_calibration_recovers_scale_and_warmup(streams):
    _, reference, secondary = streams
    align = cf.decide_alignment(*cf.estimate_lag(reference, secondary)[:1], None, None, None)
    ref = cf.shifted(reference, align.reference_shift_minutes)
    sec = cf.shifted(secondary, align.secondary_shift_minutes)
    cal = cf.calibrate(ref, sec)
    # secondary = 0.8 * truth - 10  ->  truth = 1.25 * secondary + 12.5
    assert cal.slope == pytest.approx(1.25, abs=0.03)
    assert cal.intercept == pytest.approx(12.5, abs=4)
    assert cal.warmup_variance_factor > 3  # the secondary is much noisier on day 1


def test_fusion_beats_either_sensor_and_fills_gaps(streams):
    true, reference, secondary = streams
    gap = (reference.index >= T0 + pd.Timedelta(days=2, hours=10)) & (reference.index < T0 + pd.Timedelta(days=2, hours=13))
    reference = reference[~gap]
    align = cf.decide_alignment(cf.estimate_lag(reference, secondary)[0], None, None, None)
    ref = cf.shifted(reference, align.reference_shift_minutes)
    sec = cf.shifted(secondary, align.secondary_shift_minutes)
    cal = cf.calibrate(ref, sec)
    fused = cf.fuse(ref, sec, cal)

    settled = fused.index >= T0 + pd.Timedelta(days=1, hours=1)
    err = lambda est: float((est - true.reindex(est.index)).abs().mean())
    fused_err = err(fused.glucose_mg_dl[settled])
    ref_err = err(cf.minute_series(ref, 10).reindex(fused.index[settled]).dropna())
    sec_err = err((cal.intercept + cal.slope * cf.minute_series(sec, 20)).reindex(fused.index[settled]).dropna())
    assert fused_err < ref_err and fused_err < sec_err

    in_gap = fused.loc[T0 + pd.Timedelta(days=2, hours=10, minutes=30): T0 + pd.Timedelta(days=2, hours=12, minutes=30)]
    assert len(in_gap) == 25 and (in_gap.source == FusionSource.secondary_only).all()
    assert (fused.source == FusionSource.both).mean() > 0.9


def test_censored_values_use_the_other_sensor():
    idx = pd.date_range(T0, periods=12 * 60, freq="5min")
    true = pd.Series(np.linspace(300, 450, len(idx)), index=idx)
    reference = true.clip(upper=400)                       # pinned at the limit
    secondary = (true / 1.2).iloc[::3].round()             # reads lower: raw max 375, never pinned
    cal = cf.Calibration(intercept=0.0, slope=1.2, overlap_points=0, disagreement_sd=5.0, warmup_variance_factor=1.0)
    fused = cf.fuse(reference, secondary, cal)
    last_secondary = secondary.index.max()
    high = fused[(fused.index > last_secondary - pd.Timedelta(hours=2)) & (fused.index <= last_secondary)]
    assert (high.source == FusionSource.secondary_only).all()
    assert high.censored.all() and (high.glucose_mg_dl == 400).all()   # beyond the reference scale's limit
    mid = fused[(fused.index > T0 + pd.Timedelta(hours=1)) & (fused.index < T0 + pd.Timedelta(hours=3))]
    assert (mid.source == FusionSource.both).all() and not mid.censored.any()


def test_gmi():
    assert cf.gmi(pd.Series([167.0] * 10)) == pytest.approx(7.30, abs=0.01)
