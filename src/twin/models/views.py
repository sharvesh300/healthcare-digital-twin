"""Read-only table definitions for the views and continuous aggregates.

They live in their own MetaData so `create_all` never tries to create them; the
DDL is in twin/db/sql/*.sql and is applied by twin.db.schema.init_db. Numeric columns
come back as float (these feed JSON/FHIR output, not arithmetic).
"""

from sqlalchemy import BigInteger, Column, Date, Integer, MetaData, Numeric, Table, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID

views = MetaData()
TS = TIMESTAMP(timezone=True)


def _num(name: str) -> Column:
    return Column(name, Numeric(asdecimal=False))


patient_summary = Table(
    "patient_summary", views,
    Column("patient_id", UUID, primary_key=True),
    Column("mrn", Text), Column("name_prefix", Text), Column("given_name", Text), Column("family_name", Text),
    Column("sex", Text), Column("birth_date", Date), Column("age", Integer), Column("race_ethnicity", Text),
    Column("address_city", Text), Column("address_state", Text),
    Column("source", Text), Column("source_subject_id", Text), Column("tags", ARRAY(Text)),
    schema="report",
)

patient_baseline = Table(
    "patient_baseline", views,
    Column("patient_id", UUID, primary_key=True), Column("effective_at", TS),
    *(_num(c) for c in ("hba1c", "fasting_glucose", "insulin", "total_cholesterol", "hdl", "triglycerides",
                        "weight_kg", "height_cm", "bmi", "non_hdl", "tc_hdl_ratio", "vldl", "ldl")),
    Column("cohort", Text),
    schema="report",
)

cgm_daily = Table(
    "cgm_daily", views,
    Column("patient_id", UUID), Column("day", TS), Column("device_id", Integer), Column("device_model", Text),
    Column("n", BigInteger),
    *(_num(c) for c in ("coverage_pct", "mean_mg_dl", "cv_pct", "gmi", "pct_very_low", "pct_low", "pct_target",
                        "pct_high", "pct_very_high")),
    schema="report",
)

cgm_window = Table(
    "cgm_window", views,
    Column("patient_id", UUID), Column("device_id", Integer), Column("device_model", Text),
    Column("period_start", TS), Column("period_end", TS), Column("n", BigInteger),
    _num("mean_mg_dl"), _num("gmi"),
    schema="report",
)

consistency = Table(
    "consistency", views,
    Column("patient_id", UUID), _num("hba1c"), _num("gmi"), _num("mean_mg_dl"), Column("device_model", Text),
    _num("abs_diff"), Column("status", Text),
    schema="report",
)

sensor_window = Table(
    "sensor_window", views,
    Column("patient_id", UUID), Column("window_start", TS), Column("window_end", TS),
    schema="report",
)

replay_stream = Table(
    "replay_stream", views,
    Column("patient_id", UUID), Column("time", TS), Column("kind", Text), Column("source", Text),
    Column("payload", JSONB),
    schema="report",
)

fitbit_daily = Table(
    "fitbit_daily", views,
    Column("device_id", Integer), Column("day", TS),
    *(_num(c) for c in ("mean_hr", "min_hr", "max_hr")),
    Column("minutes_worn", BigInteger), _num("met_minutes"), Column("active_minutes", BigInteger),
    _num("active_kcal"),
    schema="ts",
)
