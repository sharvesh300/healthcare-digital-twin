"""`load-sensors` step: devices and raw CGM/wearable readings into TimescaleDB (twin time)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert

from twin.config import Settings
from twin.db import copy_records, engine, lookup, session_scope
from twin.models import (
    DataSource,
    Device,
    DeviceModel,
    GlucoseReading,
    Patient,
    WearableMetric,
    WearableSample,
)
from twin.pipeline.patients import load_participants
from twin.sources import cgmacros

# CGMacros column / stream -> (manufacturer, model_name) in ref.device_model
DEXCOM = ("Dexcom", "G6 Pro")
LIBRE = ("Abbott", "FreeStyle Libre Pro")
CONTOUR = ("Ascensia", "Contour Next")
FITBIT = ("Fitbit", "Sense")
CGM_MODELS = {"Dexcom GL": DEXCOM, "Libre GL": LIBRE}
CONTINUOUS_AGGREGATES = ("ts.glucose_daily", "ts.wearable_daily")
# CGMacros Fitbit column (after parsing) -> ref.wearable_metric code
FITBIT_METRICS = {"heart_rate": "heart_rate", "mets": "mets", "activity_level": "activity_level", "active_kcal": "active_kcal"}


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
    by_code = await lookup(session, WearableMetric.code, WearableMetric.metric_id)
    metric_ids = {column: by_code[code] for column, code in FITBIT_METRICS.items()}
    device_ids = list(devices.values())

    # Idempotent reload: replace this patient's rows wholesale.
    await session.execute(delete(GlucoseReading).where(GlucoseReading.device_id.in_(device_ids)))
    await session.execute(delete(WearableSample).where(WearableSample.device_id.in_(device_ids)))

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

    # Fitbit: one row per (minute, metric) that has a value.
    fitbit = streams.fitbit.copy()
    fitbit.index = cgmacros.shift(fitbit.index, offset_days, tz)
    fitbit = fitbit[fitbit.index.notna()]
    samples = []
    for column, metric_id in metric_ids.items():
        if column not in fitbit:
            continue
        values = fitbit[column].dropna()
        samples += [(devices[FITBIT], metric_id, t.to_pydatetime(), _dec(v, 3)) for t, v in values.items()]
    stats["fitbit_samples"] = await copy_records(
        session, WearableSample, ("device_id", "metric_id", "time", "value"), samples)
    stats["ignored_columns"] = ",".join(streams.ignored_columns)
    return stats


async def run_load_sensors(cfg: Settings, log=print) -> list[dict]:
    participants = load_participants(cfg)
    async with session_scope() as s:
        patients = (await s.execute(
            select(Patient.patient_id, Patient.source_subject_id, Patient.time_offset)
            .join(DataSource, DataSource.source_id == Patient.source_id)
            .where(DataSource.code == "cgmacros")
            .order_by(Patient.source_subject_id)
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
        for model in (GlucoseReading, WearableSample):
            await conn.execute(
                text("SELECT add_compression_policy(:t, compress_after => INTERVAL '30 days', if_not_exists => true)"),
                {"t": f"{model.__table__.schema}.{model.__table__.name}"},
            )
    return results
