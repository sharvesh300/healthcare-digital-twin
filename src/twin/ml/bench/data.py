"""CGMacros inputs for the glucose benchmark, straight from the raw PhysioNet files.

Only real, measured CGMacros factors are used. Nothing comes from Synthea, the wearable
generator or the database:
  * glucose: Dexcom G6 native readings (5 min). This is the input history and the target.
  * Fitbit: heart rate and activity calories, in 5-minute bins.
  * meal log: energy, carbs, protein, fat and fiber at the logged meal time.
  * bio.csv: age, sex, BMI, HbA1c and fasting glucose.
  * time of day, from the timestamps.
Libre readings are left out. They come from a second sensor on the same arm, and the target
is Dexcom. `Amount Consumed` is left out because it mixes 0-4 codes with percentages.

Every patient gets a 5-minute grid anchored on their Dexcom reading phase. Each covariate
bin covers (t - 5 min, t], so a row only holds what was known at t. The timeline is split
chronologically per patient into train, valid and test (60/15/25 %). An origin belongs to a
split only if it and its longest-horizon target are both inside that split.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from twin.sources import cgmacros

STEP_MIN = 5
HORIZONS = (15, 30, 60)
SPLITS = (("train", 0.60), ("valid", 0.75), ("test", 1.0))
MAX_FILL_STEPS = 6  # input gaps up to 30 min are bridged by interpolating between past readings
MACROS = ("energy_kcal", "carbs_g", "protein_g", "fat_g", "fiber_g")
STATIC = ("age", "male", "bmi", "hba1c", "fasting_glucose")


@dataclass
class Patient:
    pid: str
    group: str  # 'normal' | 'prediabetes' | 't2d' by HbA1c
    frame: pd.DataFrame  # 5-minute grid: glucose (raw, NaN gaps), glucose_in (bridged), covariates
    static: dict[str, float]
    split: np.ndarray  # per grid row: 'train' | 'valid' | 'test' | '' (purged)


def a1c_group(hba1c: float | None) -> str:
    if hba1c is None or np.isnan(hba1c):
        return "unknown"
    return "normal" if hba1c < 5.7 else "prediabetes" if hba1c < 6.5 else "t2d"


def _bridge_short_gaps(s: pd.Series, limit: int) -> pd.Series:
    """Linear interpolation across interior NaN runs of at most `limit` steps only.

    Both ends of a bridged run are readings that precede any origin after the run, so
    bridging never uses a value from the future of an origin.
    """
    isna = s.isna()
    run_id = (isna != isna.shift()).cumsum()
    run_len = isna.groupby(run_id).transform("sum")
    filled = s.interpolate(limit_area="inside")
    return s.where(~isna | (run_len > limit), filled)


def _grid(native: pd.Series) -> pd.DatetimeIndex:
    phase = int(pd.Series(native.index.minute % STEP_MIN).mode().iloc[0])
    start = native.index.min().floor("h") + pd.Timedelta(minutes=phase)
    return pd.date_range(start, native.index.max() + pd.Timedelta(minutes=STEP_MIN), freq=f"{STEP_MIN}min")


def _bin(values: pd.Series | pd.DataFrame, grid: pd.DatetimeIndex, how: str):
    """Aggregate minute values into (t - 5, t] bins labelled t."""
    binned = values.resample(f"{STEP_MIN}min", origin=grid[0], closed="right", label="right")
    out = binned.sum(min_count=1) if how == "sum" else binned.mean()
    return out.reindex(grid)


def load_patient(cgmacros_dir: Path, info: cgmacros.Participant) -> Patient | None:
    df = cgmacros.read_sensor_csv(cgmacros.sensor_csv_path(cgmacros_dir, info.subject_id))
    streams = cgmacros.parse_streams(df)
    native = streams.glucose["Dexcom GL"].astype(float)
    if len(native) < 288:
        return None
    grid = _grid(native)

    # Snap each native reading to the nearest grid point (Dexcom clocks drift by a minute or two).
    snapped = pd.Series(native.to_numpy(), index=_snap(native.index, grid))
    glucose = snapped.groupby(level=0).mean().reindex(grid)

    f = pd.DataFrame(index=grid)
    f["glucose"] = glucose
    f["glucose_in"] = _bridge_short_gaps(glucose, MAX_FILL_STEPS)
    fit = streams.fitbit
    f["hr"] = _bin(fit["heart_rate"], grid, "mean")
    f["active_kcal"] = _bin(fit["active_kcal"], grid, "sum")
    meals = streams.meals[list(MACROS)].fillna(0.0)
    meals = meals.assign(meal=1.0)
    f[[*MACROS, "meal"]] = _bin(meals, grid, "sum").fillna(0.0)
    minute = grid.hour * 60 + grid.minute
    f["tod_sin"] = np.sin(2 * np.pi * minute / 1440)
    f["tod_cos"] = np.cos(2 * np.pi * minute / 1440)

    labs = info.labs
    static = {
        "age": float(info.age),
        "male": float(info.sex == "male"),
        "bmi": info.bmi if info.bmi is not None else np.nan,
        "hba1c": labs.get("4548-4", np.nan),
        "fasting_glucose": labs.get("1558-6", np.nan),
    }

    # Chronological split with a purge: the origin and its 60-minute target share a split.
    t = (grid - grid[0]) / (grid[-1] - grid[0])
    t_target = (grid + pd.Timedelta(minutes=max(HORIZONS)) - grid[0]) / (grid[-1] - grid[0])
    split = np.full(len(grid), "", dtype=object)
    lo = 0.0
    for name, hi in SPLITS:
        inside = (t >= lo) & (t_target < hi + 1e-9) if hi < 1 else (t >= lo)
        split[np.asarray(inside)] = name
        lo = hi
    return Patient(info.subject_id, a1c_group(static["hba1c"]), f, static, split)


def _snap(index: pd.DatetimeIndex, grid: pd.DatetimeIndex) -> pd.DatetimeIndex:
    offset = ((index - grid[0]) / pd.Timedelta(minutes=STEP_MIN)).to_numpy()
    return grid[0] + pd.to_timedelta(np.rint(offset) * STEP_MIN, unit="min")


def load_cohort(cgmacros_dir: Path) -> list[Patient]:
    participants = cgmacros.read_bio(cgmacros_dir / "bio.csv")
    patients = [load_patient(cgmacros_dir, p) for p in participants.values()]
    return [p for p in patients if p is not None]


@dataclass
class Origins:
    """Forecast origins shared by every model: one row per (patient, grid index)."""

    pid: np.ndarray
    idx: np.ndarray  # row in the patient's frame
    time: np.ndarray
    split: np.ndarray
    group: np.ndarray
    glucose_now: np.ndarray
    target: np.ndarray  # (n, len(HORIZONS)) raw future readings, NaN when not observed


def build_origins(patients: list[Patient], lookback: int) -> Origins:
    """Origins with a reading at t and a complete (bridged) lookback window."""
    cols: dict[str, list] = {k: [] for k in ("pid", "idx", "time", "split", "group", "now", "target")}
    for p in patients:
        g = p.frame["glucose"].to_numpy()
        gin = p.frame["glucose_in"].to_numpy()
        complete = pd.Series(~np.isnan(gin)).rolling(lookback).sum().to_numpy() == lookback
        ok = complete & ~np.isnan(g) & (p.split != "")
        idx = np.flatnonzero(ok)
        steps = [h // STEP_MIN for h in HORIZONS]
        tgt = np.full((len(idx), len(steps)), np.nan)
        for j, s in enumerate(steps):
            inside = idx + s < len(g)
            tgt[inside, j] = g[idx[inside] + s]
        keep = ~np.isnan(tgt).all(axis=1)
        idx = idx[keep]
        cols["pid"].append(np.full(len(idx), p.pid))
        cols["idx"].append(idx)
        cols["time"].append(p.frame.index.to_numpy()[idx])
        cols["split"].append(p.split[idx].astype(str))
        cols["group"].append(np.full(len(idx), p.group))
        cols["now"].append(g[idx])
        cols["target"].append(tgt[keep])
    cat = {k: np.concatenate(v) for k, v in cols.items()}
    return Origins(cat["pid"], cat["idx"], cat["time"], cat["split"], cat["group"], cat["now"], cat["target"])
