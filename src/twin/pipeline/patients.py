"""`match` step: pair participants with Synthea patients and create the patient master records."""

from __future__ import annotations

import csv
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from twin.config import Settings
from twin.db import lookup, session_scope
from twin.models import DataSource, LabResult, ObservationCode, Patient, PatientTag, Tag
from twin.pipeline.matching import Match, day_offset, match
from twin.sources import cgmacros
from twin.sources.synthea import index_cohort

SOURCE_CODE = "cgmacros"
COMPOSITE_TAG = "composite-patient"


def load_participants(cfg: Settings) -> dict[str, cgmacros.Participant]:
    return cgmacros.read_bio(cfg.cgmacros_dir / "bio.csv")


def t2d_participants(cfg: Settings) -> list[cgmacros.Participant]:
    return [p for p in load_participants(cfg).values() if p.hba1c is not None and p.hba1c >= cfg.t2d_hba1c]


def study_day_1(cfg: Settings, subject_id: str):
    df = cgmacros.read_sensor_csv(cgmacros.sensor_csv_path(cfg.cgmacros_dir, subject_id))
    return cgmacros.parse_streams(df).study_day_1


def lab_timestamp(p: cgmacros.Participant, day1, offset_days: int, cfg: Settings) -> datetime:
    clock = p.lab_time or datetime.min.time()
    return datetime.combine(day1 + timedelta(days=offset_days), clock, tzinfo=cfg.tz)


def _patient_row(m: Match, source_id: int, offset_days: int) -> dict:
    p, s = m.participant, m.patient
    return {
        "patient_id": uuid.UUID(s.patient_id), "mrn": s.mrn, "given_name": s.given_name,
        "family_name": s.family_name, "name_prefix": s.name_prefix, "sex": s.sex, "birth_date": s.birth_date,
        "race_ethnicity": p.race_ethnicity, "address_city": s.address_city, "address_state": s.address_state,
        "address_postal": s.address_postal, "source_id": source_id, "source_subject_id": p.subject_id,
        "time_offset": timedelta(days=offset_days), "match_age_diff": m.age_diff, "match_bmi_diff": m.bmi_diff,
    }


async def run_match(cfg: Settings) -> tuple[list[Match], list[cgmacros.Participant]]:
    participants = t2d_participants(cfg)
    cohort = index_cohort(cfg.synthea_fhir_dir)
    matches, unmatched = match(participants, cohort, cfg.match_max_age_diff, cfg.tz)

    rows = []
    async with session_scope() as s:
        source_id = await s.scalar(select(DataSource.source_id).where(DataSource.code == SOURCE_CODE))
        tag_id = await s.scalar(select(Tag.tag_id).where(Tag.code == COMPOSITE_TAG))
        lab_codes = await lookup(s, ObservationCode.loinc, ObservationCode.code_id)

        # Drop links that no longer hold (cohort or rule changed); the database
        # cascades to everything the patient owns.
        keep = {(m.participant.subject_id, uuid.UUID(m.patient.patient_id)) for m in matches}
        existing = await s.execute(
            select(Patient.patient_id, Patient.source_subject_id).where(Patient.source_id == source_id)
        )
        stale = [pid for pid, sid in existing if (sid, pid) not in keep]
        if stale:
            await s.execute(delete(Patient).where(Patient.patient_id.in_(stale)))

        for m in matches:
            p, syn = m.participant, m.patient
            day1 = study_day_1(cfg, p.subject_id)
            offset = day_offset(m, day1, cfg.tz)
            values = _patient_row(m, source_id, offset)
            stmt = insert(Patient).values(values)
            await s.execute(
                stmt.on_conflict_do_update(
                    index_elements=[Patient.patient_id],
                    set_={**{k: stmt.excluded[k] for k in values if k != "patient_id"}, "updated_at": func.now()},
                )
            )
            await s.execute(
                insert(PatientTag).values(patient_id=values["patient_id"], tag_id=tag_id).on_conflict_do_nothing()
            )

            effective = lab_timestamp(p, day1, offset, cfg)
            await s.execute(delete(LabResult).where(LabResult.patient_id == values["patient_id"]))
            await s.execute(
                insert(LabResult),
                [{"patient_id": values["patient_id"], "code_id": lab_codes[loinc], "effective_at": effective, "value": v}
                 for loinc, v in p.labs.items()],
            )
            rows.append({
                "subject_id": p.subject_id, "patient_id": syn.patient_id,
                "name": f"{syn.given_name} {syn.family_name}", "sex": p.sex,
                "participant_age": p.age, "age_diff": m.age_diff,
                "participant_bmi": round(p.bmi, 1), "synthea_bmi": syn.latest_bmi,
                "bmi_diff": m.bmi_diff, "hba1c": p.hba1c,
                "last_encounter": syn.last_encounter_local_date(cfg.tz).isoformat(),
                "offset_days": offset, "status": "matched",
            })

    for p in unmatched:
        rows.append({"subject_id": p.subject_id, "sex": p.sex, "participant_age": p.age,
                     "hba1c": p.hba1c, "status": "unmatched"})
    out = cfg.reports_dir / "match_report.csv"
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return matches, unmatched
