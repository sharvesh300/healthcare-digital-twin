"""SQL views on fixture rows, via async SQLAlchemy. Each test runs inside a
transaction that is rolled back; skipped when the twin database is unreachable."""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from twin.models import views as v
from twin.db import copy_records, dispose_engine, engine
from twin.models import Device, DeviceModel, GlucoseReading, LabResult, ObservationCode, Patient

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session():
    try:
        conn = await engine().connect()
    except (OSError, SQLAlchemyError):
        await dispose_engine()
        pytest.skip("twin database not reachable")
    trans = await conn.begin()
    s = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield s
    finally:
        await s.close()
        await trans.rollback()
        await conn.close()
        await dispose_engine()


async def _patient(s: AsyncSession, labs: dict[str, float]) -> uuid.UUID:
    pid = uuid.uuid4()
    s.add(Patient(patient_id=pid, mrn=str(pid), given_name="T", family_name="P", sex="female",
                  birth_date=date(1970, 1, 1), source_id=1, source_subject_id=f"test-{pid}",
                  time_offset=timedelta(0), match_age_diff=0, match_bmi_diff=0))
    await s.flush()
    codes = dict((await s.execute(select(ObservationCode.loinc, ObservationCode.code_id))).all())
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    s.add_all(LabResult(patient_id=pid, code_id=codes[loinc], effective_at=at, value=value) for loinc, value in labs.items())
    await s.flush()
    return pid


async def _baseline(s: AsyncSession, pid) -> dict:
    b = v.patient_baseline.c
    row = await s.execute(select(b.bmi, b.ldl, b.vldl, b.non_hdl, b.cohort).where(b.patient_id == pid))
    return dict(row.mappings().one())


async def test_bmi_friedewald_and_cohort(session):
    pid = await _patient(session, {"29463-7": 80, "8302-2": 170, "2093-3": 200, "2085-9": 50, "2571-8": 150,
                                   "4548-4": 7.1})
    row = await _baseline(session, pid)
    assert row["bmi"] == 27.7
    assert row["ldl"] == 120  # 200 - 50 - 150/5
    assert row["vldl"] == 30 and row["non_hdl"] == 150
    assert row["cohort"] == "t2d"


async def test_ldl_undefined_when_triglycerides_above_400(session):
    pid = await _patient(session, {"2093-3": 260, "2085-9": 40, "2571-8": 450, "4548-4": 6.0})
    row = await _baseline(session, pid)
    assert row["ldl"] is None and row["vldl"] is None
    assert row["cohort"] == "prediabetes"


@pytest.mark.parametrize("hba1c,status", [(7.3, "ok"), (7.9, "warn"), (8.5, "inconsistent")])
async def test_gmi_consistency_thresholds(session, hba1c, status):
    pid = await _patient(session, {"4548-4": hba1c})
    model_id = await session.scalar(select(DeviceModel.model_id).where(DeviceModel.model_name == "G6 Pro"))
    device = Device(patient_id=pid, model_id=model_id)
    session.add(device)
    await session.flush()
    t0 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    # GMI = 3.31 + 0.02392 * 167 = 7.30
    await copy_records(session, GlucoseReading, ("device_id", "time", "glucose_mg_dl"),
                       [(device.device_id, t0 + timedelta(minutes=5 * i), 167) for i in range(288)])
    c = v.consistency.c
    gmi, got = (await session.execute(select(c.gmi, c.status).where(c.patient_id == pid))).one()
    assert gmi == 7.30 and got == status
