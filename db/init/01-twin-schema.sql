-- Digital-twin store: patient master, real-participant data, sensor time-series.
-- Conventions
--   * patient_id = Synthea UUID = FHIR Patient.id
--   * every timestamptz in core/ts is in "twin time" (source time + patient.time_offset)
--   * derived values (age, BMI, LDL, TIR, GMI, cohort, sensor window) live in report.* views only

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE SCHEMA IF NOT EXISTS ref;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS ts;
CREATE SCHEMA IF NOT EXISTS report;

-- ── ref: controlled vocabularies ─────────────────────────────────────
CREATE TABLE ref.data_source (
  source_id   smallint PRIMARY KEY,
  code        text UNIQUE NOT NULL,
  name        text NOT NULL,
  url         text,
  license     text
);

CREATE TABLE ref.tag (
  tag_id      smallint PRIMARY KEY,
  code        text UNIQUE NOT NULL,
  display     text NOT NULL,
  description text,
  fhir_system text NOT NULL DEFAULT 'urn:healthcare-digital-twin:tags'
);

CREATE TABLE ref.observation_code (
  code_id     smallint PRIMARY KEY,
  loinc       text UNIQUE NOT NULL,
  display     text NOT NULL,
  ucum_unit   text NOT NULL
);

CREATE TYPE ref.device_kind AS ENUM ('cgm', 'glucometer', 'wearable');

CREATE TABLE ref.device_model (
  model_id         smallint PRIMARY KEY,
  manufacturer     text NOT NULL,
  model_name       text NOT NULL,
  kind             ref.device_kind NOT NULL,
  specimen         text CHECK (specimen IN ('interstitial', 'capillary')),
  nominal_interval interval,
  UNIQUE (manufacturer, model_name)
);

CREATE TYPE ref.sex       AS ENUM ('female', 'male');
CREATE TYPE ref.meal_type AS ENUM ('breakfast', 'lunch', 'dinner', 'snack');

-- ── core: patient master + patient-owned entities ────────────────────
CREATE TABLE core.patient (
  patient_id        uuid PRIMARY KEY,
  mrn               text UNIQUE NOT NULL,
  given_name        text NOT NULL,
  family_name       text NOT NULL,
  name_prefix       text,
  sex               ref.sex NOT NULL,
  birth_date        date NOT NULL,
  race_ethnicity    text,
  address_city      text,
  address_state     text,
  address_postal    text,
  source_id         smallint NOT NULL REFERENCES ref.data_source,
  source_subject_id text NOT NULL,
  time_offset       interval NOT NULL,
  match_age_diff    smallint NOT NULL,
  match_bmi_diff    numeric(4,1) NOT NULL,
  fhir_synced_at    timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_id, source_subject_id)
);
COMMENT ON COLUMN core.patient.time_offset    IS 'source time + time_offset = twin time';
COMMENT ON COLUMN core.patient.match_age_diff IS 'audit of the match decision; EHR values are overwritten afterwards';

CREATE TABLE core.patient_tag (
  patient_id  uuid     NOT NULL REFERENCES core.patient ON DELETE CASCADE,
  tag_id      smallint NOT NULL REFERENCES ref.tag,
  assigned_by text NOT NULL DEFAULT 'pipeline',
  assigned_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (patient_id, tag_id)
);
CREATE INDEX patient_tag_tag_idx ON core.patient_tag (tag_id);

CREATE TABLE core.lab_result (
  patient_id   uuid     NOT NULL REFERENCES core.patient ON DELETE CASCADE,
  code_id      smallint NOT NULL REFERENCES ref.observation_code,
  effective_at timestamptz NOT NULL,
  value        numeric(8,2) NOT NULL,
  PRIMARY KEY (patient_id, code_id, effective_at)
);

CREATE TABLE core.device (
  device_id   serial PRIMARY KEY,
  patient_id  uuid     NOT NULL REFERENCES core.patient ON DELETE CASCADE,
  model_id    smallint NOT NULL REFERENCES ref.device_model,
  UNIQUE (patient_id, model_id)
);

CREATE TABLE core.meal (
  meal_id      bigserial PRIMARY KEY,
  patient_id   uuid NOT NULL REFERENCES core.patient ON DELETE CASCADE,
  started_at   timestamptz NOT NULL,
  meal_type    ref.meal_type NOT NULL,
  energy_kcal  numeric(6,1),
  carbs_g      numeric(5,1),
  protein_g    numeric(5,1),
  fat_g        numeric(5,1),
  fiber_g      numeric(5,1),
  pct_consumed numeric(5,2) CHECK (pct_consumed BETWEEN 0 AND 100),
  UNIQUE (patient_id, started_at)
);

CREATE TABLE core.meal_photo (
  meal_id  bigint NOT NULL REFERENCES core.meal ON DELETE CASCADE,
  taken_at timestamptz NOT NULL,
  path     text NOT NULL,
  PRIMARY KEY (meal_id, taken_at)
);

-- ── ts: raw sensor streams (hypertables) ─────────────────────────────
CREATE TABLE ts.glucose_reading (
  device_id     int NOT NULL REFERENCES core.device ON DELETE CASCADE,
  time          timestamptz NOT NULL,
  glucose_mg_dl smallint NOT NULL CHECK (glucose_mg_dl BETWEEN 20 AND 600),
  PRIMARY KEY (device_id, time)
);

-- Fitbit export differs per participant: METs for most, a 0-3 intensity level
-- (sedentary/light/moderate/vigorous) for others. Both are measured, neither derivable.
CREATE TABLE ts.fitbit_reading (
  device_id      int NOT NULL REFERENCES core.device ON DELETE CASCADE,
  time           timestamptz NOT NULL,
  heart_rate     smallint     CHECK (heart_rate BETWEEN 25 AND 250),
  mets           numeric(4,1) CHECK (mets >= 0),
  activity_level smallint     CHECK (activity_level BETWEEN 0 AND 3),
  active_kcal    numeric(6,3) CHECK (active_kcal >= 0),
  PRIMARY KEY (device_id, time),
  CHECK (num_nonnulls(heart_rate, mets, activity_level, active_kcal) > 0)
);

SELECT create_hypertable('ts.glucose_reading', by_range('time', INTERVAL '7 days'));
SELECT create_hypertable('ts.fitbit_reading',  by_range('time', INTERVAL '7 days'));
ALTER TABLE ts.glucose_reading SET (timescaledb.compress, timescaledb.compress_segmentby = 'device_id');
ALTER TABLE ts.fitbit_reading  SET (timescaledb.compress, timescaledb.compress_segmentby = 'device_id');

-- Daily buckets in the study's local time. Ranges follow the HL7 CGM IG
-- times-in-ranges panel (106793-3): <54, 54-69, 70-180, 181-250, >250 mg/dL.
CREATE MATERIALIZED VIEW ts.glucose_daily WITH (timescaledb.continuous) AS
SELECT device_id,
       time_bucket(INTERVAL '1 day', time, 'America/Chicago') AS day,
       count(*)                                                  AS n,
       avg(glucose_mg_dl)                                        AS mean,
       stddev_samp(glucose_mg_dl)                                AS sd,
       count(*) FILTER (WHERE glucose_mg_dl < 54)                AS n_very_low,
       count(*) FILTER (WHERE glucose_mg_dl BETWEEN 54 AND 69)   AS n_low,
       count(*) FILTER (WHERE glucose_mg_dl BETWEEN 70 AND 180)  AS n_target,
       count(*) FILTER (WHERE glucose_mg_dl BETWEEN 181 AND 250) AS n_high,
       count(*) FILTER (WHERE glucose_mg_dl > 250)               AS n_very_high
FROM ts.glucose_reading
GROUP BY 1, 2
WITH NO DATA;

CREATE MATERIALIZED VIEW ts.fitbit_daily WITH (timescaledb.continuous) AS
SELECT device_id,
       time_bucket(INTERVAL '1 day', time, 'America/Chicago') AS day,
       avg(heart_rate)   AS mean_hr,
       min(heart_rate)   AS min_hr,
       max(heart_rate)   AS max_hr,
       count(heart_rate) AS minutes_worn,
       sum(mets)         AS met_minutes,
       count(*) FILTER (WHERE activity_level >= 2) AS active_minutes,
       sum(active_kcal)  AS active_kcal
FROM ts.fitbit_reading
GROUP BY 1, 2
WITH NO DATA;
