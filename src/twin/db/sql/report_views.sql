-- Derived metrics. Nothing here is stored; every value is computed from core/ts.
-- Recreated on every `twin init-db` (the report schema holds only these views).

-- Patient master + computed age + display name + tag list.
CREATE VIEW report.patient_summary AS
SELECT p.patient_id,
       coalesce(nullif(concat_ws(' ', p.given_name, p.family_name), ''),
                ds.code || ' ' || p.source_subject_id)                AS display_name,
       p.mrn,
       p.name_prefix,
       p.given_name,
       p.family_name,
       p.sex,
       p.birth_date,
       p.birth_date_imputed,
       date_part('year', age(current_date, p.birth_date))::int       AS age,
       p.race_ethnicity,
       p.address_city,
       p.address_state,
       ds.code                                                        AS source,
       p.source_subject_id,
       coalesce(array_agg(t.code ORDER BY t.code) FILTER (WHERE t.code IS NOT NULL), '{}') AS tags
FROM core.patient p
JOIN ref.data_source ds USING (source_id)
LEFT JOIN core.patient_tag pt USING (patient_id)
LEFT JOIN ref.tag t USING (tag_id)
GROUP BY p.patient_id, ds.code;

-- Latest value per patient and analyte, with provenance. Real values are preferred
-- over synthetic ones regardless of date (composite twins mix CGMacros and Synthea).
CREATE VIEW report.observation_latest AS
SELECT DISTINCT ON (o.patient_id, c.analyte)
       o.patient_id,
       c.analyte,
       c.loinc,
       c.category,
       o.effective_at,
       o.value_num,
       cp.display        AS value_display,
       c.ucum_unit,
       ds.code           AS source,
       ds.is_synthetic
FROM core.observation o
JOIN ref.observation_code c USING (code_id)
JOIN ref.data_source ds USING (source_id)
LEFT JOIN ref.concept cp ON cp.concept_id = o.value_concept_id
ORDER BY o.patient_id, c.analyte, ds.is_synthetic, o.effective_at DESC;

-- Baseline clinical picture: latest values pivoted, plus values derived from them.
--   bmi          weight / height^2
--   ldl          real measured, else Friedewald (TC - HDL - TG/5, undefined if TG > 400) from real
--                inputs, else the synthetic equivalents
--   *_is_synthetic  true when a derived value rests on any synthetic input
--   homa_ir      fasting glucose (mg/dL) x fasting insulin (uU/mL) / 405
--   egfr         CKD-EPI 2021 from the latest creatinine, age at that draw and sex
--   cohort       by HbA1c: <5.7 normal, <6.5 prediabetes, else t2d
-- synthetic_analytes lists the values that came from a synthetic source.
CREATE VIEW report.patient_baseline AS
WITH pivot AS (
  SELECT patient_id,
         max(effective_at)                                                    AS effective_at,
         max(value_num) FILTER (WHERE analyte = 'hba1c')                      AS hba1c,
         max(value_num) FILTER (WHERE analyte = 'glucose_fasting')            AS fasting_glucose,
         max(value_num) FILTER (WHERE analyte = 'glucose_2h_postprandial')    AS glucose_2h_postprandial,
         max(value_num) FILTER (WHERE analyte = 'insulin')                    AS insulin,
         max(value_num) FILTER (WHERE analyte = 'c_peptide')                  AS c_peptide,
         max(value_num) FILTER (WHERE analyte = 'cholesterol_total')          AS total_cholesterol,
         max(value_num) FILTER (WHERE analyte = 'hdl')                        AS hdl,
         max(value_num) FILTER (WHERE analyte = 'triglycerides')              AS triglycerides,
         max(value_num) FILTER (WHERE analyte = 'ldl')                        AS ldl_measured,
         max(value_num) FILTER (WHERE analyte = 'weight')                     AS weight_kg,
         max(value_num) FILTER (WHERE analyte = 'height')                     AS height_cm,
         max(value_num) FILTER (WHERE analyte = 'sbp')                        AS sbp,
         max(value_num) FILTER (WHERE analyte = 'dbp')                        AS dbp,
         max(value_num) FILTER (WHERE analyte = 'creatinine')                 AS creatinine,
         max(effective_at) FILTER (WHERE analyte = 'creatinine')              AS creatinine_at,
         max(value_num) FILTER (WHERE analyte = 'uacr')                       AS uacr,
         max(value_num) FILTER (WHERE analyte = 'alt')                        AS alt,
         max(value_num) FILTER (WHERE analyte = 'ast')                        AS ast,
         max(value_num) FILTER (WHERE analyte = 'uric_acid')                  AS uric_acid,
         max(value_display) FILTER (WHERE analyte = 'smoking_status')         AS smoking_status,
         coalesce(array_agg(analyte ORDER BY analyte) FILTER (WHERE is_synthetic), '{}') AS synthetic_analytes
  FROM report.observation_latest
  GROUP BY patient_id
), kidney AS (
  SELECT pv.patient_id,
         CASE p.sex WHEN 'female' THEN 0.7 ELSE 0.9 END              AS kappa,
         CASE p.sex WHEN 'female' THEN -0.241 ELSE -0.302 END        AS alpha,
         CASE p.sex WHEN 'female' THEN 1.012 ELSE 1.0 END            AS sex_factor,
         date_part('year', age(pv.creatinine_at, p.birth_date))      AS age_at_creatinine
  FROM pivot pv JOIN core.patient p USING (patient_id)
)
SELECT pv.patient_id,
       pv.effective_at,
       pv.hba1c, pv.fasting_glucose, pv.glucose_2h_postprandial, pv.insulin, pv.c_peptide,
       pv.total_cholesterol, pv.hdl, pv.triglycerides,
       pv.weight_kg, pv.height_cm, pv.sbp, pv.dbp, pv.creatinine, pv.uacr, pv.alt, pv.ast, pv.uric_acid,
       pv.smoking_status,
       round(pv.weight_kg / ((pv.height_cm / 100) ^ 2), 1)                       AS bmi,
       pv.synthetic_analytes && ARRAY['weight', 'height']                       AS bmi_is_synthetic,
       pv.total_cholesterol - pv.hdl                                            AS non_hdl,
       round(pv.total_cholesterol / nullif(pv.hdl, 0), 2)                       AS tc_hdl_ratio,
       CASE WHEN pv.triglycerides <= 400 THEN round(pv.triglycerides / 5) END   AS vldl,
       coalesce(l.measured_real, l.friedewald_real, pv.ldl_measured, l.friedewald) AS ldl,
       l.measured_real IS NULL AND l.friedewald_real IS NULL                    AS ldl_is_synthetic,
       round(pv.fasting_glucose * pv.insulin / 405, 2)                          AS homa_ir,
       pv.synthetic_analytes && ARRAY['glucose_fasting', 'insulin']             AS homa_ir_is_synthetic,
       round(142 * least(pv.creatinine / k.kappa, 1) ^ k.alpha
                 * greatest(pv.creatinine / k.kappa, 1) ^ (-1.200)
                 * 0.9938 ^ k.age_at_creatinine * k.sex_factor)                 AS egfr,
       'creatinine' = ANY(pv.synthetic_analytes)                                AS egfr_is_synthetic,
       CASE WHEN pv.hba1c IS NULL THEN NULL
            WHEN pv.hba1c < 5.7   THEN 'normal'
            WHEN pv.hba1c < 6.5   THEN 'prediabetes'
            ELSE 't2d' END                                                      AS cohort,
       pv.synthetic_analytes
FROM pivot pv
JOIN kidney k USING (patient_id)
CROSS JOIN LATERAL (
  SELECT CASE WHEN NOT 'ldl' = ANY(pv.synthetic_analytes) THEN pv.ldl_measured END AS measured_real,
         f.friedewald,
         CASE WHEN NOT pv.synthetic_analytes && ARRAY['cholesterol_total', 'hdl', 'triglycerides']
              THEN f.friedewald END                                             AS friedewald_real
  FROM (SELECT CASE WHEN pv.triglycerides <= 400
                    THEN round(pv.total_cholesterol - pv.hdl - pv.triglycerides / 5) END AS friedewald) f
) l;

-- Conditions rolled up to clinical groups (hypertension, ckd, retinopathy, ...).
CREATE VIEW report.patient_conditions AS
SELECT c.patient_id,
       cg.code                                        AS condition_group,
       min(c.onset_at)                                AS first_onset,
       bool_or(c.abated_at IS NULL)                   AS active,
       array_agg(DISTINCT cp.display)                 AS conditions,
       bool_and(ds.is_synthetic)                      AS all_synthetic
FROM core.condition c
JOIN ref.concept cp USING (concept_id)
JOIN ref.condition_group cg ON cg.group_id = cp.condition_group_id
JOIN ref.data_source ds USING (source_id)
GROUP BY c.patient_id, cg.code;

-- Medication regimens with ingredient, the product prescribed, twin drug class, the visit
-- it was first prescribed at, and provenance.
CREATE VIEW report.medication_regimen AS
SELECT r.patient_id,
       r.regimen_id,
       m.medication_id                                AS rxcui,
       m.name                                         AS medication,
       r.product_rxcui,
       mp.display                                     AS product,
       dc.code                                        AS drug_class,
       dc.display                                     AS drug_class_display,
       coalesce(dc.glucose_lowering, false)           AS glucose_lowering,
       r.started_at,
       r.ended_at,
       r.ended_at IS NULL                             AS active,
       r.dose_value,
       r.dose_unit,
       r.times_per_day,
       r.as_needed,
       r.encounter_id,
       ds.code                                        AS source,
       ds.is_synthetic
FROM core.medication_regimen r
JOIN ref.medication m USING (medication_id)
LEFT JOIN ref.medication_product mp ON mp.product_rxcui = r.product_rxcui AND mp.medication_id = r.medication_id
LEFT JOIN ref.drug_class dc ON dc.class_id = m.drug_class_id
JOIN ref.data_source ds USING (source_id);

-- One row per condition episode (the same concept can recur: bronchitis, stress, ...).
--   display   the concept's name without its SNOMED semantic tag ("Acute bronchitis")
--   kind      'diagnosis' for disorders and anything in a clinical group; 'finding' for social
--             findings, situations and other tagged concepts (employment, stress, history of ...)
CREATE VIEW report.condition_episode AS
SELECT c.patient_id,
       c.concept_id,
       cp.system,
       cp.code,
       regexp_replace(cp.display, '\s*\([^()]*\)$', '')  AS display,
       CASE WHEN cg.code IS NOT NULL OR cp.display ~ '\(disorder\)$' OR cp.display !~ '\)$'
            THEN 'diagnosis' ELSE 'finding' END             AS kind,
       cg.code                                              AS condition_group,
       cg.display                                           AS condition_group_display,
       c.onset_at,
       c.abated_at,
       c.abated_at IS NULL                                  AS active,
       c.encounter_id,
       ds.code                                              AS source,
       ds.is_synthetic
FROM core.condition c
JOIN ref.concept cp USING (concept_id)
LEFT JOIN ref.condition_group cg ON cg.group_id = cp.condition_group_id
JOIN ref.data_source ds USING (source_id);

-- Every test and vital-sign result, with its analyte, coded answer (if any), the visit it was
-- recorded at and provenance. The record groups analytes into measures (twin.clinical.measures).
CREATE VIEW report.observation_result AS
SELECT o.patient_id,
       c.analyte,
       c.loinc,
       c.display                                      AS loinc_display,
       c.category,
       o.effective_at,
       o.value_num,
       cp.display                                     AS value_text,
       c.ucum_unit,
       o.encounter_id,
       ds.code                                        AS source,
       ds.is_synthetic
FROM core.observation o
JOIN ref.observation_code c USING (code_id)
JOIN ref.data_source ds USING (source_id)
LEFT JOIN ref.concept cp ON cp.concept_id = o.value_concept_id;

-- Visits with their SNOMED type and reason, and provenance.
CREATE VIEW report.visit AS
SELECT e.patient_id,
       e.encounter_id,
       e.encounter_class::text                                     AS encounter_class,
       regexp_replace(t.display, '\s*\([^()]*\)$', '')          AS type,
       regexp_replace(r.display, '\s*\([^()]*\)$', '')          AS reason,
       e.started_at,
       e.ended_at,
       ds.code                                                     AS source,
       ds.is_synthetic
FROM core.encounter e
LEFT JOIN ref.concept t ON t.concept_id = e.type_concept_id
LEFT JOIN ref.concept r ON r.concept_id = e.reason_concept_id
JOIN ref.data_source ds USING (source_id);

-- Readings from live-simulator devices (ref.device_model.is_live_simulator, written by
-- `twin simulate-stream`) feed only the live twin (report.twin_latest); every other view
-- below excludes them, so replayed history never doubles a patient's series.

-- Daily wearable summary per patient (one column per metric; NULL when not measured).
-- synthetic_metrics lists the metrics that came from a generator, not a real device.
CREATE VIEW report.activity_daily AS
SELECT d.patient_id,
       w.day,
       max(w.total) FILTER (WHERE m.code = 'steps')                     AS steps,
       round(max(w.mean) FILTER (WHERE m.code = 'heart_rate'), 1)       AS hr_mean,
       max(w.min) FILTER (WHERE m.code = 'heart_rate')                  AS hr_min,
       max(w.max) FILTER (WHERE m.code = 'heart_rate')                  AS hr_max,
       max(w.n) FILTER (WHERE m.code = 'heart_rate')                    AS hr_minutes,
       max(w.total) FILTER (WHERE m.code = 'wear_minutes')              AS wear_minutes,
       round(max(w.total) FILTER (WHERE m.code = 'mets'), 1)            AS met_minutes,
       round(max(w.total) FILTER (WHERE m.code = 'active_kcal'), 1)     AS active_kcal,
       round(max(w.mean) FILTER (WHERE m.code = 'activity_level'), 2)   AS activity_level_mean,
       round(max(w.mean) FILTER (WHERE m.code = 'spo2'), 1)             AS spo2_mean,
       round(max(w.mean) FILTER (WHERE m.code = 'respiration_rate'), 1) AS respiration_mean,
       round(max(w.mean) FILTER (WHERE m.code = 'stress'), 1)           AS stress_mean,
       round(max(w.mean) FILTER (WHERE m.code = 'skin_temp'), 2)        AS skin_temp_mean,
       round(max(w.mean) FILTER (WHERE m.code = 'eda'), 3)              AS eda_mean,
       coalesce(array_agg(DISTINCT m.code) FILTER (WHERE dm.is_synthetic), '{}') AS synthetic_metrics
FROM ts.wearable_daily w
JOIN core.device d USING (device_id)
JOIN ref.device_model dm USING (model_id)
JOIN ref.wearable_metric m USING (metric_id)
WHERE NOT dm.is_live_simulator
GROUP BY d.patient_id, w.day;

-- Sleep per night ("night of" = local date of the evening the sleep started).
CREATE VIEW report.sleep_nightly AS
WITH seg AS (
  SELECT d.patient_id,
         ((s.start_time AT TIME ZONE 'America/Chicago') - INTERVAL '12 hours')::date AS night,
         s.start_time, s.end_time, s.stage,
         extract(epoch FROM s.end_time - s.start_time) / 60                       AS minutes,
         dm.is_synthetic
  FROM ts.sleep_segment s
  JOIN core.device d USING (device_id)
  JOIN ref.device_model dm USING (model_id)
  WHERE NOT dm.is_live_simulator
)
SELECT patient_id,
       night,
       min(start_time)                                                  AS bedtime,
       max(end_time)                                                    AS wake_time,
       round(extract(epoch FROM max(end_time) - min(start_time)) / 60)  AS time_in_bed_min,
       round(sum(minutes) FILTER (WHERE stage <> 'awake'))              AS asleep_min,
       round(sum(minutes) FILTER (WHERE stage = 'light'))               AS light_min,
       round(sum(minutes) FILTER (WHERE stage = 'deep'))                AS deep_min,
       round(sum(minutes) FILTER (WHERE stage = 'rem'))                 AS rem_min,
       round(sum(minutes) FILTER (WHERE stage = 'awake'))               AS awake_min,
       round(100 * sum(minutes) FILTER (WHERE stage <> 'awake')
             / nullif(extract(epoch FROM max(end_time) - min(start_time)) / 60, 0), 1) AS efficiency_pct,
       bool_or(is_synthetic)                                            AS is_synthetic
FROM seg
GROUP BY patient_id, night;

-- Nightly SpO2 while asleep: mean, nadir, T90 (% of sleep below 90 %) and an
-- oxygen-desaturation index (drops of >= 3 points below the previous 5 minutes' max, per hour).
CREATE VIEW report.spo2_nightly AS
WITH sleep_spo2 AS (
  SELECT d.patient_id,
         ((ss.start_time AT TIME ZONE 'America/Chicago') - INTERVAL '12 hours')::date AS night,
         w.time, w.value, dm.is_synthetic
  FROM ts.wearable_sample w
  JOIN ref.wearable_metric m ON m.metric_id = w.metric_id AND m.code = 'spo2'
  JOIN ts.sleep_segment ss ON ss.device_id = w.device_id AND w.time >= ss.start_time
                          AND w.time < ss.end_time AND ss.stage <> 'awake'
  JOIN core.device d ON d.device_id = w.device_id
  JOIN ref.device_model dm USING (model_id)
  WHERE NOT dm.is_live_simulator
), flagged AS (
  SELECT *, value <= max(value) OVER (PARTITION BY patient_id, night ORDER BY time
                                      ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) - 3 AS dropped
  FROM sleep_spo2
), events AS (
  SELECT *, dropped AND NOT coalesce(lag(dropped) OVER (PARTITION BY patient_id, night ORDER BY time), false) AS event_start
  FROM flagged
)
SELECT patient_id,
       night,
       count(*)                                           AS sleep_minutes,
       round(avg(value), 1)                               AS spo2_mean,
       min(value)                                         AS spo2_min,
       round(100.0 * avg((value < 90)::int), 1)           AS t90_pct,
       round(count(*) FILTER (WHERE event_start) / (count(*) / 60.0), 1) AS odi_per_hour,
       bool_or(is_synthetic)                              AS is_synthetic
FROM events
GROUP BY patient_id, night;

-- Nightly HRV (RMSSD, ms). Real: from inter-beat intervals between 00:00 and 05:00 local
-- (successive beats < 2.5 s apart, differences < 200 ms, i.e. artefacts excluded); this does
-- not depend on the (synthetic) sleep staging. Synthetic: the generator's nightly value.
CREATE VIEW report.hrv_nightly AS
WITH beats AS (
  SELECT d.patient_id, w.time, w.value,
         w.value - lag(w.value) OVER (PARTITION BY w.device_id ORDER BY w.time)  AS diff,
         w.time - lag(w.time) OVER (PARTITION BY w.device_id ORDER BY w.time)    AS gap
  FROM ts.wearable_sample w
  JOIN ref.wearable_metric m ON m.metric_id = w.metric_id AND m.code = 'ibi_ms'
  JOIN core.device d ON d.device_id = w.device_id
  JOIN ref.device_model dm ON dm.model_id = d.model_id AND NOT dm.is_live_simulator
  WHERE (w.time AT TIME ZONE 'America/Chicago')::time < TIME '05:00'
), real_hrv AS (
  SELECT patient_id, ((time AT TIME ZONE 'America/Chicago') - INTERVAL '12 hours')::date AS night,
         round(sqrt(avg(diff * diff)), 1) AS rmssd_ms, count(*) AS beats, false AS is_synthetic
  FROM beats
  WHERE gap < INTERVAL '2.5 seconds' AND abs(diff) < 200
  GROUP BY 1, 2
  HAVING count(*) >= 300
), synthetic_hrv AS (
  SELECT d.patient_id, ((w.time AT TIME ZONE 'America/Chicago') - INTERVAL '12 hours')::date AS night,
         round(avg(w.value), 1) AS rmssd_ms, NULL::bigint AS beats, true AS is_synthetic
  FROM ts.wearable_sample w
  JOIN ref.wearable_metric m ON m.metric_id = w.metric_id AND m.code = 'hrv_rmssd'
  JOIN core.device d ON d.device_id = w.device_id
  JOIN ref.device_model dm ON dm.model_id = d.model_id AND NOT dm.is_live_simulator
  GROUP BY 1, 2
)
SELECT * FROM real_hrv
UNION ALL
SELECT * FROM synthetic_hrv;

-- Per-device daily CGM metrics, one row per patient, day and CGM (raw readings, no fusion).
-- coverage_pct = share of the device's expected readings present.
CREATE VIEW report.cgm_device_daily AS
SELECT        d.patient_id,
       g.day,
       d.device_id,
       m.manufacturer || ' ' || m.model_name                                   AS device_model,
       g.n,
       least(100, round(100.0 * g.n * extract(epoch FROM m.nominal_interval) / 86400, 1)) AS coverage_pct,
       round(g.mean, 1)                                                        AS mean_mg_dl,
       round(100 * g.sd / nullif(g.mean, 0), 1)                                AS cv_pct,
       round(3.31 + 0.02392 * g.mean, 2)                                       AS gmi,
       round(100.0 * g.n_very_low  / g.n, 1)                                   AS pct_very_low,
       round(100.0 * g.n_low       / g.n, 1)                                   AS pct_low,
       round(100.0 * g.n_target    / g.n, 1)                                   AS pct_target,
       round(100.0 * g.n_high      / g.n, 1)                                   AS pct_high,
       round(100.0 * g.n_very_high / g.n, 1)                                   AS pct_very_high
FROM ts.glucose_daily g
JOIN core.device d USING (device_id)
JOIN ref.device_model m USING (model_id)
WHERE m.kind = 'cgm' AND NOT m.is_live_simulator;

-- Per-device whole-window CGM metrics (raw readings, no fusion).
CREATE VIEW report.cgm_device_window AS
SELECT        d.patient_id,
       d.device_id,
       m.manufacturer || ' ' || m.model_name     AS device_model,
       min(r.time)                               AS period_start,
       max(r.time)                               AS period_end,
       count(*)                                  AS n,
       round(avg(r.glucose_mg_dl), 1)            AS mean_mg_dl,
       round(3.31 + 0.02392 * avg(r.glucose_mg_dl), 2) AS gmi
FROM ts.glucose_reading r
JOIN core.device d USING (device_id)
JOIN ref.device_model m USING (model_id)
WHERE m.kind = 'cgm' AND NOT m.is_live_simulator
GROUP BY d.patient_id, d.device_id, m.manufacturer, m.model_name;

-- Daily CGM metrics from the fused stream (ts.glucose_fused, 5-min grid).
-- coverage_pct = share of the day's 288 five-minute slots with a value.
CREATE VIEW report.cgm_daily AS
SELECT g.patient_id,
       g.day,
       g.n,
       least(100, round(100.0 * g.n / 288, 1))           AS coverage_pct,
       round(g.mean, 1)                                  AS mean_mg_dl,
       round(100 * g.sd / nullif(g.mean, 0), 1)          AS cv_pct,
       round(3.31 + 0.02392 * g.mean, 2)                 AS gmi,
       round(100.0 * g.n_very_low  / g.n, 1)             AS pct_very_low,
       round(100.0 * g.n_low       / g.n, 1)             AS pct_low,
       round(100.0 * g.n_target    / g.n, 1)             AS pct_target,
       round(100.0 * g.n_high      / g.n, 1)             AS pct_high,
       round(100.0 * g.n_very_high / g.n, 1)             AS pct_very_high
FROM ts.glucose_fused_daily g;

-- Whole-window CGM metrics from the fused stream, with the fusion's provenance.
CREATE VIEW report.cgm_window AS
SELECT f.patient_id,
       rm.manufacturer || ' ' || rm.model_name
         || coalesce(' + ' || sm.manufacturer || ' ' || sm.model_name, '') AS glucose_source,
       c.method_version,
       min(f.time)                                 AS period_start,
       max(f.time)                                 AS period_end,
       count(*)                                    AS n,
       round(avg(f.glucose_mg_dl), 1)              AS mean_mg_dl,
       round(3.31 + 0.02392 * avg(f.glucose_mg_dl), 2) AS gmi
FROM ts.glucose_fused f
JOIN core.cgm_calibration c USING (patient_id)
JOIN ref.device_model rm ON rm.model_id = c.reference_model_id
LEFT JOIN ref.device_model sm ON sm.model_id = c.secondary_model_id
GROUP BY f.patient_id, rm.manufacturer, rm.model_name, sm.manufacturer, sm.model_name, c.method_version;

-- Lab HbA1c vs GMI of the fused CGM stream. A large gap means the twin contradicts itself.
CREATE VIEW report.consistency AS
SELECT b.patient_id,
       b.hba1c,
       w.gmi,
       w.mean_mg_dl,
       w.glucose_source,
       round(abs(b.hba1c - w.gmi), 2) AS abs_diff,
       CASE WHEN abs(b.hba1c - w.gmi) <= 0.5 THEN 'ok'
            WHEN abs(b.hba1c - w.gmi) <= 1.0 THEN 'warn'
            ELSE 'inconsistent' END    AS status
FROM report.patient_baseline b
JOIN report.cgm_window w USING (patient_id);

-- First/last sensor timestamp per patient, across all of their devices.
CREATE VIEW report.sensor_window AS
SELECT d.patient_id, min(t.lo) AS window_start, max(t.hi) AS window_end
FROM core.device d
JOIN ref.device_model dm ON dm.model_id = d.model_id AND NOT dm.is_synthetic AND NOT dm.is_live_simulator
JOIN (
  SELECT device_id, min(time) AS lo, max(time) AS hi FROM ts.glucose_reading GROUP BY device_id
  UNION ALL
  SELECT device_id, min(time), max(time) FROM ts.wearable_sample GROUP BY device_id
) t USING (device_id)
GROUP BY d.patient_id;

-- Unified, patient-addressable event stream for the live replay.
CREATE VIEW report.replay_stream AS
SELECT d.patient_id,
       r.time,
       'glucose'::text                       AS kind,
       m.manufacturer || ' ' || m.model_name AS source,
       jsonb_build_object('glucose_mg_dl', r.glucose_mg_dl, 'specimen', m.specimen) AS payload
FROM ts.glucose_reading r
JOIN core.device d USING (device_id)
JOIN ref.device_model m USING (model_id)
WHERE NOT m.is_live_simulator
UNION ALL
SELECT d.patient_id,
       w.time,
       'activity',
       dm.manufacturer || ' ' || dm.model_name,
       jsonb_object_agg(m.code, w.value)
FROM ts.wearable_sample w
JOIN core.device d USING (device_id)
JOIN ref.device_model dm USING (model_id)
JOIN ref.wearable_metric m USING (metric_id)
WHERE NOT dm.is_live_simulator
GROUP BY d.patient_id, w.time, dm.manufacturer, dm.model_name
UNION ALL
SELECT d.patient_id,
       s.start_time,
       'sleep',
       dm.manufacturer || ' ' || dm.model_name,
       jsonb_build_object('stage', s.stage, 'until', s.end_time, 'synthetic', dm.is_synthetic)
FROM ts.sleep_segment s
JOIN core.device d USING (device_id)
JOIN ref.device_model dm USING (model_id)
WHERE NOT dm.is_live_simulator
UNION ALL
SELECT f.patient_id,
       f.time,
       'glucose_fused',
       'fused CGM',
       jsonb_build_object('glucose_mg_dl', f.glucose_mg_dl, 'sensors', f.source, 'censored', f.censored)
FROM ts.glucose_fused f
UNION ALL
SELECT md.patient_id,
       md.time,
       'medication',
       ds.code,
       jsonb_strip_nulls(jsonb_build_object(
         'medication', m.name, 'drug_class', dc.code, 'dose', md.dose_value,
         'unit', md.dose_unit, 'route', md.route))
FROM core.medication_dose md
JOIN ref.medication m USING (medication_id)
LEFT JOIN ref.drug_class dc ON dc.class_id = m.drug_class_id
JOIN ref.data_source ds ON ds.source_id = md.source_id;

-- Latest reading per patient and live-twin metric: what twin.streaming builds a patient's
-- state from when it is first loaded. Readings from live-simulator devices win; otherwise the
-- latest reading at or before now() (twin time runs past the wall clock for some recordings).
-- Historical glucose comes from the fused stream, live glucose from the live CGM.
-- metric = 'glucose', 'sleep' or a ref.wearable_metric code (beat-level ibi_ms excluded).
CREATE VIEW report.twin_latest AS
WITH candidate AS (
  SELECT d.patient_id, d.device_id, 'glucose'::text AS metric, r.time,
         r.glucose_mg_dl::numeric AS value_num, NULL::text AS value_text, NULL::timestamptz AS until,
         'mg/dL'::text AS unit, dm.manufacturer || ' ' || dm.model_name AS source, true AS is_live
  FROM core.device d
  JOIN ref.device_model dm ON dm.model_id = d.model_id AND dm.is_live_simulator AND dm.kind = 'cgm'
  CROSS JOIN LATERAL (SELECT time, glucose_mg_dl FROM ts.glucose_reading r
                      WHERE r.device_id = d.device_id ORDER BY time DESC LIMIT 1) r
  UNION ALL
  SELECT p.patient_id, NULL, 'glucose', f.time, f.glucose_mg_dl, NULL, NULL, 'mg/dL', 'fused CGM', false
  FROM core.patient p
  CROSS JOIN LATERAL (SELECT time, glucose_mg_dl FROM ts.glucose_fused f
                      WHERE f.patient_id = p.patient_id AND f.time <= now() ORDER BY time DESC LIMIT 1) f
  UNION ALL
  SELECT d.patient_id, d.device_id, m.code, w.time, w.value, NULL, NULL, m.unit,
         dm.manufacturer || ' ' || dm.model_name, dm.is_live_simulator
  FROM core.device d
  JOIN ref.device_model dm ON dm.model_id = d.model_id AND dm.kind = 'wearable'
  JOIN ref.wearable_metric m ON m.code NOT IN ('ibi_ms', 'wear_minutes')
  CROSS JOIN LATERAL (SELECT time, value FROM ts.wearable_sample w
                      WHERE w.device_id = d.device_id AND w.metric_id = m.metric_id
                        AND (dm.is_live_simulator OR w.time <= now())
                      ORDER BY time DESC LIMIT 1) w
  UNION ALL
  SELECT d.patient_id, d.device_id, 'sleep', s.start_time, NULL, s.stage::text, s.end_time, NULL,
         dm.manufacturer || ' ' || dm.model_name, dm.is_live_simulator
  FROM core.device d
  JOIN ref.device_model dm ON dm.model_id = d.model_id
  CROSS JOIN LATERAL (SELECT start_time, end_time, stage FROM ts.sleep_segment s
                      WHERE s.device_id = d.device_id AND (dm.is_live_simulator OR s.start_time <= now())
                      ORDER BY start_time DESC LIMIT 1) s
)
SELECT DISTINCT ON (patient_id, metric) *
FROM candidate
ORDER BY patient_id, metric, is_live DESC, time DESC;
