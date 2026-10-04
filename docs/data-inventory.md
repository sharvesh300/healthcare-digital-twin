# Twin data inventory (2026-10-04)

**Principle:** the twin is driven by **CGM plus continuous wearables**. Medication timing
cannot come from wearables; it comes from records, dose logs or pens. Every value is
marked real or synthetic.

## 1. Available now (all local, works offline)

| Cohort | People | Real | Synthetic (flagged) |
|---|---|---|---|
| **CGMacros twins** | 14 T2D | CGM: Dexcom + Libre, fused, 5 min, ~10 days. Fitbit: HR, METs or intensity. Baseline labs. | EHR history (Synthea): BP, kidney labs, conditions, medications, visits. Sleep, SpO₂, respiration, stress, nightly HRV (generator). |
| **BIG IDEAs twins** | 16 prediabetes / elevated glucose | Dexcom G6 CGM. Empatica E4: HR, **inter-beat intervals (true HRV)**, skin temperature, EDA. HbA1c. | EHR history (Synthea general cohort). Sleep, SpO₂, respiration, stress (generator). |
| **NHANES** | 1,879 with diabetes | Labs, BP, body measures, conditions, 9,869 prescriptions, minute steps for 1,607 people | – |

**Channels in the 30 twins** (5-minute feature series: 80,567 rows):

| Channel | Coverage | Source |
|---|---|---|
| Glucose (fused CGM) | 30 twins, ~10 days | real |
| Heart rate | 30 | real (Fitbit / E4) |
| HRV, RMSSD | 16 real (5-min and nightly); 14 nightly synthetic | real / synthetic |
| Skin temperature, EDA | 16 | real (E4) |
| Activity (METs, intensity) | 14 | real (Fitbit) |
| Sleep stages, SpO₂ (sleep + spot checks), respiration, stress | 30 | **synthetic**: rule-based, driven by the twin's real HR, age, BMI, sleep apnoea and COPD |
| Medication regimens, conditions, BP, kidney labs | 30 | synthetic (Synthea) |
| Timed medication doses | none | – |

The generator is deterministic, never overwrites real data and is never linked to glucose.
Generated channels sit under a device flagged `is_synthetic`, are listed in
`synthetic_channels` / `synthetic_metrics`, and carry the FHIR tag `synthetic-sensors`.
They are for display, alerts and pipeline testing, **not for training or validating models**.

**Ready to use:**
- **Views:** `report.*` covers CGM, sleep, SpO₂ (mean, nadir, T90, ODI), HRV, activity, baseline and consistency.
- **Feature store:** `data/features/*.parquet`, 1,909 patients and 14,321 patient-days.
- **FHIR:** 30 twins with records and daily CGM, HR, sleep and SpO₂ summaries.
- **Twin API:** `/twin/{id}`, timeline, and the WebSocket replay.

## 2. Still to integrate

| Priority | Source | Adds | Status |
|---|---|---|---|
| 1 | **ShanghaiT2DM** (~100 T2D) | CGM + **timed insulin and oral doses** + labs | needs a browser download from figshare into `data/raw/shanghai/` |
| 2 | Real overnight SpO₂ (e.g. PhysioNet UCD Sleep Apnea DB) | calibrate the SpO₂ generator against real desaturations | optional; open |
| 3 | A real wearable source with sleep and SpO₂ | replace the generated channels | AI-READI is not accessible; candidates are the team's own device exports (Garmin, Apple Health, Health Connect) |
| 4 | Longitudinal cohort (ACCORD, All of Us) | years of HbA1c, BP, eGFR, medication changes | application |
