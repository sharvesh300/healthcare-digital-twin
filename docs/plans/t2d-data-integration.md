# Plan: T2D data integration for the digital twin

Status: proposal · 2026-10-03 · scope: steps, medications, laboratory data, blood pressure and
other T2D-relevant data; meals are dropped for now.

## 1. Goal

Extend the twin from "CGM + wearable + baseline labs" to a T2D record that can support three uses:

- **Show** a patient: a timeline of glucose, activity, vitals, labs, medications, conditions.
- **Train ML**: glucose forecasting, hypo/hyper risk, HbA1c/eGFR/BP trajectories,
  medication-response models.
- **Simulate**: "what if" scenarios (dose change, step target) driven by models trained on
  real data.

## 2. The constraint that shapes the plan

Treatment and activity effects can only be learned when the **inputs and the glucose outcome
come from the same person**. Stitching one person's medications onto another person's CGM (as
the current CGMacros + Synthea composite does for the EHR) produces data that looks complete
but has no causal signal. A model trained on it learns noise.

No open dataset has CGM, steps, medications, labs and BP for the same people. The plan
therefore uses several **cohorts**, each kept internally consistent, in one schema, with
provenance on every row:

| Cohort | People | CGM | Steps / wearable | Medications | Labs | BP | Conditions | Access |
|---|---|---|---|---|---|---|---|---|
| **CGMacros** (have) | 14 T2D | Dexcom + Libre, fused | HR, METs/intensity (no steps) | ✗ (synthetic only) | baseline panel | ✗ (synthetic) | ✗ (synthetic) | open |
| **ShanghaiT2DM** | ~100 T2D | Libre, 15 min, 3–14 d | ✗ | ✓ insulin and oral agents, with doses and times | ✓ broad panel | ? | ✓ complications, comorbidities | open, CC BY 4.0 |
| **NHANES 2011–2014**, diabetes subset | ~1,000+ adults | ✗ | ✓ minute-level steps, 7 d | ✓ prescription list | ✓ broad panel | ✓ | ✓ self-report | open |
| **AI-READI** v2 | 1,067 (whole T2D spectrum) | Dexcom G6, 10 d | ✓ Garmin: steps, HR, sleep, SpO₂, stress, respiration | ✓ (controlled tier) | ✓ incl. C-peptide, CRP, NT-proBNP | ✓ | ✓ | registered / controlled |
| **Synthea** (have) | any | ✗ | ✗ | synthetic | synthetic | synthetic | synthetic | generated |

Notes on the table:
- **ShanghaiT2DM:** the exact column list is verified at download. The PMC article was not machine-readable here.
- **AI-READI:** this is the **only source with every modality in the same person**, so it becomes the primary "full twin" cohort once access is granted. Access requires an application on FAIRhub, and medication history sits in the controlled tier. The full release is about 2 TB, mostly retinal images; only the CGM, wearable and clinical subsets are needed.
- **NHANES:** cross-sectional and population-representative. Use it for population models and priors, not time-series twins.
- **Synthea:** keep for EHR history and long-horizon simulation demos. Always flagged synthetic, and never used as a training label for real-world effects.

## 3. Use of each cohort

| Task | CGMacros | ShanghaiT2DM | NHANES | AI-READI | Synthea |
|---|---|---|---|---|---|
| Twin display / demo | ✓ | ✓ | – | ✓ | backbone |
| Glucose forecasting (30/60 min) | ✓ (activity) | ✓ (insulin, oral agents) | – | ✓ (activity) | – |
| Hypo / hyper event prediction | weak (few lows) | ✓ (insulin users) | – | ✓ | – |
| Medication response (dose → glucose) | – | ✓ within-person | – | ✓ between-person | – |
| HbA1c / BP / eGFR risk models | – | ✓ small | ✓ | ✓ | trajectory demos only |
| Activity effect (steps → glucose / HbA1c) | – | – | ✓ (HbA1c) | ✓ (CGM) | – |

## 4. Data integration ("fusion") method

The method is applied per cohort, per patient. No cross-dataset person linkage, except the
existing CGMacros composite, which stays tagged `composite-patient`.

1. **Identity.**
   - Each real person is one `core.patient`, with `patient_id = uuid5(source, subject_id)`.
   - Composite CGMacros patients keep their Synthea UUID.
   - Every row carries a `source_id`, so a value's origin, and whether it's real or synthetic, is always known.
2. **Time.**
   - Each patient gets one `time_offset` into twin time, as today.
   - Within a person, device clocks are validated: CGM vs CGM (done), wearable HR/steps vs CGM, and medication-dose timing vs glucose response in ShanghaiT2DM.
3. **Semantics.** Every value is mapped to a standard code. Mapping tables are seed CSVs in `seeds/mappings/`, so they're reviewable.
   - Labs, vitals and activity → LOINC.
   - Conditions → SNOMED CT, plus ICD-10-CM.
   - Drugs → RxNorm ingredient, plus ATC class.
   - Units → UCUM.
4. **Units.** Values are converted once at ingest:

   | Measure | From | To |
   |---|---|---|
   | Glucose | mmol/L | mg/dL (×18.016) |
   | HbA1c | mmol/mol (IFCC) | % (NGSP) = 0.09148 × IFCC + 2.152 |
   | Creatinine | µmol/L | mg/dL (÷88.42) |
   | Total cholesterol, HDL, LDL | mmol/L | mg/dL (×38.67) |
   | Triglycerides | mmol/L | mg/dL (×88.57) |
   | Uric acid | µmol/L | mg/dL (÷59.48) |
   | Weight / height | lb / in | kg / cm |

5. **Medications.**
   - Each source drug name is normalised to an RxNorm ingredient, then to an ATC code, then to a twin drug class:

     | Area | Twin drug classes |
     |---|---|
     | Glucose-lowering | biguanide, sulfonylurea, glinide, DPP-4i, SGLT2i, GLP-1 RA, TZD, α-glucosidase inhibitor, basal / bolus / premixed insulin |
     | Cardio-renal | statin, ACEi / ARB, other |

   - Doses go into canonical units (mg/day, U).
   - Two record types are kept, regimen and dose event, plus a defined-daily-dose ratio so drugs can be compared.
6. **Derived values** are computed in views, as now, never stored:
   - eGFR by CKD-EPI 2021, from creatinine, age and sex;
   - HOMA-IR and HOMA-B, from fasting glucose with insulin or C-peptide;
   - BMI, LDL (if not measured), and daily step and sleep totals;
   - resting heart rate;
   - medication exposure per day.
7. **Conflicts.** Real values beat synthetic ones. Within a source, the latest measurement wins. Exact duplicates (same code, time and value) are dropped.
8. **Quality checks**, run at every load:
   - physiological ranges;
   - code-mapping coverage, failing below 98 %;
   - recomputed vs reported values (eGFR, BMI);
   - cross-modal plausibility (GMI vs HbA1c, drug class vs HbA1c);
   - per-cohort missingness report.

## 5. Schema changes

The schema stays normalised, in the same style as today.

**Removed:**
- `core.meal`, `core.meal_photo`, the `ref.meal_type` enum and the meal replay events.
- CGM fusion still needs meal **times** for its clock-offset check. It will read them transiently from the source CSV, not from tables.

**Changed:**

| Before | After |
|---|---|
| `ref.data_source` | adds `is_synthetic` and `access_tier` (open, registered, controlled) |
| `ref.observation_code` | adds `category` (laboratory, vital-signs, activity, survey) and `value_type` (numeric, coded) |
| `core.lab_result` | **`core.observation`**: `(patient_id, code_id, effective_at, value_num \| value_concept_id, source_id)`. Labs, vitals and survey answers in one long table; exactly one value column is set. |
| `ts.fitbit_reading` (wide, Fitbit-specific) | **`ts.wearable_sample`**: `(device_id, metric_id, time, value)`. Long form, because Fitbit, Garmin and ActiGraph export different metrics. Compressed, segmented by device and metric. |

**New:**

| Table | Contents |
|---|---|
| `ref.wearable_metric` | steps, heart_rate, mets, activity_level, active_kcal, spo2, respiration_rate, stress — each with its LOINC code and unit |
| `ts.sleep_segment` | `(device_id, start, end, stage)` |
| `ref.concept` | coded concepts: SNOMED, ICD-10-CM, LOINC answers |
| `core.condition` | `(patient_id, concept_id, onset, abatement, source_id)`, covering comorbidities and complications |
| `ref.drug_class` | twin drug classes |
| `ref.medication` | RxNorm ingredient, ATC code, class, route |
| `core.medication_regimen` | `(patient_id, medication_id, start, end, dose, unit, times_per_day, source_id)` |
| `core.medication_dose` | `(patient_id, medication_id, time, dose, unit, route, source_id)`: timed doses such as insulin injections |
| `core.encounter` | `(patient_id, start, end, class, source_id)`: visit timeline for display |
| continuous aggregates | daily steps, daily heart rate (mean and resting), daily sleep |
| `ml` schema | feature-store views, see § 7 |

**Synthea data copied into the twin DB:** medications, conditions, BP, eGFR/UACR, encounters. They're copied from HAPI with `source = synthea` and `is_synthetic = true`, so the composite twins show a full chart in one place. FHIR stays the system of record for the EHR.

## 6. Source-specific loaders

| Source | Loader | Key work |
|---|---|---|
| NHANES 2011–14 | `sources/nhanes.py` | Read the XPT files for 2011–12 (suffix `_G`) and 2013–14 (`_H`), joined on `SEQN`. Diabetes subset: `DIQ010` (diagnosed), or HbA1c ≥ 6.5 %, or a glucose-lowering drug. Minute-level steps come from the PhysioNet release. Survey weights are kept for population estimates. |
| ShanghaiT2DM | `sources/shanghai.py` | One file per patient, plus the summary sheet. Glucose mmol/L → mg/dL. Free-text drug entries are parsed into drug, dose, unit and frequency against a curated mapping CSV (Chinese brand and generic names, then RxNorm). Single CGM, so fusion passes it through as a one-sensor stream. |
| AI-READI | `sources/aireadi.py` | Read the OMOP-style clinical tables (labs, vitals, conditions, drug exposure), Dexcom G6 CGM, and Garmin JSON (steps, HR, sleep, SpO₂, stress, respiration). Retinal images and ECG are kept as references only. |
| Synthea | `sources/synthea_ehr.py` | Medication requests, conditions, BP, labs and encounters from the bundles, through the same mappings. |

All four become steps of the `twin` CLI, `ingest-<source>`, each idempotent with a validation report.

## 7. ML feature store (`ml` schema, plus a Parquet export)

The feature store has four grains:

| Table | Grain | Contents |
|---|---|---|
| `ml.patient_static` | one row per patient | demographics, diabetes duration, baseline labs, derived indices (HOMA-IR, eGFR), comorbidities, regimen class at baseline, cohort, `is_synthetic` |
| `ml.patient_day` | patient × day | fused CGM metrics (mean, CV, TIR / TBR / TAR, GMI), steps, active minutes, HR (mean and resting), sleep, medication exposure per class (dose / DDD), BP if measured that day |
| `ml.series_5min` | patient × 5 min | glucose (fused), insulin and oral-agent doses, steps, HR, censored and source flags. The input to forecasting models. |
| `ml.treatment_episode` | regimen start or change | outcome windows before and after (mean glucose, TIR, hypo count; HbA1c where available) |

Also:
- **Labels:** future glucose at +30 and +60 min, hypo in the next 60 min, next-day TIR, HbA1c at follow-up, eGFR decline.
- **Splits:** by patient, and by time within a patient, to avoid leakage. Synthetic rows are excluded from training labels by default.
- **Export:** `twin export-features` writes `data/features/<cohort>/<table>.parquet`, plus a dataset card covering provenance, codes, missingness and splits.

## 8. Simulation

Simulation is phased so it rests on real data:

1. **Short horizon**, minutes to days. A data-driven glucose forecaster, trained on ShanghaiT2DM and AI-READI, driven by scenario inputs: dose changes, step targets.
2. **Long horizon**, months to years. Population models for HbA1c, BP and eGFR trajectories by regimen and activity (NHANES, AI-READI), with Synthea histories as the visual backbone for composite twins.
3. **Physiological model**, such as the Bergman minimal model or a T2D meal model. **Deferred:** it needs carbohydrate input, and meals are out of scope for now. Without meals, short-horizon simulation cannot explain post-meal excursions, so treat it as indicative.

## 9. Full data needed to simulate and show a T2D twin

Abbreviations for the source columns:

| Abbrev. | Cohort |
|---|---|
| CM | CGMacros |
| SH | ShanghaiT2DM |
| NH | NHANES |
| AR | AI-READI |
| SY | Synthea (synthetic) |

### Demographics and history

| Element | Code (indicative) | Unit / grain | Sources |
|---|---|---|---|
| Age / birth date, sex, race / ethnicity | – | patient | CM, SH, NH, AR, SY |
| Height, weight, BMI | 8302-2, 29463-7, 39156-5 | cm, kg, kg/m² | all |
| Diabetes duration | – | years | SH, NH, AR |
| Smoking, alcohol | 72166-2, 74013-4 | coded | SH, NH, AR, SY |

### Glucose and glycaemic control

| Element | Code (indicative) | Unit / grain | Sources |
|---|---|---|---|
| CGM glucose (fused) | 99504-3 | mg/dL, 5 min | CM, SH, AR |
| Capillary glucose | 41653-7 | mg/dL, event | CM, SH |
| HbA1c | 4548-4 | %, visit | all |
| Fasting glucose; 2-h glucose | 1558-6; 20438-8 | mg/dL | all except CM (2-h) |
| Glycated albumin | 1758-2 | % | SH |

### Insulin secretion and resistance

| Element | Code (indicative) | Unit / grain | Sources |
|---|---|---|---|
| Fasting insulin | 20448-7 | µIU/mL | CM, SH, NH |
| C-peptide | 1986-9 | ng/mL | SH, AR |
| HOMA-IR, HOMA-B | derived | – | from the above |

### Lipids, kidney and liver

| Element | Code (indicative) | Unit / grain | Sources |
|---|---|---|---|
| Lipids (TC, HDL, LDL, TG) | 2093-3, 2085-9, 13457-7 / 18262-6, 2571-8 | mg/dL | all |
| Creatinine | 2160-0 | mg/dL | SH, NH, AR, SY |
| eGFR (CKD-EPI 2021) | 98979-8 (derived) | mL/min/1.73 m² | from creatinine |
| UACR | 9318-7 | mg/g | NH, AR, SY |
| BUN, uric acid, potassium | 3094-0, 3084-1, 2823-3 | mg/dL, mmol/L | SH, NH, AR |
| ALT, AST | 1742-6, 1920-8 | U/L | NH, AR |

### Cardiovascular and inflammation

| Element | Code (indicative) | Unit / grain | Sources |
|---|---|---|---|
| hs-CRP, NT-proBNP, troponin T | 30522-7, 33762-6, 67151-1 | mg/L, pg/mL, ng/L | AR |
| Systolic / diastolic BP | 8480-6 / 8462-4 | mmHg, visit | NH, AR, SY |

### Wearable and activity

| Element | Code (indicative) | Unit / grain | Sources |
|---|---|---|---|
| Heart rate; resting HR | 8867-4; 40443-4 | /min, 1 min; day | CM, AR |
| Steps | 55423-8 | count, 1 min → day | NH, AR (CM: none) |
| Active minutes / METs / intensity | – | 1 min | CM, NH (derived), AR |
| Sleep duration / stages | 93832-4 | min, segments | AR |
| SpO₂, respiration, stress / HRV | 59408-5, 9279-1, – | %, /min | AR |

### Medications

| Element | Code (indicative) | Unit / grain | Sources |
|---|---|---|---|
| Regimen: drug, class, dose, frequency, start / stop | RxNorm, ATC | mg/day, U/day | SH, NH (list), AR, SY |
| Dose events (insulin, oral agents), with times | RxNorm | U, mg, timestamp | SH |

### Conditions and complications

| Element | Code (indicative) | Unit / grain | Sources |
|---|---|---|---|
| T2D, hypertension, dyslipidaemia, obesity, CKD, retinopathy, neuropathy, CAD / stroke / HF, MASLD, hypoglycaemia history | SNOMED / ICD-10 | onset date | SH, NH (self-report), AR, SY |

### Timeline and outcomes

| Element | Code (indicative) | Unit / grain | Sources |
|---|---|---|---|
| Encounters / visit timeline | – | date | AR, SY |
| Outcome labels (future glucose, hypo, TIR, HbA1c, eGFR decline) | derived | – | as available per cohort |

**Out of scope for now:** meals and diet, retinal imaging and ECG (stored as references only),
environmental sensors (AI-READI).

Codes marked indicative are confirmed against LOINC, RxNorm and SNOMED when the seed CSVs are
written. The ShanghaiT2DM column list and the AI-READI table names are confirmed against the
downloaded data dictionaries.

## 10. Phases

| Phase | Work | Needs |
|---|---|---|
| **0. Schema** | Remove meals. Generalise observations, wearables, medications and conditions. Migrate CGMacros. Copy Synthea medications, conditions, BP, eGFR/UACR and encounters into the twin DB (synthetic-flagged). Update views, FHIR and replay. | nothing |
| **1. NHANES** | Diabetes subset: steps, labs, BP, medications, conditions. Mapping seeds. Population report. | ~100 MB download |
| **2. ShanghaiT2DM** | CGM, medication dose events, labs, complications. Drug-name mapping. Dose → glucose timing check. | ~10s of MB |
| **3. AI-READI** | Apply now (lead time). Then load CGM, Garmin, clinical data, and medications if controlled access is granted. | approval, larger download |
| **4. Feature store** | `ml` views, Parquet export, dataset cards, baseline models (forecaster, hypo classifier, treatment-episode analysis). | phases 1–2 (3 optional) |
| **5. Simulation and twin view** | Scenario API (dose change, step target) using the trained forecaster. A twin timeline endpoint covering all of § 9. | phase 4 |

Each phase ships with:
- validation reports and unit tests (unit conversion, code mapping, derived values);
- idempotent loaders;
- README updates.

## 11. Decisions needed

1. **Registry design:** single-source real twins for ML (recommended), with the CGMacros composite twins kept only for demos.
2. **AI-READI:** someone with a research affiliation applies on FAIRhub (registered tier; controlled tier for medications). The licence forbids redistribution, so data stays out of git, as now.
3. **Bandwidth:** this machine measured about 30 KB/s. NHANES and ShanghaiT2DM are fine; AI-READI subsets need a faster link.
4. **Medication granularity:** class-level exposure is enough for v1 models. Dose-level modelling only for ShanghaiT2DM insulin.

## Sources

- AI-READI: [FAIRhub dataset](https://fairhub.io/datasets/2), [overview, Retinal Physician 2025](https://retinalphysician.com/issues/2025/june/ai-readi-a-multimodal-data-set-for-diabetic-eye-research/), [GitHub](https://github.com/AI-READI), [GWU dataset overview](https://hivelab.biochemistry.gwu.edu/wiki/AI-READI_Dataset_Overview)
- ShanghaiT2DM: [Chinese diabetes datasets for data-driven machine learning (Sci Data 2023)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9849330/)
- NHANES steps: [Minute-level step count, NHANES 2011–2014 (PhysioNet)](https://physionet.org/content/minute-level-step-count-nhanes/)
- HL7 CGM IG (codes already in use): [build.fhir.org/ig/HL7/cgm](https://build.fhir.org/ig/HL7/cgm/)
