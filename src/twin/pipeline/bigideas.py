"""`ingest-bigideas` step: BIG IDEAs participants as composite twins.

Each of the 16 participants (real Dexcom G6 CGM + Empatica E4: heart rate, inter-beat
intervals, skin temperature, EDA) is matched to a Synthea patient from the general-
population cohort (data/synthea_general, ages 35-65):

  * same sex
  * age 35-65 at the last encounter (the study's inclusion range); women 50-65, as the
    study enrolled only post-menopausal women
  * same glycaemic group: HbA1c >= 5.7 -> Synthea prediabetes (and no T2D);
    otherwise neither prediabetes nor T2D
  * then nearest Synthea HbA1c (healthy Synthea patients often have none; ties are broken
    by a stable hash so the match is reproducible)

BIG IDEAs has no age or BMI, so match_age_diff / match_bmi_diff stay NULL. Sensor data are
shifted so the window starts the day after the Synthea patient's last encounter.
"""

from __future__ import annotations

import csv
import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta
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
    GlucoseReading,
    Observation,
    ObservationCode,
    Patient,
    PatientTag,
    Tag,
    WearableMetric,
    WearableSample,
)
from twin.sources import bigideas
from twin.sources.synthea import SyntheaPatient, index_cohort
from twin.sources.synthea_ehr import parse_bundle

SOURCE = "bigideas"
T2D, PREDIABETES = "44054006", "714628002"
DEXCOM = ("Dexcom", "G6")
E4 = ("Empatica", "E4")
PREDIABETES_HBA1C = 5.7


@dataclass
class Candidate:
    patient: SyntheaPatient
    group: str  # 'prediabetes' | 'neither'
    hba1c: float | None
    age: int


@dataclass
class Match:
    participant: bigideas.Participant
    candidate: Candidate


def _candidates(cfg: Settings, tz: ZoneInfo) -> list[Candidate]:
    out = []
    for p in index_cohort(cfg.synthea_general_fhir_dir):
        if p.deceased:
            continue
        age = p.age_on(p.last_encounter_local_date(tz))
        if not (35 <= age <= 65) or (p.sex == "female" and age < 50):
            continue
        ehr = parse_bundle(cfg.synthea_general_fhir_dir / p.bundle_file, {"4548-4"})
        codes = {c.code for c in ehr.conditions}
        if T2D in codes:
            continue
        a1c = sorted(ehr.numeric, key=lambda n: n.effective_at)
        out.append(Candidate(p, "prediabetes" if PREDIABETES in codes else "neither",
                             a1c[-1].value if a1c else None, age))
    return out


def _tiebreak(a: str, b: str) -> int:
    return int(hashlib.sha256(f"{a}/{b}".encode()).hexdigest()[:8], 16)


def match(participants: list[bigideas.Participant], candidates: list[Candidate]) -> list[Match]:
    def pool(p):
        group = "prediabetes" if p.hba1c >= PREDIABETES_HBA1C else "neither"
        return [c for c in candidates if c.patient.sex == p.sex and c.group == group]

    used, out = set(), []
    for p in sorted(participants, key=lambda p: (len(pool(p)), p.subject_id)):
        options = [c for c in pool(p) if c.patient.patient_id not in used]
        if not options:
            continue
        best = min(options, key=lambda c: (abs(c.hba1c - p.hba1c) if c.hba1c is not None else 99.0,
                                           _tiebreak(p.subject_id, c.patient.patient_id)))
        used.add(best.patient.patient_id)
        out.append(Match(p, best))
    return sorted(out, key=lambda m: m.participant.subject_id)


async def run_ingest_bigideas(cfg: Settings, log=print) -> list[dict]:
    raw = cfg.data_dir / "raw" / "bigideas"
    if not (raw / "Demographics.csv").exists() or not cfg.synthea_general_fhir_dir.exists():
        log("BIG IDEAs data or the general Synthea cohort is missing; run seeds/download_bigideas.sh and "
            "COHORT_DIR=synthea_general KEEP_MODULE=none AGES=35-65 POPULATION=200 SEED=43 "
            "seeds/generate_cohort.sh (skipped)")
        return []
    tz = cfg.tz
    participants = [p for p in bigideas.read_demographics(raw) if bigideas.path(raw, p.subject_id, "Dexcom").exists()]
    matches = match(participants, _candidates(cfg, tz))
    log(f"{len(matches)} of {len(participants)} participants matched")

    async with session_scope() as s:
        source_id = await s.scalar(select(DataSource.source_id).where(DataSource.code == SOURCE))
        tag_id = await s.scalar(select(Tag.tag_id).where(Tag.code == "composite-patient"))
        hba1c_code = await s.scalar(select(ObservationCode.code_id).where(ObservationCode.loinc == "4548-4"))
        keep = {m.candidate.patient.patient_id for m in matches}
        stale = [pid for pid in await s.scalars(select(Patient.patient_id).where(Patient.source_id == source_id))
                 if str(pid) not in keep]
        if stale:
            await s.execute(delete(Patient).where(Patient.patient_id.in_(stale)))
        models = dict(((m, n), mid) for m, n, mid in (await s.execute(
            select(DeviceModel.manufacturer, DeviceModel.model_name, DeviceModel.model_id))).all())
        metrics = await lookup(s, WearableMetric.code, WearableMetric.metric_id)

    report = []
    for m in matches:
        p, syn = m.participant, m.candidate.patient
        pid = uuid.UUID(syn.patient_id)
        glucose = bigideas.read_dexcom(bigideas.path(raw, p.subject_id, "Dexcom"))
        day1 = glucose.index.min().date()
        offset = (syn.last_encounter_local_date(tz) + timedelta(days=1) - day1).days

        async with session_scope() as s:
            await upsert(s, Patient, [{
                "patient_id": pid, "mrn": syn.mrn, "given_name": syn.given_name, "family_name": syn.family_name,
                "name_prefix": syn.name_prefix, "sex": p.sex, "birth_date": syn.birth_date,
                "address_city": syn.address_city, "address_state": syn.address_state,
                "address_postal": syn.address_postal, "source_id": source_id, "source_subject_id": p.subject_id,
                "time_offset": timedelta(days=offset),
            }], key=["patient_id"])
            await upsert(s, PatientTag, [{"patient_id": pid, "tag_id": tag_id}], key=["patient_id", "tag_id"])
            await s.execute(delete(Observation).where(Observation.patient_id == pid,
                                                      Observation.source_id == source_id))
            lab_at = datetime.combine(day1 + timedelta(days=offset), time(8, 0), tzinfo=ZoneInfo(bigideas.TZ))
            await upsert(s, Observation, [{"patient_id": pid, "code_id": hba1c_code, "effective_at": lab_at,
                                            "value_num": Decimal(str(p.hba1c)), "source_id": source_id}],
                          key=["patient_id", "code_id", "effective_at"])
            await upsert(s, Device, [{"patient_id": pid, "model_id": models[DEXCOM]},
                                      {"patient_id": pid, "model_id": models[E4]}], key=["patient_id", "model_id"])
            devices = dict((await s.execute(select(Device.model_id, Device.device_id)
                                            .where(Device.patient_id == pid))).all())
            dexcom, e4 = devices[models[DEXCOM]], devices[models[E4]]
            await s.execute(delete(GlucoseReading).where(GlucoseReading.device_id == dexcom))
            await s.execute(delete(WearableSample).where(WearableSample.device_id == e4))

            g_times = bigideas.shift(glucose.index, offset)
            n_glucose = await copy_records(s, GlucoseReading, ("device_id", "time", "glucose_mg_dl"), (
                (dexcom, t.to_pydatetime(), int(round(v))) for t, v in zip(g_times, glucose.to_numpy()) if pd.notna(t)))

            counts = {"glucose": n_glucose}
            streams = {
                "heart_rate": lambda: bigideas.read_heart_rate(bigideas.path(raw, p.subject_id, "HR")),
                "ibi_ms": lambda: bigideas.read_ibi(bigideas.path(raw, p.subject_id, "IBI")),
                "skin_temp": lambda: bigideas.read_minute_mean(bigideas.path(raw, p.subject_id, "TEMP"), "temp"),
                "eda": lambda: bigideas.read_minute_mean(bigideas.path(raw, p.subject_id, "EDA"), "eda"),
            }
            for metric, read in streams.items():
                kind = {"heart_rate": "HR", "ibi_ms": "IBI", "skin_temp": "TEMP", "eda": "EDA"}[metric]
                if not bigideas.path(raw, p.subject_id, kind).exists():
                    counts[metric] = 0
                    continue
                series = read()
                times = bigideas.shift(series.index, offset)
                counts[metric] = await copy_records(s, WearableSample, ("device_id", "metric_id", "time", "value"), (
                    (e4, metrics[metric], t.to_pydatetime(), Decimal(str(round(float(v), 3))))
                    for t, v in zip(times, series.to_numpy()) if pd.notna(t)))
        row = {"subject_id": p.subject_id, "sex": p.sex, "hba1c": p.hba1c, "group": m.candidate.group,
               "patient_id": syn.patient_id, "name": f"{syn.given_name} {syn.family_name}",
               "synthea_age": m.candidate.age, "synthea_hba1c": m.candidate.hba1c, "offset_days": offset, **counts}
        report.append(row)
        log(row)

    async with engine().connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        for view in ("ts.glucose_daily", "ts.wearable_daily"):
            await conn.exec_driver_sql(f"CALL refresh_continuous_aggregate('{view}', NULL, NULL)")

    out = cfg.reports_dir / "bigideas_report.csv"
    with out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(dict.fromkeys(k for r in report for k in r)))
        writer.writeheader()
        writer.writerows(report)
    return report
