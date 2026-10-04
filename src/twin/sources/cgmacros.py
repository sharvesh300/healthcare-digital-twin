"""Parsing and normalisation of the CGMacros dataset (PhysioNet, v1.0.0).

Source quirks handled here (verified against the files, not just the data dictionary):
  * bio.csv headers carry stray whitespace; three fingerstick columns share the
    header "Time (t)", so they are read by position.
  * BMI, Non HDL, LDL (Cal), VLDL (Cal) and Cho/HDL Ratio are derived values
    (with 800/400 error sentinels) and are dropped; the report views recompute them.
  * A1c is labelled mmol/mol in the dictionary but the values (4.6-8.5) are %.
  * Weight is in lb and height in inches; both are converted to kg / cm.
  * Per-participant CSVs come in several header variants (optional pandas index
    column, METs vs Fitbit Intensity, optional Amount Consumed, one file with Steps).
  * Libre and Dexcom values are linearly interpolated onto a 1-minute grid. Only the
    native sensor readings are kept (see `native_samples`).
  * METs are exported multiplied by 10.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path

import numpy as np
import pandas as pd

LB_TO_KG = 0.45359237
IN_TO_CM = 2.54

# bio.csv column -> (LOINC, factor to UCUM unit). Only measured values.
BIO_LABS: dict[str, tuple[str, float]] = {
    "A1c PDL (Lab)": ("4548-4", 1.0),
    "Fasting GLU - PDL (Lab)": ("1558-6", 1.0),
    "Insulin": ("20448-7", 1.0),
    "Cholesterol": ("2093-3", 1.0),
    "HDL": ("2085-9", 1.0),
    "Triglycerides": ("2571-8", 1.0),
    "Body weight": ("29463-7", LB_TO_KG),
    "Height": ("8302-2", IN_TO_CM),
}
BIO_DERIVED = {"BMI", "Non HDL", "LDL (Cal)", "VLDL (Cal)", "Cho/HDL Ratio"}
BIO_REQUIRED = {"subject", "Age", "Gender", "Self-identify", "Collection time PDL (Lab)"} | set(BIO_LABS)
FINGERSTICK_RE = re.compile(r"#\d Contour Fingerstick GLU")

SENSOR_REQUIRED = {"Timestamp", "Libre GL", "Dexcom GL", "HR", "Meal Type", "Image path"}
MEAL_MACROS = {
    "Calories": "energy_kcal",
    "Carbs": "carbs_g",
    "Protein": "protein_g",
    "Fat": "fat_g",
    "Fiber": "fiber_g",
    "Amount Consumed": "pct_consumed",
}
# Columns we know about but deliberately do not store (reported, not silently lost).
SENSOR_IGNORED = {"Steps", "Sugar", "RecordIndex"}

CGM_INTERVAL_MIN = {"Dexcom GL": 5, "Libre GL": 15}


class SchemaError(ValueError):
    pass


@dataclass(frozen=True)
class Participant:
    subject_id: str  # zero-padded CGMacros number, e.g. "003"
    sex: str  # 'female' | 'male' (FHIR administrative gender)
    age: int
    race_ethnicity: str | None
    labs: dict[str, float]  # LOINC -> value in UCUM units
    lab_time: time | None
    fingersticks: list[tuple[time, float]] = field(default_factory=list)

    @property
    def hba1c(self) -> float | None:
        return self.labs.get("4548-4")

    @property
    def bmi(self) -> float | None:
        weight, height = self.labs.get("29463-7"), self.labs.get("8302-2")
        if not weight or not height:
            return None
        return weight / (height / 100) ** 2


def _num(value: str) -> float | None:
    value = (value or "").strip()
    if value in ("", "nan", "NaN"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _clock(value: str) -> time | None:
    value = (value or "").strip()
    for fmt in ("%I:%M:%S %p", "%I:%M %p", "%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    return None


def _normalise_race_ethnicity(value: str) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    if "african american" in value.lower() or "black" in value.lower():
        return "Black or African American"
    return value


def read_bio(path: Path) -> dict[str, Participant]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    header = [h.strip() for h in rows[0]]
    missing = BIO_REQUIRED - set(header)
    if missing:
        raise SchemaError(f"bio.csv missing columns {sorted(missing)}; found {header}")
    col = {name: header.index(name) for name in BIO_REQUIRED}
    # Fingerstick value columns, each followed by its own "Time (t)" column.
    sticks = [i for i, h in enumerate(header) if FINGERSTICK_RE.fullmatch(h)]

    participants: dict[str, Participant] = {}
    for row in rows[1:]:
        if not row or not row[col["subject"]].strip():
            continue
        sid = f"{int(row[col['subject']]):03d}"
        labs = {}
        for name, (loinc, factor) in BIO_LABS.items():
            value = _num(row[col[name]])
            if value is not None:
                labs[loinc] = round(value * factor, 2)
        fingersticks = []
        for i in sticks:
            value, at = _num(row[i]), _clock(row[i + 1]) if i + 1 < len(row) else None
            if value is not None and at is not None:
                fingersticks.append((at, value))
        participants[sid] = Participant(
            subject_id=sid,
            sex={"F": "female", "M": "male"}[row[col["Gender"]].strip().upper()],
            age=int(float(row[col["Age"]])),
            race_ethnicity=_normalise_race_ethnicity(row[col["Self-identify"]]),
            labs=labs,
            lab_time=_clock(row[col["Collection time PDL (Lab)"]]),
            fingersticks=fingersticks,
        )
    return participants


def sensor_csv_path(cgmacros_dir: Path, subject_id: str) -> Path:
    return cgmacros_dir / f"CGMacros-{subject_id}" / f"CGMacros-{subject_id}.csv"


def read_sensor_csv(path: Path) -> pd.DataFrame:
    """Raw per-minute frame indexed by naive local timestamp, headers normalised."""
    df = pd.read_csv(path, low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    df = df.drop(columns=[c for c in df.columns if c.startswith("Unnamed")])
    missing = SENSOR_REQUIRED - set(df.columns)
    if missing:
        raise SchemaError(f"{path.name} missing columns {sorted(missing)}; found {list(df.columns)}")
    df.index = pd.to_datetime(df.pop("Timestamp"), format="ISO8601")
    df = df[~df.index.duplicated(keep="first")].sort_index()
    return df


def native_samples(series: pd.Series, interval_min: int, tol: float = 1e-3) -> pd.Series:
    """Recover native sensor readings from a series linearly interpolated to 1 minute.

    Linear interpolation leaves the native readings as the vertices of a piecewise-
    linear curve, so vertices (slope changes and segment ends) are native. Readings
    that fall inside a straight run (e.g. three equal values) are not vertices; they
    are restored by stepping the sensor's nominal interval between two vertices whose
    distance is an exact multiple of it.
    """
    s = series.dropna()
    if s.empty:
        return s.astype("int64")
    grid = pd.date_range(s.index.min(), s.index.max(), freq="min")
    v = s.reindex(grid).to_numpy(dtype=float)
    valid = ~np.isnan(v)
    prev_valid = np.r_[False, valid[:-1]]
    next_valid = np.r_[valid[1:], False]
    slope_in = np.r_[np.nan, np.diff(v)]
    slope_out = np.r_[np.diff(v), np.nan]
    with np.errstate(invalid="ignore"):
        bend = np.abs(slope_out - slope_in) > tol
    vertex = valid & (~prev_valid | ~next_valid | bend)

    keep = vertex.copy()
    knots = np.flatnonzero(vertex)
    for a, b in zip(knots, knots[1:]):
        gap = b - a
        if gap > interval_min and gap % interval_min == 0 and valid[a : b + 1].all():
            keep[a + interval_min : b : interval_min] = True
    out = pd.Series(v[keep], index=grid[keep])
    return out.round().astype("int64")


def normalise_meal_type(value: str) -> str | None:
    value = (value or "").strip().lower()
    if not value:
        return None
    if value.startswith("snack"):
        return "snack"
    if value in ("breakfast", "lunch", "dinner"):
        return value
    raise SchemaError(f"unknown meal type {value!r}")


@dataclass
class SensorStreams:
    """All streams for one participant, timestamps still naive source-local time."""

    glucose: dict[str, pd.Series]  # 'Dexcom GL' / 'Libre GL' -> native readings
    fitbit: pd.DataFrame  # heart_rate, mets, activity_level, active_kcal
    meals: pd.DataFrame  # started_at index, meal_type + macros; not stored, used to time-check CGM clocks
    ignored_columns: list[str]

    @property
    def first_timestamp(self) -> datetime:
        starts = [s.index.min() for s in self.glucose.values() if not s.empty]
        starts.append(self.fitbit.index.min())
        return min(starts).to_pydatetime()

    @property
    def study_day_1(self) -> date:
        return self.first_timestamp.date()


def parse_streams(df: pd.DataFrame) -> SensorStreams:
    glucose = {col: native_samples(df[col], minutes) for col, minutes in CGM_INTERVAL_MIN.items()}

    fitbit = pd.DataFrame(index=df.index)
    fitbit["heart_rate"] = df["HR"].round()
    fitbit["mets"] = df["METs"] / 10 if "METs" in df else np.nan
    fitbit["activity_level"] = df["Intensity"] if "Intensity" in df else np.nan
    fitbit["active_kcal"] = df["Calories (Activity)"].round(3) if "Calories (Activity)" in df else np.nan
    fitbit = fitbit.dropna(how="all")

    meal_rows = df[df["Meal Type"].notna() & (df["Meal Type"].astype(str).str.strip() != "")]
    meals = pd.DataFrame(index=meal_rows.index)
    meals["meal_type"] = meal_rows["Meal Type"].astype(str).map(normalise_meal_type)
    for src, dst in MEAL_MACROS.items():
        meals[dst] = pd.to_numeric(meal_rows[src], errors="coerce") if src in meal_rows else np.nan
    meals["pct_consumed"] = meals["pct_consumed"].clip(0, 100)

    known = SENSOR_REQUIRED | set(MEAL_MACROS) | {"METs", "Intensity", "Calories (Activity)"}
    ignored = sorted(c for c in df.columns if c not in known)
    return SensorStreams(glucose=glucose, fitbit=fitbit, meals=meals, ignored_columns=ignored)


def shift(index: pd.DatetimeIndex, days: int, tz: str) -> pd.DatetimeIndex:
    """Naive source-local wall time -> tz-aware twin time, preserving time of day. Non-existent
    (spring-forward) and ambiguous (fall-back) local times become NaT and are dropped."""
    shifted = index + pd.Timedelta(days=days)
    return shifted.tz_localize(tz, ambiguous="NaT", nonexistent="NaT")
