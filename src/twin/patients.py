"""`match` step: pair participants with Synthea patients and create the patient master records."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta

from twin import cgmacros
from twin.config import Settings
from twin.db import connect, ref_ids
from twin.matching import Match, day_offset, match
from twin.synthea import index_cohort

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


def run_match(cfg: Settings) -> tuple[list[Match], list[cgmacros.Participant]]:
    participants = t2d_participants(cfg)
    cohort = index_cohort(cfg.synthea_fhir_dir)
    matches, unmatched = match(participants, cohort, cfg.match_max_age_diff, cfg.tz)

    with connect() as conn:
        source_id = ref_ids(conn, "ref.data_source", "code", "source_id")[SOURCE_CODE]
        tag_id = ref_ids(conn, "ref.tag", "code", "tag_id")[COMPOSITE_TAG]
        lab_codes = ref_ids(conn, "ref.observation_code", "loinc", "code_id")

        # Drop links that no longer hold (cohort or rule changed); cascades to owned rows.
        keep = [(m.participant.subject_id, m.patient.patient_id) for m in matches]
        stale = conn.execute(
            "SELECT patient_id, source_subject_id FROM core.patient WHERE source_id = %s",
            (source_id,),
        ).fetchall()
        for pid, sid in stale:
            if (sid, str(pid)) not in keep:
                conn.execute("DELETE FROM core.patient WHERE patient_id = %s", (pid,))

        rows = []
        for m in matches:
            p, s = m.participant, m.patient
            day1 = study_day_1(cfg, p.subject_id)
            offset = day_offset(m, day1, cfg.tz)
            conn.execute(
                """
                INSERT INTO core.patient (
                  patient_id, mrn, given_name, family_name, name_prefix, sex, birth_date,
                  race_ethnicity, address_city, address_state, address_postal,
                  source_id, source_subject_id, time_offset, match_age_diff, match_bmi_diff)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,make_interval(days => %s),%s,%s)
                ON CONFLICT (patient_id) DO UPDATE SET
                  mrn = EXCLUDED.mrn, given_name = EXCLUDED.given_name,
                  family_name = EXCLUDED.family_name, name_prefix = EXCLUDED.name_prefix,
                  sex = EXCLUDED.sex, birth_date = EXCLUDED.birth_date,
                  race_ethnicity = EXCLUDED.race_ethnicity, address_city = EXCLUDED.address_city,
                  address_state = EXCLUDED.address_state, address_postal = EXCLUDED.address_postal,
                  source_id = EXCLUDED.source_id, source_subject_id = EXCLUDED.source_subject_id,
                  time_offset = EXCLUDED.time_offset, match_age_diff = EXCLUDED.match_age_diff,
                  match_bmi_diff = EXCLUDED.match_bmi_diff, updated_at = now()
                """,
                (
                    s.patient_id, s.mrn, s.given_name, s.family_name, s.name_prefix, s.sex,
                    s.birth_date, p.race_ethnicity, s.address_city, s.address_state,
                    s.address_postal, source_id, p.subject_id, offset, m.age_diff, m.bmi_diff,
                ),
            )
            conn.execute(
                "INSERT INTO core.patient_tag (patient_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (s.patient_id, tag_id),
            )

            effective = lab_timestamp(p, day1, offset, cfg)
            conn.execute("DELETE FROM core.lab_result WHERE patient_id = %s", (s.patient_id,))
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO core.lab_result (patient_id, code_id, effective_at, value) VALUES (%s,%s,%s,%s)",
                    [(s.patient_id, lab_codes[loinc], effective, value) for loinc, value in p.labs.items()],
                )
            rows.append(
                {
                    "subject_id": p.subject_id, "patient_id": s.patient_id,
                    "name": f"{s.given_name} {s.family_name}", "sex": p.sex,
                    "participant_age": p.age, "age_diff": m.age_diff,
                    "participant_bmi": round(p.bmi, 1), "synthea_bmi": s.latest_bmi,
                    "bmi_diff": m.bmi_diff, "hba1c": p.hba1c,
                    "last_encounter": s.last_encounter_local_date(cfg.tz).isoformat(),
                    "offset_days": offset, "status": "matched",
                }
            )
        conn.commit()

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
