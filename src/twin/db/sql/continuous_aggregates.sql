-- Continuous aggregates over the hypertables (materialised derived data, refreshable).
-- Daily buckets in the study's local time. Glucose ranges follow the HL7 CGM IG
-- times-in-ranges panel (106793-3): <54, 54-69, 70-180, 181-250, >250 mg/dL.

CREATE MATERIALIZED VIEW IF NOT EXISTS ts.glucose_daily WITH (timescaledb.continuous) AS
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

-- Daily totals/means per wearable metric (steps -> total; heart rate -> mean/min/max; ...).
CREATE MATERIALIZED VIEW IF NOT EXISTS ts.wearable_daily WITH (timescaledb.continuous) AS
SELECT device_id,
       metric_id,
       time_bucket(INTERVAL '1 day', time, 'America/Chicago') AS day,
       count(*)   AS n,
       sum(value) AS total,
       avg(value) AS mean,
       min(value) AS min,
       max(value) AS max
FROM ts.wearable_sample
GROUP BY 1, 2, 3
WITH NO DATA;

-- Same ranges over the fused CGM stream (ts.glucose_fused), per patient.
CREATE MATERIALIZED VIEW IF NOT EXISTS ts.glucose_fused_daily WITH (timescaledb.continuous) AS
SELECT patient_id,
       time_bucket(INTERVAL '1 day', time, 'America/Chicago') AS day,
       count(*)                                                  AS n,
       avg(glucose_mg_dl)                                        AS mean,
       stddev_samp(glucose_mg_dl)                                AS sd,
       count(*) FILTER (WHERE glucose_mg_dl < 54)                AS n_very_low,
       count(*) FILTER (WHERE glucose_mg_dl >= 54 AND glucose_mg_dl < 70)   AS n_low,
       count(*) FILTER (WHERE glucose_mg_dl >= 70 AND glucose_mg_dl <= 180) AS n_target,
       count(*) FILTER (WHERE glucose_mg_dl > 180 AND glucose_mg_dl <= 250) AS n_high,
       count(*) FILTER (WHERE glucose_mg_dl > 250)               AS n_very_high
FROM ts.glucose_fused
GROUP BY 1, 2
WITH NO DATA;

-- Real-time aggregation: rows written after the last refresh are included on read,
-- so freshly streamed readings show up in the daily metrics immediately.
ALTER MATERIALIZED VIEW ts.glucose_daily SET (timescaledb.materialized_only = false);
ALTER MATERIALIZED VIEW ts.wearable_daily SET (timescaledb.materialized_only = false);
ALTER MATERIALIZED VIEW ts.glucose_fused_daily SET (timescaledb.materialized_only = false);
