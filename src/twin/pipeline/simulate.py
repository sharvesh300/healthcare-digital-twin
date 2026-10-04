"""`simulate-wearables` step: synthetic sleep, SpO2, respiration, stress and nightly HRV for
every composite twin (twin.synthetic.wearables). SYNTHETIC: stored under a device whose model
is flagged `is_synthetic`, and the patient is tagged `synthetic-sensors`.

The generator only runs within the patient's real recording window and is driven by the
patient's real heart rate, age, sex, BMI, sleep apnoea and COPD.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import delete, select

from twin.config import Settings
from twin.db import copy_records, engine, lookup, session_scope, upsert
from twin.models import (
    DataSource,
    Device,
    DeviceModel,
    Patient,
    PatientTag,
    SleepSegment,
    Tag,
    WearableMetric,
    WearableSample,
)
from twin.models import views as v
from twin.pipeline.ehr import fhir_patients
from twin.synthetic.wearables import Profile, generate

GENERATOR = ("Twin generator", "Garmin-like wearable (synthetic)")
SOURCE_TZ = {"bigideas": "America/New_York"}  # default: settings().source_tz


async def _real_minutes(s, patient_id, metric_ids: list[int]) -> pd.DataFrame:
    """Real (non-synthetic device) wearable samples for the patient, one column per metric."""
    rows = (await s.execute(
        select(WearableSample.time, WearableMetric.code, WearableSample.value)
        .join(Device, Device.device_id == WearableSample.device_id)
        .join(DeviceModel, DeviceModel.model_id == Device.model_id)
        .join(WearableMetric, WearableMetric.metric_id == WearableSample.metric_id)
        .where(Device.patient_id == patient_id, DeviceModel.is_synthetic.is_(False),
               WearableSample.metric_id.in_(metric_ids))
    )).all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["time", "metric", "value"])
    df["value"] = df["value"].astype(float)
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.floor("min")
    return df.pivot_table(index="time", columns="metric", values="value", aggfunc="mean")


async def run_simulate_wearables(cfg: Settings, log=print) -> list[dict]:
    async with session_scope() as s:
        patients = list(await s.scalars(fhir_patients()))
        metrics = await lookup(s, WearableMetric.code, WearableMetric.metric_id)
        model_id = await s.scalar(select(DeviceModel.model_id).where(
            DeviceModel.manufacturer == GENERATOR[0], DeviceModel.model_name == GENERATOR[1]))
        tag_id = await s.scalar(select(Tag.tag_id).where(Tag.code == "synthetic-sensors"))
        sources = dict((await s.execute(select(Patient.patient_id, DataSource.code)
                                        .join(DataSource, DataSource.source_id == Patient.source_id))).all())

    report = []
    for pid in patients:
        tz = ZoneInfo(SOURCE_TZ.get(sources[pid], cfg.source_tz))
        async with session_scope() as s:
            summary = (await s.execute(select(v.patient_summary.c.age, v.patient_summary.c.sex)
                                       .where(v.patient_summary.c.patient_id == pid))).one()
            bmi = await s.scalar(select(v.patient_baseline.c.bmi).where(v.patient_baseline.c.patient_id == pid))
            groups = set(await s.scalars(select(v.patient_conditions.c.condition_group)
                                         .where(v.patient_conditions.c.patient_id == pid)))
            hba1c = await s.scalar(select(v.patient_baseline.c.hba1c).where(v.patient_baseline.c.patient_id == pid))
            real = await _real_minutes(s, pid, [metrics[m] for m in ("heart_rate", "mets", "activity_level", "ibi_ms")])
        if real.empty or "heart_rate" not in real:
            log(f"{pid}: no real heart rate; skipped")
            continue
        has_real_hrv = "ibi_ms" in real and real["ibi_ms"].notna().sum() > 1000
        profile = Profile(
            patient_id=str(pid), age=int(summary.age), sex=str(summary.sex), bmi=float(bmi) if bmi else None,
            sleep_apnea="sleep_apnea" in groups, copd="copd" in groups,
            dysglycaemia=bool(groups & {"t2d", "prediabetes"}) or (hba1c is not None and float(hba1c) >= 5.7),
            has_real_hrv=has_real_hrv,
        )
        hr = real["heart_rate"].dropna().tz_convert(tz)
        active = None
        if "mets" in real:
            active = (real["mets"] >= 3).tz_convert(tz)
        elif "activity_level" in real:
            active = (real["activity_level"] >= 2).tz_convert(tz)
        out = generate(profile, hr.index.min().date(), hr.index.max().date(), tz, heart_rate=hr, active=active)

        async with session_scope() as s:
            await upsert(s, Device, [{"patient_id": pid, "model_id": model_id}], key=["patient_id", "model_id"])
            device_id = await s.scalar(select(Device.device_id).where(Device.patient_id == pid,
                                                                      Device.model_id == model_id))
            await s.execute(delete(WearableSample).where(WearableSample.device_id == device_id))
            await s.execute(delete(SleepSegment).where(SleepSegment.device_id == device_id))
            await copy_records(s, SleepSegment, ("device_id", "start_time", "end_time", "stage"),
                               [(device_id, a, b, str(st)) for a, b, st in out.sleep])
            counts = Counter()
            for code, series in out.samples.items():
                counts[code] = await copy_records(s, WearableSample, ("device_id", "metric_id", "time", "value"), (
                    (device_id, metrics[code], t.to_pydatetime(), Decimal(str(float(val))))
                    for t, val in series.items()))
            await upsert(s, PatientTag, [{"patient_id": pid, "tag_id": tag_id}], key=["patient_id", "tag_id"])
        row = {"patient_id": str(pid), "source": sources[pid], "age": profile.age, "bmi": profile.bmi,
               "sleep_apnea": profile.sleep_apnea, "copd": profile.copd, "real_hrv": has_real_hrv,
               "sleep_segments": len(out.sleep), **counts}
        report.append(row)
        log(row)

    async with engine().connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.exec_driver_sql("CALL refresh_continuous_aggregate('ts.wearable_daily', NULL, NULL)")
    return report
