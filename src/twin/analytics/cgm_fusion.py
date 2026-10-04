"""Fusion of two CGMs worn at the same time into one glucose stream.

Method (cgm-fusion-1), validated on the CGMacros T2D cohort:

1. Time alignment. The lag between the sensors is found by cross-correlation over
   +/-120 min. A lag of at most 20 min is sensor/processing delay: the later sensor
   is shifted onto the earlier one (it is closer to blood glucose). A larger lag is a
   device clock error; the device whose post-meal glucose peak is closer to the
   cohort's typical time-to-peak keeps its clock and the other one is shifted.
2. Cross-calibration. The secondary sensor is mapped onto the reference sensor's
   scale with Deming regression (errors in both sensors), fitted only where neither
   sensor is in its first 24 h. The reference scale is not re-anchored to
   fingersticks: in CGMacros all fingersticks fall on warm-up day 1 and disagree
   with each other far more than the sensors do later; lab HbA1c agrees with the
   reference sensor's GMI instead.
3. Combination on a 5-min grid: inverse-variance weighting with equal base error,
   where a sensor in its first 24 h has its variance multiplied by the measured
   warm-up factor. Gaps in one sensor are filled by the other. Values at a sensor's
   reporting limit (<=40 or >=400 mg/dL) are censored: the other sensor is used if it
   has a valid value, otherwise the value is kept and flagged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import numpy as np
import pandas as pd

from twin.models.base import FusionSource, LagKind

METHOD_VERSION = "cgm-fusion-1"
GRID = "5min"
LAG_SEARCH_MINUTES = 120
SENSOR_LAG_MAX_MINUTES = 20
WARMUP = timedelta(hours=24)
LOW_LIMIT, HIGH_LIMIT = 40.0, 400.0
MAX_WARMUP_FACTOR = 25.0
# Interpolation onto the minute grid only between consecutive native readings.
MAX_GAP_MINUTES = {"reference": 10, "secondary": 20}


@dataclass(frozen=True)
class Alignment:
    lag_minutes: int  # secondary behind reference (+) / ahead (-)
    lag_kind: LagKind
    reference_shift_minutes: int
    secondary_shift_minutes: int


@dataclass(frozen=True)
class Calibration:
    intercept: float
    slope: float
    overlap_points: int
    disagreement_sd: float
    warmup_variance_factor: float


def minute_series(native: pd.Series, max_gap_minutes: int) -> pd.Series:
    """Native readings -> 1-minute series, interpolated only across gaps <= max_gap."""
    s = native.dropna().astype(float).sort_index()
    if s.empty:
        return s
    grid = pd.date_range(s.index.min().ceil("min"), s.index.max().floor("min"), freq="min")
    full = s.reindex(s.index.union(grid))
    known = full.index.to_series().where(full.notna())
    gap = (known.bfill() - known.ffill()).dt.total_seconds() / 60
    out = full.interpolate(method="time", limit_area="inside")
    out[full.isna() & (gap > max_gap_minutes)] = np.nan
    return out.reindex(grid)


def shifted(native: pd.Series, minutes: int) -> pd.Series:
    out = native.copy()
    out.index = out.index + pd.Timedelta(minutes=minutes)
    return out


def estimate_lag(reference: pd.Series, secondary: pd.Series) -> tuple[int, float]:
    """Minutes the secondary lags the reference (+) or leads it (-), and the correlation there."""
    r = minute_series(reference, MAX_GAP_MINUTES["reference"])
    s = minute_series(secondary, MAX_GAP_MINUTES["secondary"])
    best, best_corr = 0, -np.inf
    for lag in range(-LAG_SEARCH_MINUTES, LAG_SEARCH_MINUTES + 1):
        corr = r.corr(s.shift(-lag, freq="min"))
        if np.isfinite(corr) and corr > best_corr:
            best, best_corr = lag, corr
    return best, float(best_corr)


def meal_time_to_peak(native: pd.Series, meal_times, max_gap_minutes: int) -> float | None:
    """Minutes from meal start to the peak of the mean post-meal glucose rise."""
    m = minute_series(native, max_gap_minutes)
    curves = []
    for t in meal_times:
        window = m.reindex(pd.date_range(t - pd.Timedelta(minutes=15), t + pd.Timedelta(minutes=180), freq="min"))
        if window.notna().mean() > 0.9:
            curves.append((window - window.iloc[:16].mean()).to_numpy())
    if not curves:
        return None
    return float(np.nanargmax(np.nanmean(curves, axis=0)) - 15)


def decide_alignment(lag: int, reference_peak: float | None, secondary_peak: float | None,
                     cohort_peak: float | None) -> Alignment:
    if abs(lag) <= SENSOR_LAG_MAX_MINUTES:
        # Shift the later sensor onto the earlier one.
        return Alignment(lag, LagKind.sensor_lag, reference_shift_minutes=min(lag, 0),
                         secondary_shift_minutes=-max(lag, 0))
    secondary_is_right = (
        None not in (reference_peak, secondary_peak, cohort_peak)
        and abs(secondary_peak - cohort_peak) < abs(reference_peak - cohort_peak)
    )
    if secondary_is_right:
        return Alignment(lag, LagKind.clock_offset, reference_shift_minutes=lag, secondary_shift_minutes=0)
    return Alignment(lag, LagKind.clock_offset, reference_shift_minutes=0, secondary_shift_minutes=-lag)


def deming(x: np.ndarray, y: np.ndarray, variance_ratio: float = 1.0) -> tuple[float, float]:
    """Fit y = a + b*x with errors in both; variance_ratio = var(err_y) / var(err_x)."""
    mx, my = x.mean(), y.mean()
    sxx, syy = ((x - mx) ** 2).mean(), ((y - my) ** 2).mean()
    sxy = ((x - mx) * (y - my)).mean()
    lam = variance_ratio
    slope = (syy - lam * sxx + np.sqrt((syy - lam * sxx) ** 2 + 4 * lam * sxy**2)) / (2 * sxy)
    return float(my - slope * mx), float(slope)


def _valid(s: pd.Series) -> pd.Series:
    return s.where((s > LOW_LIMIT) & (s < HIGH_LIMIT))


def _robust_sd(x: pd.Series) -> float:
    return float(1.4826 * (x - x.median()).abs().median())


def calibrate(reference: pd.Series, secondary: pd.Series) -> Calibration:
    """Map the (already aligned) secondary onto the reference scale."""
    r = minute_series(reference, MAX_GAP_MINUTES["reference"])
    s = minute_series(secondary, MAX_GAP_MINUTES["secondary"])
    both = pd.concat([_valid(r), _valid(s)], axis=1, keys=["r", "s"]).dropna()
    warm = (both.index < reference.index.min() + WARMUP) | (both.index < secondary.index.min() + WARMUP)
    settled = both[~warm]
    if len(settled) < 60:
        raise ValueError(f"only {len(settled)} overlapping minutes after warm-up; cannot calibrate")
    intercept, slope = deming(settled.s.to_numpy(), settled.r.to_numpy())

    diff = both.r - (intercept + slope * both.s)
    sd_settled = _robust_sd(diff[~warm])
    # Disagreement variance = var_ref + var_sec. With equal base variances v, a warming
    # sensor with factor f gives (f + 1) v, so f = 2 * var_warm / var_settled - 1.
    factor = 1.0
    if warm.sum() >= 60 and sd_settled > 0:
        factor = float(np.clip(2 * (_robust_sd(diff[warm]) / sd_settled) ** 2 - 1, 1.0, MAX_WARMUP_FACTOR))
    return Calibration(intercept, slope, len(settled), sd_settled, factor)


def fuse(reference: pd.Series, secondary: pd.Series, cal: Calibration) -> pd.DataFrame:
    """Fused 5-min stream: columns glucose_mg_dl, source (FusionSource), censored."""
    r_min = minute_series(reference, MAX_GAP_MINUTES["reference"])
    s_min = minute_series(secondary, MAX_GAP_MINUTES["secondary"])
    starts = [x.index.min() for x in (r_min, s_min) if not x.empty]
    ends = [x.index.max() for x in (r_min, s_min) if not x.empty]
    grid = pd.date_range(min(starts).ceil(GRID), max(ends).floor(GRID), freq=GRID)

    r = r_min.reindex(grid)
    s_raw = s_min.reindex(grid)
    s = cal.intercept + cal.slope * s_raw
    r_ok, s_ok = _valid(r).notna(), _valid(s_raw).notna()

    def weight(native: pd.Series) -> np.ndarray:
        in_warmup = grid < native.index.min() + WARMUP
        return np.where(in_warmup, 1 / cal.warmup_variance_factor, 1.0)

    w_r, w_s = weight(reference), weight(secondary)
    value = np.where(
        r_ok & s_ok, (w_r * r + w_s * s) / (w_r + w_s),
        np.where(r_ok, r, np.where(s_ok, s, r.fillna(s))),
    )
    source = np.select(
        [r_ok & s_ok, r_ok, s_ok, r.notna() & s.notna(), r.notna()],
        [FusionSource.both, FusionSource.reference_only, FusionSource.secondary_only,
         FusionSource.both, FusionSource.reference_only],
        default=FusionSource.secondary_only,
    )
    # Censored: no sensor had a valid value, or calibration pushed it past the reporting limits.
    censored = ~(r_ok | s_ok) | (value <= LOW_LIMIT) | (value >= HIGH_LIMIT)
    out = pd.DataFrame({"glucose_mg_dl": value, "source": source, "censored": censored}, index=grid)
    out = out[np.isfinite(out.glucose_mg_dl)]
    out["glucose_mg_dl"] = out.glucose_mg_dl.clip(LOW_LIMIT, HIGH_LIMIT).round(1)
    return out


def gmi(values: pd.Series) -> float:
    """Glucose management indicator (%) from mean glucose in mg/dL."""
    return 3.31 + 0.02392 * float(values.mean())


def single(reference: pd.Series) -> pd.DataFrame:
    """One CGM: the same 5-min grid and censoring rules, without a second sensor."""
    r_min = minute_series(reference, MAX_GAP_MINUTES["reference"])
    if r_min.empty:
        return pd.DataFrame(columns=["glucose_mg_dl", "source", "censored"])
    grid = pd.date_range(r_min.index.min().ceil(GRID), r_min.index.max().floor(GRID), freq=GRID)
    r = r_min.reindex(grid).dropna()
    out = pd.DataFrame({"glucose_mg_dl": r.clip(LOW_LIMIT, HIGH_LIMIT).round(1),
                        "source": FusionSource.reference_only,
                        "censored": (r <= LOW_LIMIT) | (r >= HIGH_LIMIT)}, index=r.index)
    return out
