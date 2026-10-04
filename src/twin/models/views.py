"""Read-only table definitions for the views and continuous aggregates.

They live in their own MetaData so `create_all` never tries to create them; the
DDL is in twin/db/sql/*.sql and is applied by twin.db.schema.init_db. Numeric columns
come back as float (these feed JSON/FHIR output, not arithmetic).
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID

views = MetaData()
TS = TIMESTAMP(timezone=True)


def _num(name: str) -> Column:
    return Column(name, Numeric(asdecimal=False))


patient_summary = Table(
    "patient_summary", views,
    Column("patient_id", UUID, primary_key=True), Column("display_name", Text),
    Column("mrn", Text), Column("name_prefix", Text), Column("given_name", Text), Column("family_name", Text),
    Column("sex", Text), Column("birth_date", Date), Column("birth_date_imputed", Boolean), Column("age", Integer),
    Column("race_ethnicity", Text), Column("address_city", Text), Column("address_state", Text),
    Column("source", Text), Column("source_subject_id", Text), Column("tags", ARRAY(Text)),
    schema="report",
)

observation_latest = Table(
    "observation_latest", views,
    Column("patient_id", UUID), Column("analyte", Text), Column("loinc", Text), Column("category", Text),
    Column("effective_at", TS), _num("value_num"), Column("value_display", Text), Column("ucum_unit", Text),
    Column("source", Text), Column("is_synthetic", Boolean),
    schema="report",
)

patient_baseline = Table(
    "patient_baseline", views,
    Column("patient_id", UUID, primary_key=True), Column("effective_at", TS),
    *(_num(c) for c in ("hba1c", "fasting_glucose", "glucose_2h_postprandial", "insulin", "c_peptide",
                        "total_cholesterol", "hdl", "triglycerides", "weight_kg", "height_cm", "sbp", "dbp",
                        "creatinine", "uacr", "alt", "ast", "uric_acid")),
    Column("smoking_status", Text),
    _num("bmi"), Column("bmi_is_synthetic", Boolean), *(_num(c) for c in ("non_hdl", "tc_hdl_ratio", "vldl", "ldl")),
    Column("ldl_is_synthetic", Boolean), _num("homa_ir"), Column("homa_ir_is_synthetic", Boolean),
    _num("egfr"), Column("egfr_is_synthetic", Boolean),
    Column("cohort", Text), Column("synthetic_analytes", ARRAY(Text)),
    schema="report",
)

patient_conditions = Table(
    "patient_conditions", views,
    Column("patient_id", UUID), Column("condition_group", Text), Column("first_onset", TS),
    Column("active", Boolean), Column("conditions", ARRAY(Text)), Column("all_synthetic", Boolean),
    schema="report",
)

medication_regimen = Table(
    "medication_regimen", views,
    Column("patient_id", UUID), Column("regimen_id", BigInteger), Column("rxcui", Integer),
    Column("medication", Text), Column("drug_class", Text), Column("glucose_lowering", Boolean),
    Column("started_at", TS), Column("ended_at", TS), Column("active", Boolean),
    _num("dose_value"), Column("dose_unit", Text), _num("times_per_day"), Column("as_needed", Boolean),
    Column("source", Text), Column("is_synthetic", Boolean),
    schema="report",
)

activity_daily = Table(
    "activity_daily", views,
    Column("patient_id", UUID), Column("day", TS),
    *(_num(c) for c in ("steps", "hr_mean", "hr_min", "hr_max")), Column("hr_minutes", BigInteger),
    _num("wear_minutes"),
    *(_num(c) for c in ("met_minutes", "active_kcal", "activity_level_mean", "spo2_mean", "respiration_mean",
                        "stress_mean", "skin_temp_mean", "eda_mean")),
    Column("synthetic_metrics", ARRAY(Text)),
    schema="report",
)

sleep_nightly = Table(
    "sleep_nightly", views,
    Column("patient_id", UUID), Column("night", Date), Column("bedtime", TS), Column("wake_time", TS),
    *(_num(c) for c in ("time_in_bed_min", "asleep_min", "light_min", "deep_min", "rem_min", "awake_min",
                        "efficiency_pct")),
    Column("is_synthetic", Boolean),
    schema="report",
)

spo2_nightly = Table(
    "spo2_nightly", views,
    Column("patient_id", UUID), Column("night", Date), Column("sleep_minutes", BigInteger),
    _num("spo2_mean"), _num("spo2_min"), _num("t90_pct"), _num("odi_per_hour"), Column("is_synthetic", Boolean),
    schema="report",
)

hrv_nightly = Table(
    "hrv_nightly", views,
    Column("patient_id", UUID), Column("night", Date), _num("rmssd_ms"), Column("beats", BigInteger),
    Column("is_synthetic", Boolean),
    schema="report",
)

cgm_daily = Table(  # fused CGM stream
    "cgm_daily", views,
    Column("patient_id", UUID), Column("day", TS), Column("n", BigInteger),
    *(_num(c) for c in ("coverage_pct", "mean_mg_dl", "cv_pct", "gmi", "pct_very_low", "pct_low", "pct_target",
                        "pct_high", "pct_very_high")),
    schema="report",
)

cgm_window = Table(  # fused CGM stream
    "cgm_window", views,
    Column("patient_id", UUID), Column("glucose_source", Text), Column("method_version", Text),
    Column("period_start", TS), Column("period_end", TS), Column("n", BigInteger),
    _num("mean_mg_dl"), _num("gmi"),
    schema="report",
)

consistency = Table(
    "consistency", views,
    Column("patient_id", UUID), _num("hba1c"), _num("gmi"), _num("mean_mg_dl"), Column("glucose_source", Text),
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
