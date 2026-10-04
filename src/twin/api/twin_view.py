"""Twin API: the full picture of one patient, a timeline, and model-based what-if scenarios.

    GET  /twin/{patient_id}                    everything known about the patient, with provenance
    GET  /twin/{patient_id}/timeline           5-minute series + events between two times
    POST /twin/{patient_id}/simulate/glucose   +30/+60 min forecast, baseline vs scenario
    POST /twin/{patient_id}/simulate/hba1c     population-model HbA1c, baseline vs scenario

Scenarios are model-based: they show what the trained models predict when inputs change.
The glucose forecaster learned short-term patterns from 14 composite patients; the HbA1c
model learned cross-sectional associations in NHANES. Neither is a validated causal model.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any
from uuid import UUID

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from twin.config import settings
from twin.db import engine, session_scope
from twin.models import Encounter, Patient
from twin.models import views as v

router = APIRouter(prefix="/twin", tags=["twin"])

DRUG_FLAGS = {"biguanide": "on_metformin", "sulfonylurea": "on_sulfonylurea", "dpp4_inhibitor": "on_dpp4i",
              "sglt2_inhibitor": "on_sglt2i", "glp1_ra": "on_glp1ra", "thiazolidinedione": "on_tzd",
              "insulin": "on_insulin", "statin": "on_statin", "acei_arb": "on_acei_arb"}


def _rows(result) -> list[dict]:
    return [dict(r) for r in result.mappings().all()]


def _clean(value: Any) -> Any:
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    return value


async def _require(patient_id: UUID) -> None:
    async with session_scope() as s:
        if await s.get(Patient, patient_id) is None:
            raise HTTPException(404, f"unknown patient {patient_id}")


@router.get("/{patient_id}")
async def twin(patient_id: UUID) -> dict:
    await _require(patient_id)
    tz = settings().tz
    async with session_scope() as s:
        one = lambda table: s.execute(select(table).where(table.c.patient_id == patient_id))  # noqa: E731
        summary = _rows(await one(v.patient_summary))[0]
        baseline = _rows(await one(v.patient_baseline))
        observations = _rows(await s.execute(select(v.observation_latest).where(
            v.observation_latest.c.patient_id == patient_id).order_by(v.observation_latest.c.analyte)))
        conditions = _rows(await one(v.patient_conditions))
        medications = _rows(await s.execute(select(v.medication_regimen).where(
            v.medication_regimen.c.patient_id == patient_id).order_by(v.medication_regimen.c.started_at.desc())))
        cgm_window = _rows(await one(v.cgm_window))
        consistency = _rows(await one(v.consistency))
        cgm_daily = _rows(await s.execute(select(v.cgm_daily).where(
            v.cgm_daily.c.patient_id == patient_id).order_by(v.cgm_daily.c.day)))
        activity = _rows(await s.execute(select(v.activity_daily).where(
            v.activity_daily.c.patient_id == patient_id).order_by(v.activity_daily.c.day)))
        nightly = {name: _rows(await s.execute(select(t).where(t.c.patient_id == patient_id).order_by(t.c.night)))
                   for name, t in (("sleep", v.sleep_nightly), ("spo2", v.spo2_nightly), ("hrv", v.hrv_nightly))}
        encounters = (await s.execute(select(Encounter.encounter_class, Encounter.started_at)
                                      .where(Encounter.patient_id == patient_id)
                                      .order_by(Encounter.started_at.desc()).limit(20))).all()
    for row in cgm_daily + activity:
        row["day"] = row["day"].astimezone(tz).date().isoformat()
    return {
        "patient": summary,
        "provenance": {
            "cohort": summary["source"],
            "composite": "composite-patient" in summary["tags"],
            "synthetic_analytes": baseline[0]["synthetic_analytes"] if baseline else [],
            "synthetic_sensor_channels": sorted({m for a in activity for m in a["synthetic_metrics"]}
                                                | ({"sleep"} if any(n["is_synthetic"] for n in nightly["sleep"]) else set())),
            "note": ("Composite twin: CGM/wearable data and baseline labs are real (CGMacros); EHR history, "
                     "conditions and medications are synthetic (Synthea).")
            if "composite-patient" in summary["tags"] else "Single-source real data.",
        },
        "baseline": baseline[0] if baseline else None,
        "observations_latest": observations,
        "conditions": conditions,
        "medications": medications,
        "cgm": {"window": cgm_window[0] if cgm_window else None,
                "consistency": consistency[0] if consistency else None, "daily": cgm_daily},
        "activity_daily": activity,
        "nights": nightly,
        "recent_encounters": [{"class": c, "start": t} for c, t in encounters],
    }


@router.get("/{patient_id}/timeline")
async def timeline(patient_id: UUID, start: datetime | None = None, end: datetime | None = None) -> dict:
    """5-minute series (fused glucose, wearable channels, doses) between start and end;
    defaults to the patient's last 24 hours of data."""
    await _require(patient_id)
    async with engine().connect() as conn:
        if end is None:
            end = await conn.scalar(text(
                "SELECT max(time) FROM ml.series_5min WHERE patient_id = :p"), {"p": patient_id})
        if end is None:
            return {"patient_id": str(patient_id), "series": [], "note": "no CGM/wearable series for this patient"}
        start = start or end - pd.Timedelta(hours=24)
        result = await conn.execute(text(
            "SELECT * FROM ml.series_5min WHERE patient_id = :p AND time BETWEEN :a AND :b ORDER BY time"),
            {"p": patient_id, "a": start, "b": end})
        series = [{k: _clean(val) for k, val in r.items() if k != "patient_id"} for r in result.mappings()]
    return {"patient_id": str(patient_id), "start": start, "end": end, "series": series}


# ── scenarios ────────────────────────────────────────────────────────


@lru_cache
def _forecaster():
    from twin.ml import forecast

    try:
        return forecast.load(settings())
    except FileNotFoundError:
        raise HTTPException(503, "glucose forecaster not trained; run `twin export-features && twin train-baselines`")


@lru_cache
def _population():
    from twin.ml import population

    try:
        return population.load(settings())
    except FileNotFoundError:
        raise HTTPException(503, "HbA1c model not trained; run `twin export-features && twin train-baselines`")


class GlucoseScenario(BaseModel):
    at: datetime | None = Field(None, description="forecast origin; default: latest time with full features")
    extra_met_minutes_30: float = Field(0, description="added activity in the last 30 min (MET-minutes)")
    heart_rate_delta: float = Field(0, description="change in mean heart rate over the last 30 min (bpm)")
    insulin_fast_units: float = Field(0, ge=0, description="extra fast-acting insulin in the last 2 h (U)")


@router.post("/{patient_id}/simulate/glucose")
async def simulate_glucose(patient_id: UUID, scenario: GlucoseScenario) -> dict:
    from twin.ml import forecast

    await _require(patient_id)
    bundle = _forecaster()
    async with engine().connect() as conn:
        result = await conn.execute(text("SELECT * FROM ml.series_5min WHERE patient_id = :p ORDER BY time"),
                                    {"p": patient_id})
        series = pd.DataFrame(result.fetchall(), columns=list(result.keys()))
    if series.empty:
        raise HTTPException(422, "no CGM series for this patient; the glucose forecaster needs CGM")
    for col in series.columns:
        if col not in ("patient_id", "time", "glucose_sources", "glucose_censored"):
            series[col] = pd.to_numeric(series[col], errors="coerce").astype(float)
    feats = forecast.build_features(series).set_index("time")
    usable = feats.dropna(subset=["glucose", "glucose_lag60"])
    if usable.empty:
        raise HTTPException(422, "not enough contiguous CGM history (needs 60 min)")
    row = usable.loc[[usable.index[usable.index <= scenario.at][-1]]] if scenario.at else usable.iloc[[-1]]

    changed = row.copy()
    for col, delta in (("met_minutes_30", scenario.extra_met_minutes_30), ("met_minutes_60", scenario.extra_met_minutes_30),
                       ("heart_rate_30", scenario.heart_rate_delta), ("insulin_fast_2h", scenario.insulin_fast_units)):
        if delta and col in changed:
            changed[col] = changed[col].fillna(0) + delta
    base, alt = forecast.predict(bundle, row), forecast.predict(bundle, changed)
    return {
        "patient_id": str(patient_id), "at": row.index[0], "glucose_now": float(row["glucose"].iloc[0]),
        "forecast": {f"+{h}min": {"baseline": round(float(base[h][0]), 1), "scenario": round(float(alt[h][0]), 1),
                                  "difference": round(float(alt[h][0] - base[h][0]), 1)} for h in base},
        "unused_inputs": sorted({"insulin_fast_2h", "steps_60"} - set(bundle["features"])),
        "caveat": "Model-based what-if from a forecaster trained on 14 patients; not a causal or clinical prediction.",
    }


class Hba1cScenario(BaseModel):
    steps_per_day: float | None = Field(None, ge=0, description="replace daily steps")
    bmi: float | None = Field(None, gt=10, lt=80, description="replace BMI")
    add_drug_classes: list[str] = Field(default_factory=list, description=f"any of {sorted(DRUG_FLAGS)}")
    remove_drug_classes: list[str] = Field(default_factory=list)


@router.post("/{patient_id}/simulate/hba1c")
async def simulate_hba1c(patient_id: UUID, scenario: Hba1cScenario) -> dict:
    from twin.ml import population

    await _require(patient_id)
    unknown = set(scenario.add_drug_classes + scenario.remove_drug_classes) - set(DRUG_FLAGS)
    if unknown:
        raise HTTPException(422, f"unknown drug classes {sorted(unknown)}; use {sorted(DRUG_FLAGS)}")
    bundle = _population()
    async with engine().connect() as conn:
        result = await conn.execute(text("SELECT * FROM ml.patient_static WHERE patient_id = :p"), {"p": patient_id})
        static = pd.DataFrame(result.fetchall(), columns=list(result.keys()))
    static["cohort"] = "nhanes"  # population.prepare filters on cohort; the model applies to any patient
    for col in static.columns:
        if static[col].map(lambda x: type(x).__name__ == "Decimal").any():
            static[col] = pd.to_numeric(static[col]).astype(float)
    if static.hba1c.isna().all():
        static["hba1c"] = 0.0  # prepare() needs a value; the target is not used for prediction
    X = population.prepare(static)[bundle["features"]].astype(float)
    alt = X.copy()
    if scenario.steps_per_day is not None:
        alt["steps_per_valid_day"] = scenario.steps_per_day
    if scenario.bmi is not None:
        alt["bmi"] = scenario.bmi
    for cls in scenario.add_drug_classes:
        alt[DRUG_FLAGS[cls]] = 1.0
    for cls in scenario.remove_drug_classes:
        alt[DRUG_FLAGS[cls]] = 0.0
    base, new = bundle["model"].predict(X)[0], bundle["model"].predict(alt)[0]
    return {
        "patient_id": str(patient_id),
        "observed_hba1c": _clean(float(static.hba1c.iloc[0])) if static.hba1c.iloc[0] else None,
        "model_hba1c": {"baseline": round(float(base), 2), "scenario": round(float(new), 2),
                        "difference": round(float(new - base), 2)},
        "inputs_changed": {c: {"from": _clean(X[c].iloc[0]), "to": _clean(alt[c].iloc[0])}
                           for c in X.columns if not (pd.isna(X[c].iloc[0]) and pd.isna(alt[c].iloc[0]))
                           and X[c].iloc[0] != alt[c].iloc[0]},
        "caveat": ("Cross-sectional association model (NHANES 2011-2014). Differences are associations, not "
                   "treatment effects: drug classes are confounded by indication."),
    }
