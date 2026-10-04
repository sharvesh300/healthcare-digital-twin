"""SQL views on fixture rows, via async SQLAlchemy. Each test runs inside a
transaction that is rolled back; skipped when the twin database is unreachable."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from twin.db import copy_records, dispose_engine, engine
from twin.models import (
    CgmCalibration,
    DeviceModel,
    GlucoseFused,
    LagKind,
    Observation,
    ObservationCode,
    Patient,
)
from twin.models import views as v

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


REAL, SYNTHETIC = 1, 2  # ref.data_source: cgmacros, synthea


async def _patient(s: AsyncSession, labs: dict[str, float], sex: str = "female",
                   birth_date: date = date(1970, 1, 1)) -> uuid.UUID:
    pid = uuid.uuid4()
    s.add(Patient(patient_id=pid, sex=sex, birth_date=birth_date, source_id=REAL, source_subject_id=f"test-{pid}"))
    await s.flush()
    await _observe(s, pid, labs, REAL)
    return pid


async def _observe(s: AsyncSession, pid, values: dict[str, float], source_id: int,
                   at: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc)) -> None:
    codes = dict((await s.execute(select(ObservationCode.loinc, ObservationCode.code_id))).all())
    s.add_all(Observation(patient_id=pid, code_id=codes[loinc], effective_at=at, value_num=value, source_id=source_id)
              for loinc, value in values.items())
    await s.flush()


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


async def test_real_values_win_over_newer_synthetic_and_flags_follow(session):
    pid = await _patient(session, {"29463-7": 80, "8302-2": 170, "2093-3": 200, "2085-9": 50, "2571-8": 150})
    # Newer synthetic values (e.g. Synthea history of a composite twin) must not override real ones,
    # and a synthetic-only measured LDL must not replace a Friedewald LDL from real inputs.
    await _observe(session, pid, {"29463-7": 95, "18262-6": 160, "2160-0": 1.1}, SYNTHETIC,
                   at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    b = v.patient_baseline.c
    row = (await session.execute(
        select(b.weight_kg, b.bmi, b.bmi_is_synthetic, b.ldl, b.ldl_is_synthetic, b.egfr_is_synthetic,
               b.synthetic_analytes).where(b.patient_id == pid))).mappings().one()
    assert row["weight_kg"] == 80 and row["bmi"] == 27.7 and row["bmi_is_synthetic"] is False
    assert row["ldl"] == 120 and row["ldl_is_synthetic"] is False
    assert row["egfr_is_synthetic"] is True and set(row["synthetic_analytes"]) == {"creatinine", "ldl"}


async def test_egfr_ckd_epi_2021(session):
    # Creatinine 1.0 mg/dL, female, 50 years at the draw:
    # 142 x (1.0/0.7)^-1.200 x 0.9938^50 x 1.012 = 142 x 0.6518 x 0.7328 x 1.012 = 68.6 -> 69.
    pid = await _patient(session, {"2160-0": 1.0}, sex="female", birth_date=date(1975, 12, 31))
    b = v.patient_baseline.c
    assert (await session.scalar(select(b.egfr).where(b.patient_id == pid))) == 69


async def test_ldl_undefined_when_triglycerides_above_400(session):
    pid = await _patient(session, {"2093-3": 260, "2085-9": 40, "2571-8": 450, "4548-4": 6.0})
    row = await _baseline(session, pid)
    assert row["ldl"] is None and row["vldl"] is None
    assert row["cohort"] == "prediabetes"


async def _fused_day(session, pid, value: float, n: int = 288) -> None:
    """A calibration row plus one day of fused readings at a constant value."""
    models = dict((await session.execute(select(DeviceModel.model_name, DeviceModel.model_id))).all())
    session.add(CgmCalibration(
        patient_id=pid, method_version="test", reference_model_id=models["G6 Pro"],
        secondary_model_id=models["FreeStyle Libre Pro"], lag_minutes=0, lag_kind=LagKind.sensor_lag,
        reference_shift_minutes=0, secondary_shift_minutes=0, secondary_intercept=0, secondary_slope=1,
        overlap_points=0, disagreement_sd=0, warmup_variance_factor=1,
    ))
    await session.flush()
    # After the aggregates' materialisation watermark, where real-time aggregation applies
    # (as for freshly streamed data). 06:00 UTC = local midnight in America/Chicago.
    t0 = datetime(2030, 1, 2, 6, tzinfo=timezone.utc)
    await copy_records(session, GlucoseFused, ("patient_id", "time", "glucose_mg_dl", "source", "censored"),
                       [(pid, t0 + timedelta(minutes=5 * i), Decimal(str(value)), "both", False) for i in range(n)])


@pytest.mark.parametrize("hba1c,status", [(7.3, "ok"), (7.9, "warn"), (8.5, "inconsistent")])
async def test_gmi_consistency_thresholds(session, hba1c, status):
    pid = await _patient(session, {"4548-4": hba1c})
    await _fused_day(session, pid, 167)  # GMI = 3.31 + 0.02392 * 167 = 7.30
    c = v.consistency.c
    gmi, got, source = (await session.execute(
        select(c.gmi, c.status, c.glucose_source).where(c.patient_id == pid))).one()
    assert gmi == 7.30 and got == status
    assert source == "Dexcom G6 Pro + Abbott FreeStyle Libre Pro"


async def test_cgm_daily_ranges_and_coverage_from_fused_stream(session):
    pid = await _patient(session, {"4548-4": 7.0})
    await _fused_day(session, pid, 69.9, n=216)  # 75 % of the day, all in the 54-69 "low" range
    c = v.cgm_daily.c
    row = (await session.execute(
        select(c.coverage_pct, c.pct_low, c.pct_target, c.mean_mg_dl).where(c.patient_id == pid))).one()
    assert row == (75.0, 100.0, 0.0, 69.9)
