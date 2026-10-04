from datetime import date
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from twin.analytics import cgm_fusion as cf
from twin.models.base import FusionSource, SleepStage
from twin.synthetic.wearables import Profile, generate

TZ = ZoneInfo("America/Chicago")


def _hr(low_hour: int = 3) -> pd.Series:
    """Real-looking HR: lowest around `low_hour` local time."""
    idx = pd.date_range("2026-08-16 07:00", "2026-08-20 07:00", freq="min", tz=TZ)
    hours = idx.hour + idx.minute / 60
    return pd.Series(70 + 12 * np.cos(2 * np.pi * (hours - low_hour - 12) / 24), index=idx)


def _profile(**kw) -> Profile:
    base = dict(patient_id="p", age=50, sex="male", bmi=27.0, sleep_apnea=False, copd=False,
                dysglycaemia=False, has_real_hrv=False)
    return Profile(**{**base, **kw})


def _sleep_spo2(out):
    asleep = pd.Series({t: st for a, b, st in out.sleep for t in pd.date_range(a, b, freq="min", inclusive="left")})
    spo2 = out.samples["spo2"]
    return spo2[spo2.index.isin(asleep[asleep != SleepStage.awake].index)]


def test_deterministic_per_patient():
    a = generate(_profile(), date(2026, 8, 16), date(2026, 8, 19), TZ, heart_rate=_hr())
    b = generate(_profile(), date(2026, 8, 16), date(2026, 8, 19), TZ, heart_rate=_hr())
    c = generate(_profile(patient_id="other"), date(2026, 8, 16), date(2026, 8, 19), TZ, heart_rate=_hr())
    assert a.sleep == b.sleep and a.samples["spo2"].equals(b.samples["spo2"])
    assert a.sleep != c.sleep


def test_ranges_and_sleep_follows_real_heart_rate():
    out = generate(_profile(), date(2026, 8, 16), date(2026, 8, 19), TZ, heart_rate=_hr(low_hour=3))
    assert out.sleep and all(b > a for a, b, _ in out.sleep)
    midpoints = [a + (b - a) / 2 for a, b, st in out.sleep if st != SleepStage.awake]
    hours = np.array([m.astimezone(TZ).hour for m in midpoints])
    assert np.mean((hours <= 6) | (hours >= 23)) > 0.8  # asleep where HR is lowest
    s = out.samples
    assert s["spo2"].between(70, 100).all() and s["respiration_rate"].between(8, 30).all()
    assert s["stress"].between(0, 99).all() and len(s["hrv_rmssd"]) >= 3


def test_apnoea_lowers_sleeping_spo2():
    normal = _sleep_spo2(generate(_profile(), date(2026, 8, 16), date(2026, 8, 19), TZ, heart_rate=_hr()))
    osa = _sleep_spo2(generate(_profile(sleep_apnea=True, bmi=37.0), date(2026, 8, 16), date(2026, 8, 19), TZ,
                               heart_rate=_hr()))
    assert normal.mean() > 94 and (normal < 90).mean() < 0.01
    assert osa.mean() < normal.mean() - 2 and (osa < 90).mean() > 0.05


def test_no_hrv_generated_when_real_inter_beat_data_exist():
    out = generate(_profile(has_real_hrv=True), date(2026, 8, 16), date(2026, 8, 19), TZ, heart_rate=_hr())
    assert out.samples["hrv_rmssd"].empty


def test_single_cgm_pass_through():
    idx = pd.date_range("2026-05-01 00:00", periods=60, freq="5min", tz=TZ)
    ref = pd.Series(np.r_[np.linspace(100, 160, 59), 40.0], index=idx)
    out = cf.single(ref)
    assert (out.index.minute % 5 == 0).all() and (out.source == FusionSource.reference_only).all()
    assert out.censored.iloc[-1] and not out.censored.iloc[:-1].any()
