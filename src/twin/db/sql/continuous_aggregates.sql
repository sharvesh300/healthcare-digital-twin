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

CREATE MATERIALIZED VIEW IF NOT EXISTS ts.fitbit_daily WITH (timescaledb.continuous) AS
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
