"""`ingest-nhanes` step: NHANES 2011-2014 adults with diabetes into the twin DB.

Each participant becomes a single-source real patient (no FHIR record): demographics,
labs + BP + anthropometrics (core.observation), smoking status (coded), self-reported
conditions, prescription medications (core.medication_regimen, mapped to RxNorm
ingredients via seeds/mappings/medication_names.csv), and minute-level wrist steps with
daily wear minutes (ts.wearable_sample, ActiGraph GT3X+).
"""

from __future__ import annotations

import csv
import uuid
from collections import Counter
from datetime import datetime, time, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
from sqlalchemy import delete, select

from twin.config import Settings
from twin.db import copy_records, engine, lookup, session_scope, upsert
from twin.fhir.client import twin_id
from twin.models import (
    Concept,
    Condition,
    DataSource,
    Device,
    DeviceModel,
    Medication,
    MedicationRegimen,
    Observation,
    ObservationCode,
    Patient,
    PatientTag,
    Tag,
    WearableMetric,
    WearableSample,
)
from twin.sources import nhanes

SOURCE = "nhanes"
DEVICE = ("ActiGraph", "GT3X+ (wrist)")
VALID_DAY_WEAR_MINUTES = 600  # >= 10 h of wear, the usual accelerometry rule


def patient_uuid(seqn: int) -> uuid.UUID:
    return uuid.UUID(twin_id("patient", SOURCE, seqn))


def _medication_map(cfg: Settings) -> dict[str, int]:
    path = cfg.seeds_dir / "mappings" / "medication_names.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        return {r["source_name"]: int(r["medication_id"]) for r in csv.DictReader(fh)
                if r["source"] == SOURCE and r["medication_id"]}


async def run_ingest_nhanes(cfg: Settings, log=print) -> dict:
    raw = cfg.data_dir / "raw" / "nhanes"
    if not (raw / "DEMO_G.xpt").exists():
        log(f"no NHANES data in {raw}; run seeds/download_nhanes.sh (skipped)")
        return {}
    tz = cfg.tz
    people, table = nhanes.cohort(raw)
    by_seqn = {p.seqn: p for p in people}
    log(f"cohort: {len(people)} adults with diabetes ({sum(p.diagnosed for p in people)} diagnosed)")

    async with session_scope() as s:
        source_id = await s.scalar(select(DataSource.source_id).where(DataSource.code == SOURCE))
        codes = await lookup(s, ObservationCode.loinc, ObservationCode.code_id)
        tags = await lookup(s, Tag.code, Tag.tag_id)
        known_meds = set(await s.scalars(select(Medication.medication_id)))
        model_id = await s.scalar(select(DeviceModel.model_id).where(
            DeviceModel.manufacturer == DEVICE[0], DeviceModel.model_name == DEVICE[1]))
        metrics = await lookup(s, WearableMetric.code, WearableMetric.metric_id)

        # Patients (replacing earlier NHANES rows wholesale: everything they own cascades).
        await s.execute(delete(Patient).where(Patient.source_id == source_id))
        await upsert(s, Patient, [{
            "patient_id": patient_uuid(p.seqn), "sex": p.sex, "birth_date": nhanes.imputed_birth_date(p),
            "birth_date_imputed": True, "race_ethnicity": p.race_ethnicity, "source_id": source_id,
            "source_subject_id": str(p.seqn),
        } for p in people], key=["patient_id"])
        await upsert(s, PatientTag, [{"patient_id": patient_uuid(p.seqn), "tag_id": tags["undiagnosed-diabetes"]}
                                      for p in people if not p.diagnosed], key=["patient_id", "tag_id"])

        # Concepts for conditions and smoking answers.
        concept_rows = {(nhanes.SNOMED, c, d) for c, d in [nhanes.T2D, *nhanes.SMOKING.values()]}
        concept_rows |= {(nhanes.SNOMED, c, d) for _, _, c, d in nhanes.CONDITIONS}
        await upsert(s, Concept, [{"system": a, "code": b, "display": c} for a, b, c in sorted(concept_rows)],
                      key=["system", "code"])
        concepts = dict((await s.execute(select(Concept.code, Concept.concept_id)
                                         .where(Concept.system == nhanes.SNOMED))).all())

        # Observations at the exam: labs, BP, anthropometrics; smoking status coded.
        obs, conds = [], []
        for p in people:
            row, pid, at = table.loc[p.seqn], patient_uuid(p.seqn), nhanes.exam_time(p, tz)
            for loinc, value in nhanes.numeric_observations(row):
                if value > 0:  # 0 is never a valid lab/BP value here
                    obs.append((pid, codes[loinc], at, Decimal(str(value)), None, source_id))
            smoke = nhanes.smoking_status(row)
            if smoke:
                obs.append((pid, codes["72166-2"], at, None, concepts[smoke[0]], source_id))
            for code, _, onset in nhanes.conditions(p, row):
                conds.append({"patient_id": pid, "concept_id": concepts[code],
                              "onset_at": datetime.combine(onset, time(0), tzinfo=tz), "source_id": source_id})
        await copy_records(s, Observation, ("patient_id", "code_id", "effective_at", "value_num", "value_concept_id",
                                            "source_id"), obs)
        await upsert(s, Condition, conds, key=["patient_id", "concept_id", "onset_at"])

        # Prescriptions: current at the exam; started RXDDAYS before it when reported.
        med_map = _medication_map(cfg)
        rx = nhanes.prescriptions(raw, set(by_seqn))
        regimens, unmapped = [], Counter()
        for i, r in enumerate(rx.itertuples()):
            mid = med_map.get(r.name)
            if mid is None or mid not in known_meds:
                unmapped[r.name] += 1
                continue
            p = by_seqn[r.SEQN]
            start = nhanes.exam_time(p, tz) - timedelta(days=float(r.days) if pd.notna(r.days) else 0)
            regimens.append({"patient_id": patient_uuid(r.SEQN), "medication_id": mid, "started_at": start,
                             "source_id": source_id, "source_ref": f"{r.SEQN}/{i}"})
        await upsert(s, MedicationRegimen, regimens, key=["patient_id", "source_id", "source_ref", "medication_id"])

        # One ActiGraph per participant with step data.
        await upsert(s, Device, [{"patient_id": patient_uuid(p.seqn), "model_id": model_id} for p in people],
                      key=["patient_id", "model_id"])
        devices = dict((await s.execute(select(Device.patient_id, Device.device_id)
                                        .where(Device.model_id == model_id))).all())

    # Minute-level steps (worn minutes with steps > 0) and daily wear minutes.
    steps_id, wear_id = metrics["steps"], metrics["wear_minutes"]
    batch, n_samples, valid_days, people_with_steps = [], 0, Counter(), set()
    for seqn, day, steps, worn in nhanes.minute_steps(raw, set(by_seqn)):
        p = by_seqn[seqn]
        device_id = devices[patient_uuid(seqn)]
        start = pd.Timestamp(datetime.combine(p.exam_date + timedelta(days=day - 1), time(0)), tz=tz)
        minutes = pd.date_range(start, periods=1440, freq="min")
        keep = worn & np.isfinite(steps) & (steps > 0)
        batch += [(device_id, steps_id, t.to_pydatetime(), Decimal(str(round(float(v), 1))))
                  for t, v in zip(minutes[keep], steps[keep])]
        if worn.any():
            batch.append((device_id, wear_id, start.to_pydatetime(), Decimal(int(worn.sum()))))
            people_with_steps.add(seqn)
            valid_days[seqn] += int(worn.sum()) >= VALID_DAY_WEAR_MINUTES
        if len(batch) >= 200_000:
            async with session_scope() as s:
                n_samples += await copy_records(s, WearableSample, ("device_id", "metric_id", "time", "value"), batch)
            batch = []
    if batch:
        async with session_scope() as s:
            n_samples += await copy_records(s, WearableSample, ("device_id", "metric_id", "time", "value"), batch)

    async with engine().connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.exec_driver_sql("CALL refresh_continuous_aggregate('ts.wearable_daily', NULL, NULL)")

    report = {
        "patients": len(people), "diagnosed": sum(p.diagnosed for p in people),
        "observations": len(obs), "conditions": len(conds),
        "medication_rows": len(rx), "medication_rows_mapped": len(regimens),
        "unmapped_names": len(unmapped), "patients_with_steps": len(people_with_steps),
        "patients_with_4_valid_days": sum(1 for d in valid_days.values() if d >= 4),
        "wearable_samples": n_samples,
    }
    log(report)
    if unmapped:
        log(f"most frequent unmapped drug names: {unmapped.most_common(10)}")
    out = cfg.reports_dir / "nhanes_report.csv"
    with out.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["metric", "value"])
        writer.writerows(report.items())
        writer.writerows((f"unmapped:{name}", n) for name, n in unmapped.most_common())
    return report
