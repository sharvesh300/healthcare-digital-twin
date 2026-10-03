"""`load-sensors` step: devices, meals and raw readings into TimescaleDB (twin time)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert

from twin import cgmacros
from twin.config import Settings
from twin.db import copy_records, engine, session_scope
from twin.models import Device, DeviceModel, FitbitReading, GlucoseReading, Meal, MealPhoto, Patient
from twin.patients import load_participants

# CGMacros column / stream -> (manufacturer, model_name) in ref.device_model
DEXCOM = ("Dexcom", "G6 Pro")
LIBRE = ("Abbott", "FreeStyle Libre Pro")
CONTOUR = ("Ascensia", "Contour Next")
FITBIT = ("Fitbit", "Sense")
CGM_MODELS = {"Dexcom GL": DEXCOM, "Libre GL": LIBRE}
CONTINUOUS_AGGREGATES = ("ts.glucose_daily", "ts.fitbit_daily")


def _none(value):
    return None if value is None or (isinstance(value, float) and np.isnan(value)) else value


def _dec(value, places: int) -> Decimal | None:
    value = _none(value)
    return None if value is None else round(Decimal(str(value)), places)


async def _ensure_devices(session, patient_id: uuid.UUID) -> dict[tuple[str, str], int]:
    models = (await session.execute(select(DeviceModel.manufacturer, DeviceModel.model_name, DeviceModel.model_id))).all()
    model_ids = {(m, n): mid for m, n, mid in models}
    devices = {}
    for model in (*CGM_MODELS.values(), CONTOUR, FITBIT):
        stmt = insert(Device).values(patient_id=patient_id, model_id=model_ids[model])
        devices[model] = await session.scalar(
            stmt.on_conflict_do_update(
                index_elements=[Device.patient_id, Device.model_id], set_={"patient_id": stmt.excluded.patient_id}
            ).returning(Device.device_id)
        )
    return devices


async def _load_patient(session, cfg: Settings, patient_id: uuid.UUID, subject_id: str, offset_days: int,
                        participant: cgmacros.Participant) -> dict:
    df = cgmacros.read_sensor_csv(cgmacros.sensor_csv_path(cfg.cgmacros_dir, subject_id))
    streams = cgmacros.parse_streams(df)
    tz = cfg.source_tz
    stats: dict = {"subject": subject_id}

    devices = await _ensure_devices(session, patient_id)
    device_ids = list(devices.values())

    # Idempotent reload: replace this patient's rows wholesale.
    await session.execute(delete(GlucoseReading).where(GlucoseReading.device_id.in_(device_ids)))
    await session.execute(delete(FitbitReading).where(FitbitReading.device_id.in_(device_ids)))
    await session.execute(delete(Meal).where(Meal.patient_id == patient_id))

    glucose: list[tuple] = []
    for column, model in CGM_MODELS.items():
        series = streams.glucose[column]
        times = cgmacros.shift(series.index, offset_days, tz)
        rows = [(devices[model], t.to_pydatetime(), int(v)) for t, v in zip(times, series.to_numpy()) if pd.notna(t)]
        glucose += rows
        stats[column] = len(rows)
    # Fingersticks from bio.csv happen on study day 1.
    day1 = streams.study_day_1 + timedelta(days=offset_days)
    glucose += [(devices[CONTOUR], datetime.combine(day1, clock, tzinfo=cfg.tz), int(round(value)))
                for clock, value in participant.fingersticks]
    stats["fingerstick"] = len(participant.fingersticks)
    await copy_records(session, GlucoseReading, ("device_id", "time", "glucose_mg_dl"), glucose)

    fitbit = streams.fitbit.copy()
    fitbit.index = cgmacros.shift(fitbit.index, offset_days, tz)
    fitbit = fitbit[fitbit.index.notna()]
    stats["fitbit"] = await copy_records(
        session, FitbitReading, ("device_id", "time", "heart_rate", "mets", "activity_level", "active_kcal"),
        (
            (devices[FITBIT], t.to_pydatetime(),
             None if _none(hr) is None else int(hr), _dec(mets, 1),
             None if _none(level) is None else int(level), _dec(kcal, 3))
            for t, (hr, mets, level, kcal) in zip(fitbit.index, fitbit.itertuples(index=False))
        ),
    )

    meals = streams.meals.copy()
    meals.index = cgmacros.shift(meals.index, offset_days, tz)
    meals = meals[meals.index.notna()]
    meal_rows = [
        {"patient_id": patient_id, "started_at": t.to_pydatetime(), "meal_type": m.meal_type,
         "energy_kcal": _dec(m.energy_kcal, 1), "carbs_g": _dec(m.carbs_g, 1), "protein_g": _dec(m.protein_g, 1),
         "fat_g": _dec(m.fat_g, 1), "fiber_g": _dec(m.fiber_g, 1), "pct_consumed": _dec(m.pct_consumed, 2)}
        for t, m in zip(meals.index, meals.itertuples(index=False))
    ]
    meal_ids: list[tuple[datetime, int]] = []
    if meal_rows:
        result = await session.execute(
            insert(Meal).values(meal_rows).on_conflict_do_nothing().returning(Meal.started_at, Meal.meal_id)
        )
        meal_ids = sorted(result.all())
    stats["meals"] = len(meal_ids)

    # Each photo belongs to the most recent meal start at or before it
    # (the start photo shares the meal's timestamp; the end photo follows it).
    photos = streams.photos.copy()
    photos.index = cgmacros.shift(photos.index, offset_days, tz)
    photos = photos[photos.index.notna()]
    starts = pd.DatetimeIndex([t for t, _ in meal_ids])
    photo_rows = {}
    for t, path in photos.items():
        pos = starts.searchsorted(t, side="right") - 1
        if pos >= 0:
            key = (meal_ids[pos][1], t.to_pydatetime())
            photo_rows.setdefault(key, {"meal_id": key[0], "taken_at": key[1], "path": f"CGMacros-{subject_id}/{path}"})
    if photo_rows:
        await session.execute(insert(MealPhoto).values(list(photo_rows.values())).on_conflict_do_nothing())
    stats["photos"] = len(photo_rows)
    stats["ignored_columns"] = ",".join(streams.ignored_columns)
    return stats


async def run_load_sensors(cfg: Settings, log=print) -> list[dict]:
    participants = load_participants(cfg)
    async with session_scope() as s:
        patients = (await s.execute(
            select(Patient.patient_id, Patient.source_subject_id, Patient.time_offset).order_by(Patient.source_subject_id)
        )).all()

    results = []
    for patient_id, subject_id, offset in patients:
        async with session_scope() as s:  # one transaction per patient
            stats = await _load_patient(s, cfg, patient_id, subject_id, offset.days, participants[subject_id])
        results.append(stats)
        log(stats)

    # Continuous-aggregate refresh and policies cannot run inside a transaction.
    async with engine().connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        for view in CONTINUOUS_AGGREGATES:
            await conn.exec_driver_sql(f"CALL refresh_continuous_aggregate('{view}', NULL, NULL)")
        for model in (GlucoseReading, FitbitReading):
            await conn.execute(
                text("SELECT add_compression_policy(:t, compress_after => INTERVAL '30 days', if_not_exists => true)"),
                {"t": f"{model.__table__.schema}.{model.__table__.name}"},
            )
    return results
