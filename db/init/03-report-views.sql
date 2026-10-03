-- Derived metrics. Nothing here is stored; every value is computed from core/ts.

-- Patient master + computed age + tag list.
CREATE VIEW report.patient_summary AS
SELECT p.patient_id,
       p.mrn,
       p.name_prefix,
       p.given_name,
       p.family_name,
       p.sex,
       p.birth_date,
       date_part('year', age(current_date, p.birth_date))::int AS age,
       p.race_ethnicity,
       p.address_city,
       p.address_state,
       ds.code AS source,
       p.source_subject_id,
       coalesce(array_agg(t.code ORDER BY t.code) FILTER (WHERE t.code IS NOT NULL), '{}') AS tags
FROM core.patient p
JOIN ref.data_source ds USING (source_id)
LEFT JOIN core.patient_tag pt USING (patient_id)
LEFT JOIN ref.tag t USING (tag_id)
GROUP BY p.patient_id, ds.code;

-- Latest measured labs pivoted, plus values derived from them.
-- LDL by Friedewald (TC - HDL - TG/5), undefined when TG > 400 mg/dL.
CREATE VIEW report.patient_baseline AS
WITH latest AS (
  SELECT DISTINCT ON (lr.patient_id, lr.code_id)
         lr.patient_id, c.loinc, lr.value, lr.effective_at
  FROM core.lab_result lr
  JOIN ref.observation_code c USING (code_id)
  ORDER BY lr.patient_id, lr.code_id, lr.effective_at DESC
), pivot AS (
  SELECT patient_id,
         max(effective_at)                               AS effective_at,
         max(value) FILTER (WHERE loinc = '4548-4')      AS hba1c,
         max(value) FILTER (WHERE loinc = '1558-6')      AS fasting_glucose,
         max(value) FILTER (WHERE loinc = '20448-7')     AS insulin,
         max(value) FILTER (WHERE loinc = '2093-3')      AS total_cholesterol,
         max(value) FILTER (WHERE loinc = '2085-9')      AS hdl,
         max(value) FILTER (WHERE loinc = '2571-8')      AS triglycerides,
         max(value) FILTER (WHERE loinc = '29463-7')     AS weight_kg,
         max(value) FILTER (WHERE loinc = '8302-2')      AS height_cm
  FROM latest
  GROUP BY patient_id
)
SELECT pivot.*,
       round(weight_kg / ((height_cm / 100) ^ 2), 1)                        AS bmi,
       total_cholesterol - hdl                                              AS non_hdl,
       round(total_cholesterol / nullif(hdl, 0), 2)                         AS tc_hdl_ratio,
       CASE WHEN triglycerides <= 400 THEN round(triglycerides / 5) END     AS vldl,
       CASE WHEN triglycerides <= 400
            THEN round(total_cholesterol - hdl - triglycerides / 5) END     AS ldl,
       CASE WHEN hba1c IS NULL THEN NULL
            WHEN hba1c < 5.7   THEN 'normal'
            WHEN hba1c < 6.5   THEN 'prediabetes'
            ELSE 't2d' END                                                  AS cohort
FROM pivot;

-- Daily CGM metrics from the primary CGM of that day (finest nominal interval wins:
-- Dexcom 5 min over Libre 15 min). coverage_pct = share of expected readings present.
CREATE VIEW report.cgm_daily AS
SELECT DISTINCT ON (d.patient_id, g.day)
       d.patient_id,
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
WHERE m.kind = 'cgm'
ORDER BY d.patient_id, g.day, m.nominal_interval;

-- Whole-window CGM metrics from each patient's primary CGM.
CREATE VIEW report.cgm_window AS
SELECT DISTINCT ON (d.patient_id)
       d.patient_id,
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
WHERE m.kind = 'cgm'
GROUP BY d.patient_id, d.device_id, m.manufacturer, m.model_name, m.nominal_interval
ORDER BY d.patient_id, m.nominal_interval;

-- Lab HbA1c vs CGM-derived GMI. A large gap means the twin contradicts itself.
CREATE VIEW report.consistency AS
SELECT b.patient_id,
       b.hba1c,
       w.gmi,
       w.mean_mg_dl,
       w.device_model,
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
JOIN (
  SELECT device_id, min(time) AS lo, max(time) AS hi FROM ts.glucose_reading GROUP BY device_id
  UNION ALL
  SELECT device_id, min(time), max(time) FROM ts.fitbit_reading GROUP BY device_id
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
UNION ALL
SELECT d.patient_id,
       r.time,
       'activity',
       m.manufacturer || ' ' || m.model_name,
       jsonb_strip_nulls(jsonb_build_object(
         'heart_rate', r.heart_rate, 'mets', r.mets,
         'activity_level', r.activity_level, 'active_kcal', r.active_kcal))
FROM ts.fitbit_reading r
JOIN core.device d USING (device_id)
JOIN ref.device_model m USING (model_id)
UNION ALL
SELECT ml.patient_id,
       ml.started_at,
       'meal',
       NULL,
       jsonb_strip_nulls(jsonb_build_object(
         'meal_type', ml.meal_type, 'energy_kcal', ml.energy_kcal, 'carbs_g', ml.carbs_g,
         'protein_g', ml.protein_g, 'fat_g', ml.fat_g, 'fiber_g', ml.fiber_g,
         'pct_consumed', ml.pct_consumed))
FROM core.meal ml;
