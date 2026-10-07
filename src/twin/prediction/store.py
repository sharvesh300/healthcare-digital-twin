"""Database side of the glucose forecast: the real inputs around one forecast origin.

Only recorded, real devices are read: the Dexcom CGM (native readings, as in training, not
the fused stream), the Fitbit (heart rate, activity kcal) and the meal log. Generator and
live-simulator devices are excluded. Inputs end at `at`; readings after `at` are loaded
separately (`after`) and only ever drawn as "what happened", never fed to a model.

Static factors are the participant's own: HbA1c, fasting glucose and BMI from the real labs
in report.patient_baseline (a synthetic BMI is dropped), and the participant's age. The
twin's birth date comes from the matched Synthea patient, so the real age is the twin's age
minus core.patient.match_age_diff (synthetic age - real age at matching).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from uuid import UUID

import numpy as np
import pandas as pd
from sqlalchemy import text

from twin.db import engine

GLUCOSE_HISTORY = timedelta(days=3)  # ARIMA fits on up to 3 days; the GRU uses the last 3 h
INPUT_HISTORY = timedelta(hours=4)  # wearables and meals: the GRU window plus meal context
AFTER = timedelta(minutes=65)  # readings after the origin, for the "what happened" overlay
MACROS = ("energy_kcal", "carbs_g", "protein_g", "fat_g", "fiber_g")


@dataclass
class ForecastInputs:
    patient_id: UUID
    source: str  # data source code: 'cgmacros', 'bigideas', ...
    at: datetime  # the origin cap, twin time (tz-aware)
    glucose: pd.Series  # native Dexcom readings up to `at`, tz-aware index
    after: pd.Series  # native Dexcom readings in (at, at + AFTER]
    heart_rate: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))  # Fitbit, per minute
    active_kcal: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    meals: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=["meal_type", *MACROS]))
    static: dict[str, float] = field(default_factory=dict)  # age, male, bmi, hba1c, fasting_glucose


_PATIENT = """
SELECT p.patient_id, s.code AS source, p.sex::text AS sex, p.birth_date, p.match_age_diff
FROM core.patient p JOIN ref.data_source s USING (source_id)
WHERE p.patient_id = :p
"""

_DEXCOM_DEVICES = """
SELECT d.device_id FROM core.device d JOIN ref.device_model m USING (model_id)
WHERE d.patient_id = :p AND m.manufacturer = 'Dexcom' AND NOT m.is_synthetic AND NOT m.is_live_simulator
"""

_LATEST = f"SELECT max(time) FROM ts.glucose_reading WHERE device_id IN ({_DEXCOM_DEVICES})"

_GLUCOSE = f"""
SELECT time, glucose_mg_dl::float AS value FROM ts.glucose_reading
WHERE device_id IN ({_DEXCOM_DEVICES}) AND time > :a AND time <= :b ORDER BY time
"""

_FITBIT = """
SELECT w.time, wm.code, w.value::float AS value
FROM ts.wearable_sample w
JOIN core.device d USING (device_id) JOIN ref.device_model m USING (model_id)
JOIN ref.wearable_metric wm USING (metric_id)
WHERE d.patient_id = :p AND m.manufacturer = 'Fitbit' AND NOT m.is_synthetic AND NOT m.is_live_simulator
  AND wm.code IN ('heart_rate', 'active_kcal') AND w.time > :a AND w.time <= :b
ORDER BY w.time
"""

_MEALS = """
SELECT time, meal_type::text AS meal_type, energy_kcal::float, carbs_g::float, protein_g::float, fat_g::float,
       fiber_g::float
FROM ts.meal WHERE patient_id = :p AND time > :a AND time <= :b ORDER BY time
"""

_BASELINE = "SELECT hba1c::float, fasting_glucose::float, bmi::float, bmi_is_synthetic FROM report.patient_baseline WHERE patient_id = :p"


def _years(born: date, on: date) -> int:
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def real_age(birth_date: date, match_age_diff: int | None, on: date) -> float:
    return float(_years(birth_date, on) - (match_age_diff or 0))


def _series(rows) -> pd.Series:
    if not rows:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
    t, v = zip(*rows)
    return pd.Series(v, index=pd.DatetimeIndex(t), dtype=float)


class SqlForecastStore:
    async def load(self, patient_id: UUID, at: datetime | None) -> ForecastInputs | None:
        """Inputs for a forecast at `at` (default: the latest Dexcom reading). None: unknown patient."""
        async with engine().connect() as conn:
            p = {"p": patient_id}
            patient = (await conn.execute(text(_PATIENT), p)).mappings().first()
            if patient is None:
                return None
            if at is None:
                at = await conn.scalar(text(_LATEST), p)
            if at is None:  # no CGM: nothing to forecast from
                return ForecastInputs(patient_id, patient["source"], datetime.now().astimezone(),
                                      _series([]), _series([]))
            glucose = _series((await conn.execute(text(_GLUCOSE), p | {"a": at - GLUCOSE_HISTORY, "b": at})).all())
            after = _series((await conn.execute(text(_GLUCOSE), p | {"a": at, "b": at + AFTER})).all())
            window = p | {"a": at - INPUT_HISTORY, "b": at}
            fitbit = (await conn.execute(text(_FITBIT), window)).all()
            meals = (await conn.execute(text(_MEALS), window)).mappings().all()
            base = (await conn.execute(text(_BASELINE), p)).mappings().first() or {}

        hr = _series([(t, v) for t, code, v in fitbit if code == "heart_rate"])
        kcal = _series([(t, v) for t, code, v in fitbit if code == "active_kcal"])
        meal_frame = pd.DataFrame([dict(m) for m in meals], columns=["time", "meal_type", *MACROS]).set_index("time")
        meal_frame.index = pd.DatetimeIndex(meal_frame.index)
        bmi = base.get("bmi") if not base.get("bmi_is_synthetic") else None
        static = {
            "age": real_age(patient["birth_date"], patient["match_age_diff"], at.date()),
            "male": float(patient["sex"] == "male"),
            "bmi": bmi if bmi is not None else np.nan,
            "hba1c": base.get("hba1c") if base.get("hba1c") is not None else np.nan,
            "fasting_glucose": base.get("fasting_glucose") if base.get("fasting_glucose") is not None else np.nan,
        }
        return ForecastInputs(patient_id, patient["source"], at, glucose, after, hr, kcal, meal_frame, static)
