"""SQL views on fixture rows. Runs against the twin database inside a rolled-back
transaction; skipped when the database is not reachable."""

import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from twin.config import settings


@pytest.fixture
def conn():
    try:
        c = psycopg.connect(settings().database_url, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("twin database not reachable")
    yield c
    c.rollback()
    c.close()


def _patient(conn, labs: dict[str, float]) -> uuid.UUID:
    pid = uuid.uuid4()
    conn.execute(
        """INSERT INTO core.patient (patient_id, mrn, given_name, family_name, sex, birth_date, source_id,
                                     source_subject_id, time_offset, match_age_diff, match_bmi_diff)
           VALUES (%s, %s, 'T', 'P', 'female', '1970-01-01', 1, %s, '0 days', 0, 0)""",
        (pid, str(pid), f"test-{pid}"),
    )
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for loinc, value in labs.items():
        conn.execute(
            """INSERT INTO core.lab_result (patient_id, code_id, effective_at, value)
               SELECT %s, code_id, %s, %s FROM ref.observation_code WHERE loinc = %s""",
            (pid, at, value, loinc),
        )
    return pid


def baseline(conn, pid):
    cur = conn.execute("SELECT bmi, ldl, vldl, non_hdl, cohort FROM report.patient_baseline WHERE patient_id = %s", (pid,))
    return dict(zip([c.name for c in cur.description], cur.fetchone()))


def test_bmi_friedewald_and_cohort(conn):
    pid = _patient(conn, {"29463-7": 80, "8302-2": 170, "2093-3": 200, "2085-9": 50, "2571-8": 150, "4548-4": 7.1})
    row = baseline(conn, pid)
    assert float(row["bmi"]) == 27.7
    assert float(row["ldl"]) == 120  # 200 - 50 - 150/5
    assert float(row["vldl"]) == 30 and float(row["non_hdl"]) == 150
    assert row["cohort"] == "t2d"


def test_ldl_undefined_when_triglycerides_above_400(conn):
    pid = _patient(conn, {"2093-3": 260, "2085-9": 40, "2571-8": 450, "4548-4": 6.0})
    row = baseline(conn, pid)
    assert row["ldl"] is None and row["vldl"] is None
    assert row["cohort"] == "prediabetes"


@pytest.mark.parametrize("hba1c,status", [(7.3, "ok"), (7.9, "warn"), (8.5, "inconsistent")])
def test_gmi_consistency_thresholds(conn, hba1c, status):
    pid = _patient(conn, {"4548-4": hba1c})
    device = conn.execute(
        """INSERT INTO core.device (patient_id, model_id)
           SELECT %s, model_id FROM ref.device_model WHERE model_name = 'G6 Pro' RETURNING device_id""",
        (pid,),
    ).fetchone()[0]
    t0 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    with conn.cursor().copy("COPY ts.glucose_reading (device_id, time, glucose_mg_dl) FROM STDIN") as cp:
        for i in range(288):
            cp.write_row((device, t0 + timedelta(minutes=5 * i), 167))  # GMI = 3.31 + 0.02392*167 = 7.30
    gmi, got = conn.execute("SELECT gmi, status FROM report.consistency WHERE patient_id = %s", (pid,)).fetchone()
    assert float(gmi) == 7.30 and got == status
