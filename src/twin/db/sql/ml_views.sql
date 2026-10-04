-- ML feature store. Views only (recreated on every `twin init-db`); exported to Parquet
-- by `twin export-features`. Rows from synthetic sources are flagged, never hidden.

-- Deterministic patient-level split (70 / 15 / 15) from a hash of the patient id, so a
-- patient never appears in more than one split and the split is stable across rebuilds.
CREATE VIEW ml.patient_split AS
SELECT patient_id,
       CASE WHEN h < 70 THEN 'train' WHEN h < 85 THEN 'validation' ELSE 'test' END AS split
FROM (SELECT patient_id, (('x' || substr(md5(patient_id::text), 1, 8))::bit(32)::bigint % 100) AS h
      FROM core.patient) x;

-- One row per patient: demographics, baseline clinical values, conditions, current
-- medication classes, data availability, provenance and split.
CREATE VIEW ml.patient_static AS
WITH cond AS (
  SELECT patient_id,
         bool_or(condition_group = 'hypertension')   AS has_hypertension,
         bool_or(condition_group = 'dyslipidemia')   AS has_dyslipidemia,
         bool_or(condition_group = 'ckd')            AS has_ckd,
         bool_or(condition_group = 'retinopathy')    AS has_retinopathy,
         bool_or(condition_group = 'neuropathy')     AS has_neuropathy,
         bool_or(condition_group = 'cardiovascular') AS has_cardiovascular,
         bool_or(condition_group = 'sleep_apnea')    AS has_sleep_apnea,
         bool_or(condition_group = 'copd')           AS has_copd,
         min(first_onset) FILTER (WHERE condition_group = 't2d') AS t2d_onset,
         bool_or(all_synthetic)                      AS conditions_synthetic
  FROM report.patient_conditions GROUP BY patient_id
), meds AS (
  SELECT patient_id,
         bool_or(drug_class = 'biguanide')                         AS on_metformin,
         bool_or(drug_class = 'sulfonylurea')                      AS on_sulfonylurea,
         bool_or(drug_class = 'dpp4_inhibitor')                    AS on_dpp4i,
         bool_or(drug_class = 'sglt2_inhibitor')                   AS on_sglt2i,
         bool_or(drug_class = 'glp1_ra')                           AS on_glp1ra,
         bool_or(drug_class = 'thiazolidinedione')                 AS on_tzd,
         bool_or(drug_class LIKE 'insulin%')                       AS on_insulin,
         bool_or(drug_class = 'statin')                            AS on_statin,
         bool_or(drug_class IN ('ace_inhibitor', 'arb'))           AS on_acei_arb,
         count(DISTINCT drug_class) FILTER (WHERE glucose_lowering) AS n_glucose_lowering_classes,
         bool_or(is_synthetic)                                     AS medications_synthetic
  FROM report.medication_regimen WHERE active GROUP BY patient_id
), night AS (
  SELECT patient_id, count(*) AS sleep_nights, bool_and(is_synthetic) AS sleep_synthetic
  FROM report.sleep_nightly GROUP BY patient_id
), hrv AS (
  SELECT patient_id, count(*) FILTER (WHERE NOT is_synthetic) AS real_hrv_nights FROM report.hrv_nightly GROUP BY patient_id
), cgm AS (
  SELECT patient_id, count(*) AS cgm_days FROM report.cgm_daily WHERE coverage_pct >= 70 GROUP BY patient_id
), act AS (
  SELECT patient_id,
         count(*) FILTER (WHERE wear_minutes >= 600)                        AS valid_step_days,
         round(avg(steps) FILTER (WHERE wear_minutes >= 600))               AS steps_per_valid_day,
         count(*) FILTER (WHERE hr_minutes >= 1008)                         AS hr_days
  FROM report.activity_daily GROUP BY patient_id
)
SELECT s.patient_id,
       s.source                                           AS cohort,
       sp.split,
       s.sex,
       s.age,
       s.race_ethnicity,
       NOT ('undiagnosed-diabetes' = ANY(s.tags))         AS diabetes_diagnosed,
       round(extract(epoch FROM (b.effective_at - c.t2d_onset)) / 31557600, 1) AS diabetes_duration_years,
       b.hba1c, b.fasting_glucose, b.insulin, b.c_peptide, b.homa_ir, b.homa_ir_is_synthetic,
       b.weight_kg, b.height_cm, b.bmi, b.bmi_is_synthetic, b.sbp, b.dbp,
       b.total_cholesterol, b.hdl, b.ldl, b.ldl_is_synthetic, b.triglycerides,
       b.creatinine, b.egfr, b.egfr_is_synthetic, b.uacr, b.alt, b.ast, b.uric_acid, b.smoking_status,
       coalesce(c.has_hypertension, false)   AS has_hypertension,
       coalesce(c.has_dyslipidemia, false)   AS has_dyslipidemia,
       coalesce(c.has_ckd, false)            AS has_ckd,
       coalesce(c.has_retinopathy, false)    AS has_retinopathy,
       coalesce(c.has_neuropathy, false)     AS has_neuropathy,
       coalesce(c.has_cardiovascular, false) AS has_cardiovascular,
       coalesce(c.has_sleep_apnea, false)    AS has_sleep_apnea,
       coalesce(c.has_copd, false)           AS has_copd,
       coalesce(m.on_metformin, false) AS on_metformin, coalesce(m.on_sulfonylurea, false) AS on_sulfonylurea,
       coalesce(m.on_dpp4i, false) AS on_dpp4i, coalesce(m.on_sglt2i, false) AS on_sglt2i,
       coalesce(m.on_glp1ra, false) AS on_glp1ra, coalesce(m.on_tzd, false) AS on_tzd,
       coalesce(m.on_insulin, false) AS on_insulin, coalesce(m.on_statin, false) AS on_statin,
       coalesce(m.on_acei_arb, false) AS on_acei_arb,
       coalesce(m.n_glucose_lowering_classes, 0) AS n_glucose_lowering_classes,
       coalesce(cg.cgm_days, 0)          AS cgm_days,
       coalesce(a.valid_step_days, 0)    AS valid_step_days,
       a.steps_per_valid_day,
       coalesce(a.hr_days, 0)            AS hr_days,
       coalesce(n.sleep_nights, 0)       AS sleep_nights,
       n.sleep_synthetic,
       coalesce(h.real_hrv_nights, 0)    AS real_hrv_nights,
       coalesce(c.conditions_synthetic, false) OR coalesce(m.medications_synthetic, false)
         OR cardinality(b.synthetic_analytes) > 0      AS has_synthetic_values
FROM report.patient_summary s
JOIN ml.patient_split sp USING (patient_id)
LEFT JOIN report.patient_baseline b USING (patient_id)
LEFT JOIN cond c USING (patient_id)
LEFT JOIN meds m USING (patient_id)
LEFT JOIN cgm cg USING (patient_id)
LEFT JOIN act a USING (patient_id)
LEFT JOIN night n USING (patient_id)
LEFT JOIN hrv h USING (patient_id);

-- One row per patient and local day with any CGM or wearable data.
CREATE VIEW ml.patient_day AS
WITH hrv AS (  -- one value per night, computed once; real HRV preferred over synthetic
  SELECT DISTINCT ON (patient_id, night) patient_id, night, rmssd_ms, is_synthetic
  FROM report.hrv_nightly ORDER BY patient_id, night, is_synthetic
), days AS (
  SELECT patient_id, day FROM report.cgm_daily
  UNION
  SELECT patient_id, day FROM report.activity_daily
)
SELECT d.patient_id,
       d.day,
       sp.split,
       c.coverage_pct       AS cgm_coverage_pct,
       c.mean_mg_dl         AS glucose_mean,
       c.cv_pct             AS glucose_cv_pct,
       c.gmi,
       c.pct_very_low, c.pct_low, c.pct_target, c.pct_high, c.pct_very_high,
       a.steps, a.wear_minutes, a.hr_mean, a.hr_min, a.hr_max, a.hr_minutes,
       a.met_minutes, a.active_kcal, a.activity_level_mean,
       a.stress_mean, a.respiration_mean, a.spo2_mean AS spo2_day_mean, a.skin_temp_mean, a.eda_mean,
       sl.asleep_min AS sleep_prev_night_min, sl.deep_min AS deep_prev_night_min, sl.rem_min AS rem_prev_night_min,
       sl.efficiency_pct AS sleep_efficiency_pct,
       so.spo2_mean AS spo2_sleep_mean, so.spo2_min AS spo2_sleep_min, so.t90_pct, so.odi_per_hour,
       hv.rmssd_ms AS hrv_rmssd_prev_night, hv.is_synthetic AS hrv_is_synthetic,
       a.synthetic_metrics || CASE WHEN sl.is_synthetic THEN ARRAY['sleep'] ELSE '{}' END AS synthetic_channels,
       (SELECT count(DISTINCT r.drug_class) FROM report.medication_regimen r
        WHERE r.patient_id = d.patient_id AND r.glucose_lowering
          AND r.started_at < d.day + INTERVAL '1 day'
          AND (r.ended_at IS NULL OR r.ended_at >= d.day))                          AS n_glucose_lowering_classes,
       (SELECT sum(md.dose_value) FROM core.medication_dose md
        JOIN ref.medication m USING (medication_id) JOIN ref.drug_class dc ON dc.class_id = m.drug_class_id
        WHERE md.patient_id = d.patient_id AND dc.code LIKE 'insulin%' AND md.dose_unit IN ('U', '[iU]')
          AND md.time >= d.day AND md.time < d.day + INTERVAL '1 day')                AS insulin_units
FROM days d
JOIN ml.patient_split sp USING (patient_id)
LEFT JOIN report.cgm_daily c USING (patient_id, day)
LEFT JOIN report.activity_daily a USING (patient_id, day)
LEFT JOIN report.sleep_nightly sl ON sl.patient_id = d.patient_id
     AND sl.night = (d.day AT TIME ZONE 'America/Chicago')::date - 1
LEFT JOIN report.spo2_nightly so ON so.patient_id = d.patient_id AND so.night = sl.night
LEFT JOIN hrv hv ON hv.patient_id = d.patient_id
     AND hv.night = (d.day AT TIME ZONE 'America/Chicago')::date - 1;

-- 5-minute multichannel series for patients with fused CGM: the input to forecasting.
-- Wearable channels are aggregated into the same 5-minute buckets; doses are summed
-- per bucket (fast/premixed vs long/intermediate insulin, oral glucose-lowering doses).
CREATE VIEW ml.series_5min AS
WITH wear AS (
  SELECT d.patient_id,
         time_bucket(INTERVAL '5 minutes', w.time)                   AS time,
         sum(w.value) FILTER (WHERE m.code = 'steps')                AS steps,
         avg(w.value) FILTER (WHERE m.code = 'heart_rate')           AS heart_rate,
         sum(w.value) FILTER (WHERE m.code = 'mets')                 AS met_minutes,
         avg(w.value) FILTER (WHERE m.code = 'activity_level')       AS activity_level,
         avg(w.value) FILTER (WHERE m.code = 'spo2')                 AS spo2,
         avg(w.value) FILTER (WHERE m.code = 'respiration_rate')     AS respiration_rate,
         avg(w.value) FILTER (WHERE m.code = 'stress')               AS stress,
         avg(w.value) FILTER (WHERE m.code = 'skin_temp')            AS skin_temp,
         avg(w.value) FILTER (WHERE m.code = 'eda')                  AS eda,
         coalesce(array_agg(DISTINCT m.code) FILTER (WHERE dm.is_synthetic), '{}') AS synthetic_channels
  FROM ts.wearable_sample w
  JOIN core.device d USING (device_id)
  JOIN ref.device_model dm USING (model_id)
  JOIN ref.wearable_metric m USING (metric_id)
  WHERE m.code NOT IN ('wear_minutes', 'ibi_ms', 'hrv_rmssd')
  GROUP BY 1, 2
), hrv AS (  -- real RMSSD per 5 minutes from inter-beat intervals (artefacts excluded)
  SELECT patient_id, time_bucket(INTERVAL '5 minutes', time) AS time, sqrt(avg(diff * diff)) AS rmssd_5min
  FROM (SELECT d.patient_id, w.time,
               w.value - lag(w.value) OVER (PARTITION BY w.device_id ORDER BY w.time) AS diff,
               w.time - lag(w.time) OVER (PARTITION BY w.device_id ORDER BY w.time)   AS gap
        FROM ts.wearable_sample w
        JOIN ref.wearable_metric m ON m.metric_id = w.metric_id AND m.code = 'ibi_ms'
        JOIN core.device d ON d.device_id = w.device_id) b
  WHERE gap < INTERVAL '2.5 seconds' AND abs(diff) < 200
  GROUP BY 1, 2
  HAVING count(*) >= 30
), dose AS (
  SELECT md.patient_id,
         time_bucket(INTERVAL '5 minutes', md.time)                                         AS time,
         sum(md.dose_value) FILTER (WHERE dc.code IN ('insulin_rapid', 'insulin_premixed')) AS insulin_fast_units,
         sum(md.dose_value) FILTER (WHERE dc.code IN ('insulin_long', 'insulin_intermediate')) AS insulin_basal_units,
         count(*) FILTER (WHERE dc.glucose_lowering AND dc.code NOT LIKE 'insulin%')        AS oral_doses
  FROM core.medication_dose md
  JOIN ref.medication m USING (medication_id)
  LEFT JOIN ref.drug_class dc ON dc.class_id = m.drug_class_id
  GROUP BY 1, 2
)
SELECT g.patient_id,
       g.time,
       g.glucose_mg_dl,
       g.source::text  AS glucose_sources,
       g.censored      AS glucose_censored,
       w.steps, w.heart_rate, w.met_minutes, w.activity_level,
       w.spo2, w.respiration_rate, w.stress, w.skin_temp, w.eda,
       hv.rmssd_5min,
       (SELECT ss.stage::text FROM ts.sleep_segment ss JOIN core.device sd ON sd.device_id = ss.device_id
        WHERE sd.patient_id = g.patient_id AND g.time >= ss.start_time AND g.time < ss.end_time LIMIT 1) AS sleep_stage,
       coalesce(w.synthetic_channels, '{}')
         || CASE WHEN EXISTS (SELECT 1 FROM ts.sleep_segment ss JOIN core.device sd ON sd.device_id = ss.device_id
                              JOIN ref.device_model sdm ON sdm.model_id = sd.model_id
                              WHERE sd.patient_id = g.patient_id AND sdm.is_synthetic
                                AND g.time >= ss.start_time AND g.time < ss.end_time)
                 THEN ARRAY['sleep'] ELSE '{}' END              AS synthetic_channels,
       coalesce(ds.insulin_fast_units, 0)  AS insulin_fast_units,
       coalesce(ds.insulin_basal_units, 0) AS insulin_basal_units,
       coalesce(ds.oral_doses, 0)          AS oral_doses
FROM ts.glucose_fused g
LEFT JOIN wear w USING (patient_id, time)
LEFT JOIN hrv hv USING (patient_id, time)
LEFT JOIN dose ds USING (patient_id, time);
