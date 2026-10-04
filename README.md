# Healthcare Digital Twin: type 2 diabetes

A data platform for T2D digital twins: real sensor, lab, medication and activity data from
open cohorts, integrated into one normalised TimescaleDB schema and a FHIR server, with
an ML feature store, baseline models and a twin API for display and what-if scenarios.

| Cohort | People | What is real | Use |
|---|---|---|---|
| **CGMacros composite** | 14 T2D | two CGMs (fused), Fitbit HR/METs, baseline labs. EHR history is **synthetic** (Synthea, matched on sex, age and BMI). | twin display, CGM analytics, glucose forecasting |
| **BIG IDEAs composite** | 16 (prediabetes / elevated glucose) | Dexcom G6 CGM, Empatica E4 heart rate, **inter-beat intervals (true HRV)**, skin temperature, EDA, HbA1c. EHR history is **synthetic** (Synthea general cohort, matched on sex, age range and glycaemic group). | twin display, CGM + HRV/EDA analytics |
| **NHANES 2011–2014** | 1,879 adults with diabetes | everything: labs, BP, body measures, self-reported conditions, prescription medications, minute-level wrist steps | population models (HbA1c vs steps, BP, kidney, medications) |
| ShanghaiT2DM | ~100 T2D | CGM with timed insulin and oral doses, labs | planned (Phase 2): download blocked from scripts, see below |
| AI-READI | 1,067 | CGM, Garmin, labs, BP, medications in the same people | planned (Phase 3): needs a FAIRhub access application |

**Synthetic wearables.** For every composite twin, `simulate-wearables` generates sleep, SpO₂,
respiration, stress and nightly HRV (where no real HRV exists) with a rule-based generator.
These channels are stored under a device flagged `is_synthetic`, so they can be displayed and
alerted on but never mistaken for measurements. See [Synthetic wearables](#3-synthetic-wearables).

Every row carries its source, and synthetic values are flagged everywhere. Composite twins
are for demonstration; ML for treatment or activity effects uses single-source real
cohorts. The plan is in [docs/plans/t2d-data-integration.md](docs/plans/t2d-data-integration.md).

![T2D digital twin data pipeline](docs/images/data-pipeline.png)

*Interactive diagram (pan, zoom, trace a flow):
[docs/diagrams/data-pipeline.html](docs/diagrams/data-pipeline.html). It was made with
[archify](https://github.com/tt-a1i/archify) from
[data-pipeline.dataflow.json](docs/diagrams/data-pipeline.dataflow.json).*

**Documentation**
- [docs/data-dictionary.md](docs/data-dictionary.md) lists every column available for a patient: identity, EHR (every analyte, condition, medication and encounter column), sensors (CGM raw and fused, wearables, sleep), derived views, ML features and vocabularies. Each item is marked real or synthetic per cohort.
- [How the synthetic data is created](#how-the-synthetic-data-is-created) (below) covers Synthea EHR histories, composite matching, the time shift and the wearable generator.
- [docs/data-inventory.md](docs/data-inventory.md) is a one-page summary of what the twin has now and what is still to integrate.
- [docs/plans/t2d-data-integration.md](docs/plans/t2d-data-integration.md) is the phased integration plan.

## Quick start

Docker runs the infrastructure (TimescaleDB and HAPI FHIR). The pipeline and the API run on
the host with `uv` and connect to them on `localhost`.

```bash
cp .env.example .env                      # set PG_PORT etc. if 5432/8080 are taken
uv sync
scripts/up.sh                             # docker compose up -d, waits for TimescaleDB + HAPI FHIR
seeds/download_cgmacros.sh                # ~7 MB: only the CSVs, fetched from the zip via HTTP ranges
seeds/generate_cohort.sh                  # Synthea diabetic cohort -> data/synthea/fhir (needs Java 17)
seeds/download_nhanes.sh                  # ~75 MB: NHANES 2011-2014 components + minute-level steps
seeds/download_bigideas.sh                # ~3 GB: BIG IDEAs CGM + E4 HR/IBI/TEMP/EDA (PhysioNet S3 mirror)
COHORT_DIR=synthea_general KEEP_MODULE=none AGES=35-65 POPULATION=200 SEED=43 \
  seeds/generate_cohort.sh                # general-population Synthea cohort for the BIG IDEAs twins
scripts/pipeline.sh                       # uv run twin all: init-db + every load step
uv run twin export-features               # ML feature store -> data/features/*.parquet
uv run twin train-baselines               # glucose forecaster + HbA1c population model -> data/models/
scripts/replay.sh                         # twin API on http://localhost:8765 (docs at /docs)
```

`scripts/pipeline.sh <step>` runs a single step, for example `scripts/pipeline.sh reconcile`.
`scripts/reset.sh` asks for confirmation, then wipes this project's Docker volume and rebuilds
everything. Downloaded data in `data/` is kept. Schema changes are not migrated: rebuild with
`scripts/reset.sh`, since all twin data is regenerated from the sources.

Medication reference data is built from RxNorm by `uv run python seeds/build_medication_seeds.py`
(NLM RxNav API, cached in `data/cache/`). Its outputs are committed.

## Project layout

```
seeds/                    everything the databases are seeded from
  reference/*.csv         vocabularies loaded by init-db: data sources, tags, LOINC codes (with analyte),
                          condition groups, drug classes (ATC), RxNorm medications/products, wearable
                          metrics, device models
  mappings/*.csv          source codes -> standard: SNOMED -> condition group, drug names -> RxNorm,
                          reviewed drug-class overrides
  build_medication_seeds.py  RxNorm/ATC seed builder (RxNav API)
  download_cgmacros.sh, fetch_cgmacros.py, generate_cohort.sh, download_nhanes.sh
scripts/                  running the system: up.sh, pipeline.sh, replay.sh (API), reset.sh
db/init/                  Docker init: creates HAPI's database
src/twin/
  cli.py, config.py       `twin` command and settings
  db/                     async engine/session, init-db (schema.py), view SQL (sql/: report, ml)
  models/                 ORM models, one module per DB schema, plus read-only view tables
  sources/                readers: CGMacros, BIG IDEAs, Synthea (cohort + EHR content), NHANES
  synthetic/              rule-based wearable generator (sleep, SpO2, respiration, stress, HRV)
  analytics/              pure signal processing (CGM fusion)
  fhir/                   async HAPI FHIR client
  pipeline/               load steps: patients, bigideas, ehr (load/copy), sensors, nhanes, fusion, simulate,
                          reconcile, summaries
  ml/                     feature export, glucose forecaster, population HbA1c model
  api/                    FastAPI app: /patients, /twin/{id}, simulations, WebSocket replay
tests/
docs/                     data dictionary, data inventory, pipeline diagram (diagrams/, images/), plans/
data/                     downloads, generated cohort, features, models, reports (gitignored)
```

| Service | URL |
|---|---|
| TimescaleDB / Postgres | `postgresql://twin:…@localhost:${PG_PORT}/twin` |
| HAPI FHIR R4 | http://localhost:8080/fhir |
| Twin API | http://localhost:8765/docs, `/twin/{patient_id}`, `ws://localhost:8765/ws/patients/{patient_id}?speed=60` |

`seeds/generate_cohort.sh` reads `SYNTHEA_DIR` (default `~/testing/synthea`),
`POPULATION` (150), `SEED` (42) and `REFERENCE_DATE` (`20261003`). The same values
always produce the same cohort, because Synthea runs single-threaded with a fixed
reference date. If you change them, the cohort changes and participants are re-matched
on the next `twin all`. `load-ehr` then removes the patients that are no longer linked.

## Pipeline (`twin <step>`, each step idempotent)

| Step | What it does |
|---|---|
| `init-db` | Creates or upgrades the twin schema: the timescaledb extension, tables from the SQLAlchemy models, hypertables with compression, continuous aggregates and report views (recreated). Reference data is upserted from `seeds/reference/*.csv`. |
| `ingest` | Validates every CGMacros file and prints per-participant counts. Writes nothing. |
| `match` | T2D participants (HbA1c ≥ 6.5 %) are matched to living Synthea diabetics: same sex, age within ±5 years at the last encounter, then nearest BMI. Assignment is greedy without replacement, most-constrained participant first. Creates `core.patient`, the `composite-patient` tag and the real baseline labs in `core.observation`. Writes `data/reports/match_report.csv`. |
| `ingest-bigideas` | BIG IDEAs participants as composite twins. Matching: same sex, age 35–65 at the last encounter (women 50–65: the study enrolled only post-menopausal women), same glycaemic group (HbA1c ≥ 5.7 → Synthea prediabetes, else neither), then nearest Synthea HbA1c. Loads Dexcom G6 CGM and E4 heart rate (per minute), inter-beat intervals (every beat), skin temperature and EDA (4 Hz → per-minute mean). Writes `data/reports/bigideas_report.csv`. |
| `load-ehr` | First prunes Synthea patients in FHIR that are no longer linked in `core.patient`: each patient's `$everything` compartment is deleted in one transaction, and shared Organization, Practitioner and Location resources are kept. Then loads hospital and practitioner bundles, followed by the **matched** patients' bundles. Requests are rewritten from `POST` to `PUT Type/<synthea-uuid>`, so FHIR ids equal Synthea ids. |
| `copy-ehr` | Copies the composite twins' Synthea history into the twin DB, tagged `source = synthea` (synthetic): observations (labs, BP, coded answers; only LOINC codes in `ref.observation_code`, with units checked), conditions, medication regimens (RxNorm products mapped to ingredients and ATC drug classes), and encounters. HAPI stays the FHIR system of record. |
| `ingest-nhanes` | NHANES 2011–2014 adults with diabetes (see [NHANES](#nhanes-20112014)): patients, labs, BP, body measures, smoking status, self-reported conditions, prescriptions (RxNorm), and minute-level wrist steps with daily wear minutes. Writes `data/reports/nhanes_report.csv`. |
| `load-sensors` | Devices, plus native CGM, fingerstick and Fitbit readings (one row per minute and metric in `ts.wearable_sample`), are COPYed into the hypertables. Everything is shifted so the 10-day window starts the day after the patient's last encounter. |
| `fuse-cgm` | Fuses each patient's Dexcom and Libre into one 5-min stream, `ts.glucose_fused`. The steps are time alignment, cross-calibration and weighted combination (see [CGM fusion](#cgm-fusion)). Fitted parameters go to `core.cgm_calibration`. Writes `data/reports/cgm_fusion_report.csv`. |
| `simulate-wearables` | **Synthetic.** Sleep stages, SpO₂, respiration, stress and nightly HRV for every composite twin (see [Synthetic wearables](#3-synthetic-wearables)), under a generator device flagged `is_synthetic`; tags the patient `synthetic-sensors`. |
| `reconcile` | Recomputes the GMI tags. Writes the Patient's tags and race/ethnicity, then the real labs (and BMI and LDL derived from them) as the newest Observations, tagged `composite-override`. Writes `data/reports/consistency_report.csv` (HbA1c vs GMI). |
| `summarize` | Writes Device resources, daily CGM Observations (mean 97507-8, time-in-ranges panel 106793-3, CV 104638-2), whole-window GMI 97506-0 and daily mean heart rate 8867-4, and daily steps 55423-8 where a wearable records them. Codes follow the [HL7 CGM IG](https://build.fhir.org/ig/HL7/cgm/). |
| `export-features` | Writes the `ml` feature store to `data/features/*.parquet` with `DATASET_CARD.md` (see [ML and simulation](#ml-and-simulation)). |
| `train-baselines` | Trains the glucose forecaster and the NHANES HbA1c model from the exported features, into `data/models/`. |
| `serve` | FastAPI twin API: `GET /patients?tag=…`, `GET /twin/{id}`, `GET /twin/{id}/timeline`, `POST /twin/{id}/simulate/glucose`, `POST /twin/{id}/simulate/hba1c`, and `WS /ws/patients/{id}?speed=60&kinds=glucose_fused,glucose,activity,medication`. |

## Data model (`twin` database)

Every column of every table and view, with real/synthetic availability per cohort, is in
[docs/data-dictionary.md](docs/data-dictionary.md).

```
ref.data_source 1──* core.patient 1──* core.patient_tag *──1 ref.tag
     (is_synthetic,      │ 1
      access_tier)       ├──* core.observation *──1 ref.observation_code (LOINC, analyte, category)
                         │                     *──1 ref.concept (coded values)
                         ├──* core.condition   *──1 ref.concept *──1 ref.condition_group
                         ├──* core.medication_regimen *──1 ref.medication (RxNorm ingredient)
                         ├──* core.medication_dose    *──1 ref.medication *──1 ref.drug_class
                         │                                  1──* ref.medication_atc / medication_product
                         ├──* core.encounter
                         ├──1 core.cgm_calibration *──2 ref.device_model (reference, secondary)
                         ├──* ts.glucose_fused      (hypertable, derived: fused CGM, 5 min)
                         └──* core.device *──1 ref.device_model
                                  │ 1
                                  ├──* ts.glucose_reading   (hypertable, raw)
                                  ├──* ts.wearable_sample   (hypertable) *──1 ref.wearable_metric
                                  └──* ts.sleep_segment     (stage intervals)
   ref.device_model.is_synthetic marks generator devices: their samples are synthetic
```

Every clinical row (`observation`, `condition`, `medication_regimen`, `medication_dose`,
`encounter`) carries `source_id`, so its origin, and whether it is synthetic, is always known.
Views prefer real values over synthetic ones, and derived values carry an `*_is_synthetic` flag.

Schemas: `ref` (vocabularies), `core` (patient master and patient-owned data),
`ts` (hypertables and continuous aggregates), `report` (derived views), `ml` (feature views).

The schema is defined in code:
- **Tables:** the SQLAlchemy 2 ORM models in [src/twin/models/](src/twin/models/), one module per database schema:
  - `base.py`: the declarative base and enums
  - `reference.py`: `ref.*` vocabularies
  - `patient.py`: `core.*`, the patient master and patient-owned data
  - `sensors.py`: `ts.*` readings
- **TimescaleDB setup:** [src/twin/db/schema.py](src/twin/db/schema.py).
- **Reference data:** seeded from [seeds/reference/](seeds/reference/).
- **Views and continuous aggregates:** SQL files in [src/twin/db/sql/](src/twin/db/sql/), with typed read-only `Table` definitions in [src/twin/models/views.py](src/twin/models/views.py).
- **Driver:** all database access is async (`AsyncSession` on asyncpg). Sensor hypertables are bulk-loaded with COPY on the session's own connection, inside its transaction.
- **Docker init:** the only init script, [db/init/00-create-dbs.sh](db/init/00-create-dbs.sh), creates HAPI's separate `hapi` database.

Normalisation rules:
- **One patient table.** `core.patient` holds everything that depends only on the patient: name, MRN, birth date, sex, race/ethnicity, address, source linkage, time offset and match audit. For composite twins `patient_id` is the Synthea UUID, which is also the FHIR `Patient.id`. Sources without names or exact birth dates leave those empty, or store an imputed mid-year birth date flagged `birth_date_imputed`.
- **Tags are many-to-many** (`ref.tag` ↔ `core.patient_tag`) and are mirrored to FHIR `Patient.meta.tag`.
- **Readings key on `device_id`, not `patient_id`.** A device belongs to exactly one patient, so a patient id on every reading would be a transitive dependency. Specimen and sensor kind come from `ref.device_model`.
- **No derived columns.** Age, BMI, non-HDL, VLDL, LDL (Friedewald, NULL when TG > 400), eGFR (CKD-EPI 2021), HOMA-IR, cohort, TIR, CV, GMI and the sensor window are all computed in `report.*` views and continuous aggregates. The source's derived bio columns, with their 800/400 error sentinels, are dropped at ingest.
- **Observations are long-form** (`patient, LOINC, time, value_num | value_concept`) in UCUM units. Codes that measure the same thing share an `analyte` (for example, creatinine in blood 38483-4 and in serum 2160-0).
- **Wearables are long-form** (`device, metric, time, value`), because devices export different metrics.
- **Medications are ingredient-level RxNorm.** Drug classes come from ATC (via the NLM RxNav API, `seeds/build_medication_seeds.py`), with reviewed overrides in `seeds/mappings/`.
- **One time offset.** All timestamps are stored in *twin time*, and `patient.time_offset` is the only record of the shift (original time = `time − time_offset`).

Useful queries:

```sql
SELECT * FROM report.patient_summary;            -- patients + age + tags
SELECT * FROM report.patient_baseline;           -- latest values + BMI/LDL/eGFR/HOMA-IR/cohort, synthetic flags
SELECT * FROM report.observation_latest;         -- latest value per analyte, with source
SELECT * FROM report.patient_conditions;         -- conditions rolled up to clinical groups
SELECT * FROM report.medication_regimen;         -- regimens with ingredient and drug class
SELECT * FROM report.activity_daily;             -- steps, HR, METs, SpO2, stress, skin temp, EDA per day (+ synthetic_metrics)
SELECT * FROM report.sleep_nightly;              -- sleep stages, efficiency per night
SELECT * FROM report.spo2_nightly;               -- SpO2 while asleep: mean, nadir, T90, ODI
SELECT * FROM report.hrv_nightly;                -- RMSSD: real (inter-beat intervals) or synthetic
SELECT * FROM report.consistency;                -- HbA1c vs GMI of the fused CGM
SELECT * FROM report.cgm_daily WHERE coverage_pct >= 70;   -- fused stream
SELECT * FROM report.cgm_device_daily;           -- each CGM separately (raw), for comparison
SELECT * FROM core.cgm_calibration;              -- fusion parameters per patient
```

## CGM fusion

Every patient wore a Dexcom G6 Pro (every 5 min) and a FreeStyle Libre Pro (every 15 min)
at the same time. The two sensors disagree a lot: over 13,365 time-matched pairs, Libre
reads about 29 mg/dL lower on average, and only 33 % of pairs agree within 15 mg/dL or
15 %. So `fuse-cgm` builds one calibrated stream
([src/twin/analytics/cgm_fusion.py](src/twin/analytics/cgm_fusion.py), method `cgm-fusion-1`):

1. **Time alignment.** The lag between the sensors is found by cross-correlation over ±120 min.
   - A lag of 20 min or less is sensor delay. Libre leads Dexcom by 2–13 min, so the later sensor is shifted onto the earlier one.
   - A larger lag is a device clock error. The device whose post-meal glucose peak sits closer to the cohort's typical time-to-peak (73.5 min) keeps its clock.
   - Subject 030's Libre clock was 57 min off and has been corrected.
2. **Cross-calibration.** Libre is mapped onto the Dexcom scale with Deming regression, which allows for errors in both sensors. It is fitted per patient only where neither sensor is in its first 24 h: slopes range from 0.74 to 1.41, so one global correction would not work.
3. **Combination** on a 5-min grid, weighting each sensor by the inverse of its error variance.
   - The weights are equal, except for a sensor in its first 24 h. Its weight is reduced by that patient's measured warm-up factor, which ranges from 1 to 4.6. Day-1 disagreement is 12 % against about 7 % on later days.
   - Gaps in one sensor are filled from the other.
   - Values at the 40/400 mg/dL reporting limits are replaced by the other sensor where it has a valid value; otherwise they are kept and flagged `censored`.

**Why the Dexcom scale, and not the fingersticks?** All CGMacros fingersticks were taken on warm-up day 1. They scatter widely (SD 34 mg/dL against the sensors), and anchoring to them made the result worse on both checks below. Lab HbA1c, measured independently, agrees with the Dexcom scale instead.

Validation against lab HbA1c, which is never used in fitting, via GMI:

| Stream | Mean \|GMI − HbA1c\| | Patients within 0.5 |
|---|---|---|
| Dexcom alone | 0.28 | 13/14 |
| Libre alone (raw) | 0.69 | 4/14 |
| **Fused** | **0.30** | **12/14** |

The fused stream matches Dexcom's agreement with HbA1c. Its gains:
- **Coverage:** 9.4 % more five-minute slots than Dexcom alone, and up to 31 % more for one patient.
- **Reliability:** no single-sensor dropouts or reporting-limit artefacts, and one clock error fixed.

All CGM metrics now use the fused stream: daily TIR, CV and GMI views, the HbA1c consistency tags, and the FHIR summaries. The FHIR summaries carry a `method` naming both devices instead of a single `device` reference. The raw per-device data stays in `ts.glucose_reading` and `report.cgm_device_*`.

## NHANES 2011–2014

`seeds/download_nhanes.sh` fetches 17 NHANES components per cycle from CDC:
- demographics and diabetes;
- labs: HbA1c, fasting glucose and insulin, biochemistry, lipids, urine albumin/creatinine;
- exams: blood pressure and body measures;
- questionnaires: blood pressure and cholesterol, medical conditions, kidney, smoking;
- prescription medications.

It also fetches minute-level wrist steps (the stepcount self-supervised model) and wear
predictions from [PhysioNet](https://physionet.org/content/minute-level-step-count-nhanes/).

- **Cohort.** Adults (20 or older) with diagnosed diabetes, HbA1c ≥ 6.5 %, fasting glucose ≥ 126 mg/dL, or taking insulin or diabetes pills. Probable type 1 (diagnosed before 30, on insulin, no pills) is excluded. This gives 1,879 people: 1,382 diagnosed and 497 lab-detected (tagged `undiagnosed-diabetes`).
- **Dates.** NHANES publishes none. Each person gets a nominal exam date in the second year of their cycle, February or August by exam period. Steps start on the exam day.
- **Labs** keep NHANES units, which already match the UCUM unit of each LOINC code. Blood pressure is the protocol mean of the available readings; an inaudible diastolic (0) is excluded. Missing values stay missing: SAS XPORT's encoded zero is restored and NaN is never turned into 0.
- **Conditions** are self-reported and coded to SNOMED, which was verified against the HL7 terminology server: hypertension, hyperlipidaemia, CHF, CHD, angina, MI, stroke, weak or failing kidneys, and diabetic retinopathy. T2D onset comes from the age at diagnosis.
- **Medications** are current prescriptions at the exam. They start `RXDDAYS` before the exam when reported. Generic names are mapped to RxNorm ingredients through `seeds/mappings/medication_names.csv`, which is resolved by the RxNav API.
- **Steps.** 1,607 people have step data and 1,551 have at least 4 valid days (≥ 10 h worn). Stored are the minutes worn with steps > 0, plus a daily `wear_minutes` value. That averages about 6,400 steps per valid day.

## How the synthetic data is created

No open dataset has continuous sensors **and** an EHR history **and** sleep/SpO₂ for the same
people. So each composite twin is assembled from three layers. Only the first is real.

| Layer | Source | Real or synthetic |
|---|---|---|
| 1. Sensors and baseline labs | CGMacros or BIG IDEAs participant | **real** |
| 2. EHR history: conditions, medications, encounters, years of labs and vitals | a matched Synthea patient | synthetic |
| 3. Sleep, SpO₂, respiration, stress, nightly HRV | the twin's rule-based generator, driven by layers 1 and 2 | synthetic |

**Never synthesised:** glucose (raw or fused), heart rate, inter-beat intervals, skin
temperature, EDA, METs and the baseline labs. NHANES patients are entirely real.

### 1. Synthea EHR cohorts

[Synthea](https://github.com/synthetichealth/synthea) simulates whole lives as state machines
of disease modules: diabetes, hypertension, CKD, medications, encounters, labs and so on. It
runs on the host (`~/testing/synthea`, unmodified upstream) through
[seeds/generate_cohort.sh](seeds/generate_cohort.sh). Two cohorts are generated:

| Cohort | For | Command | Settings |
|---|---|---|---|
| `data/synthea/` | CGMacros T2D twins | `seeds/generate_cohort.sh` | 150 people, ages 25–75, seed 42, keep module `keep_diabetes.json` (only people with SNOMED 44054006, T2D) |
| `data/synthea_general/` | BIG IDEAs twins | `COHORT_DIR=synthea_general KEEP_MODULE=none AGES=35-65 POPULATION=200 SEED=43 seeds/generate_cohort.sh` | 200 people, ages 35–65, seed 43, general population (prediabetes and normoglycaemia occur naturally) |

Both cohorts are reproducible:
- The person seed and clinician seed (`-s`, `-cs`) are fixed.
- The reference date is fixed (`-r 20261003`, "today" in the EHR timeline).
- Synthea runs single-threaded (`--generate.thread_pool_size=1`). With threads, it creates different people each run.

The output is FHIR R4 transaction bundles, plus hospital and practitioner bundles. CSV export is off.

### 2. Composite matching and the time shift

Each real participant is paired with one Synthea patient. The pairing is greedy, without
replacement, and handles the participant with the fewest candidates first:

| | CGMacros (`twin match`) | BIG IDEAs (`twin ingest-bigideas`) |
|---|---|---|
| Participants | HbA1c ≥ 6.5 % (14 of 45) | all 16 |
| Candidate pool | living Synthea diabetics | Synthea general cohort |
| Hard constraints | same sex; age within ±5 years at the last encounter | same sex; age 35–65 at the last encounter (women 50–65: the study enrolled post-menopausal women); same glycaemic group (HbA1c ≥ 5.7 → Synthea prediabetes without T2D, otherwise neither) |
| Ranking | nearest latest BMI | nearest latest Synthea HbA1c, then a stable hash tie-break |
| Audit | `match_age_diff`, `match_bmi_diff`, `data/reports/match_report.csv` | `data/reports/bigideas_report.csv` (BIG IDEAs has no age or BMI) |

The twin takes these fields from the Synthea patient: `patient_id` (the Synthea UUID, which is also the FHIR id), name, MRN, birth date and address. It takes sex (equal by construction) and race/ethnicity from the real participant, when the source reports it.

**Time shift.** The sensor window is moved so it starts on the day after the Synthea patient's last
encounter. The history then leads up to the sensor days.
- The shift is a whole number of days, stored once as `core.patient.time_offset`. It keeps wall-clock time, so a 07:30 breakfast stays at 07:30.
- Times that fall into a DST gap or overlap on the target date are dropped rather than duplicated.
- The real baseline labs are dated at their real clock time on the shifted collection day.

**Loading the EHR.**
- `load-ehr` sends only the matched patients' bundles to HAPI FHIR. It rewrites every request to `PUT Type/<synthea-uuid>`, which makes it idempotent.
- `copy-ehr` copies the history into `core.*` with `source = synthea`. Only LOINC codes in the vocabulary are copied, with units checked. Medication products are mapped to RxNorm ingredients and ATC classes.
- `reconcile` writes the real labs to FHIR as the newest Observations, tagged `composite-override`, so "latest HbA1c" is always the real value.
- Synthetic history is never rewritten: an implausible Synthea HbA1c from years ago stays visible as synthetic.

### 3. Synthetic wearables

`twin simulate-wearables` runs [src/twin/synthetic/wearables.py](src/twin/synthetic/wearables.py),
version `twin-wearables-1`. It fills the Garmin-like channels that no real device recorded.

**Inputs.** Each patient gets a `Profile` built from the patient's own record:
- age, sex and BMI;
- sleep apnoea and COPD, from the conditions;
- dysglycaemia: T2D or prediabetes;
- whether real inter-beat intervals exist.

The generator also reads the patient's **real per-minute heart rate**, and real activity, which marks exercise minutes (METs ≥ 3 or intensity level ≥ 2). It runs only inside the real recording window.

**Randomness.** There is one random stream per patient, seeded with `sha256("twin-wearables-1/<patient_id>")`. Re-running gives identical data, and a different patient gets different data.

The parameters are rounded, literature-typical values. They were not fitted to data.

| Channel | Cadence | Rule |
|---|---|---|
| Sleep duration | per night | hours ~ N(7.2 − 0.015·(age − 40) − 0.3·apnoea, 0.6), clipped to 4.5–9.5 |
| Bedtime | per night | Candidates are 15-minute steps from 21:00 to 01:30. The generator picks the one where the mean of the **real** HR over the sleep window is lowest, if ≥ 50 % of that window has HR. Otherwise it uses 22:45 − max(age − 40, 0) min + N(0, 40) min. |
| Sleep stages | per minute → `ts.sleep_segment` | Cycles of N(90, 10) min, clipped to 70–110. The deep share is clip(0.35 − 0.004·(age − 20), 0.12, 0.35), reduced by 25 % per cycle. The REM share is 0.25·min(1, 0.4 + 0.3·cycle), growing through the night; the rest is light. Sleep onset takes 5–20 min (awake). Awakenings ~ Poisson(1.5 + 2.5·apnoea + 0.02·max(age − 40, 0)), each 2–8 min. |
| SpO₂ baseline | – | Awake baseline: 97.4 − 0.04·max(age − 40, 0) − 0.06·max(BMI − 30, 0) − 2.5·COPD + N(0, 0.4). Asleep: 0.8 lower, and a further 0.3 lower in REM, with noise of 0.5. |
| SpO₂ desaturations | per minute asleep | The oxygen desaturation index (ODI) is 2/h without apnoea. With apnoea it is 12, 22 or 35 per hour, by BMI (< 30, 30–35, ≥ 35). Events are placed in proportion to stage weights: REM 1.5, light 1.0, deep 0.6. Each event lasts 3 minutes, with depth U(3, 6) points (+2 when severe) scaled by (0.6, 1.0, 0.4). An event pulls SpO₂ *to* a nadir, so overlapping events do not add up. There are at most asleep_minutes / 3 events. Values are rounded and clipped to 70–100. |
| SpO₂ awake | every 15 min | Spot checks: awake baseline + N(0, 0.6) |
| Respiration | every worn minute | Awake: 15.5 + 0.06·(HR − resting HR) + N(0, 1). Asleep: light 14.2, deep 13.2, REM 15.0, plus N(0, 0.6), and 2.5 lower during a desaturation. Clipped to 8–30. |
| Stress | every 3 min awake | 12 + 2·(HR − resting HR) + N(0, 6), clipped to 0–99. Blank while exercising or asleep. Resting HR is the 5th percentile of awake HR. |
| Nightly HRV (RMSSD) | one value per night, at wake time | ln RMSSD = ln 45 − 0.017·(age − 40) − 0.12·dysglycaemia − 0.10·apnoea + a per-patient offset N(0, 0.15) + a nightly N(0, 0.12). **Only** for patients without real inter-beat intervals: the 16 BIG IDEAs twins keep their real HRV, computed from E4 beats. |

**Checks** ([tests/test_wearable_generator.py](tests/test_wearable_generator.py)):
- determinism per patient;
- value ranges;
- sleep falls where real HR is lowest;
- apnoea lowers sleeping SpO₂ (mean more than 2 points lower, over 5 % of minutes below 90 %);
- no HRV is generated when real beats exist.

On the current twins: apnoea patients have ODI 9.3/h against 2.0/h; synthetic RMSSD is about 33 ms against about 42 ms real.

The generator **never overwrites real data** and is **not linked to glucose**, so no
sleep-to-glucose effect can be "discovered" in it.

### Provenance: how to tell real from synthetic

| Where | Marker |
|---|---|
| Any EHR row | `source_id` → `ref.data_source.is_synthetic` (`synthea`, `twin_generator` = true) |
| Sensor samples | `core.device` → `ref.device_model.is_synthetic` (the "Twin generator" model) |
| Patient | tags `composite-patient`, `synthetic-sensors` (also FHIR `Patient.meta.tag`) |
| Derived values | `bmi_is_synthetic`, `ldl_is_synthetic`, `egfr_is_synthetic`, `homa_ir_is_synthetic`, `synthetic_analytes` |
| Views and features | `is_synthetic` (nightly views, regimens, latest observations), `synthetic_metrics` / `synthetic_channels` |
| FHIR | `composite-override` on real labs; `synthetic-sensors` on generated summaries |
| API | `GET /twin/{id}` → `provenance.synthetic_analytes`, `provenance.synthetic_sensor_channels` |

**Use synthetic data for display, alerts, replay and pipeline testing. Do not use it to train
or validate models:** a model would learn the rules written above, not physiology.

## ML and simulation

`twin export-features` writes the `ml` schema views to Parquet, with a dataset card:

| Table | Grain | Contents |
|---|---|---|
| `patient_static` | patient | demographics, baseline values with synthetic flags, condition groups, current medication classes, data availability, split |
| `patient_day` | patient × day | fused CGM metrics, steps, wear, heart rate, METs, number of glucose-lowering classes, insulin units |
| `series_5min` | patient × 5 min | fused glucose (with source and censored flags), steps, heart rate, METs, insulin and oral doses, labels `glucose_t30` and `glucose_t60` |

Splits are by patient: a hash of `patient_id`, 70/15/15, stable across rebuilds.

`twin train-baselines`:
- **Glucose forecaster** (`ml/forecast.py`). Gradient-boosted trees predict the glucose change 30 and 60 min ahead from:
  - recent glucose, its lags and rate of change;
  - heart rate and METs;
  - steps and insulin, when the cohort has them;
  - time of day.

  It is evaluated with patient-grouped 5-fold CV on the 14 composite patients:

  | horizon | RMSE | persistence RMSE | MARD |
  |---|---|---|---|
  | +30 min | **16.2 mg/dL** | 21.3 | 6.8 % |
  | +60 min | **30.2 mg/dL** | 35.3 | 13.1 % |

- **Population HbA1c model** (`ml/population.py`). HbA1c in NHANES (n = 1,774) is predicted from demographics, BMI, BP, eGFR, lipids, diabetes duration, daily steps, medication classes and conditions, with 5-fold CV. It is **weak: RMSE 1.73 % against 1.78 % for the mean, R² 0.05.** A single cross-sectional HbA1c is mostly unexplained by these variables. There are also adjusted associations (OLS, n = 1,392, bootstrap 95 % intervals), saved to `data/models/hba1c_associations.csv`:
  - **Confounding by indication:** insulin +1.34 % [1.08, 1.59] and sulfonylureas +0.63 % go with *higher* HbA1c, because those drugs are given to people whose diabetes is harder to control.
  - **Steps:** no detectable association, −0.006 % per 1,000 steps/day [−0.03, +0.02].

The twin API (`twin serve`, docs at `/docs`):
- **`GET /twin/{id}`** returns the patient, provenance (what is synthetic), baseline (with derived values and flags), latest observations, conditions, medications, CGM window, consistency, daily CGM and activity, and recent encounters.
- **`GET /twin/{id}/timeline?start&end`** returns the 5-minute series.
- **`POST /twin/{id}/simulate/glucose`** takes `{extra_met_minutes_30, heart_rate_delta, insulin_fast_units}` and returns the +30/+60 forecast, baseline vs scenario.
- **`POST /twin/{id}/simulate/hba1c`** takes `{steps_per_day, bmi, add_drug_classes, remove_drug_classes}` and returns the population-model HbA1c, baseline vs scenario.

**Scenarios are model-based what-ifs, not causal predictions.** Two examples from the current models:
- **Activity:** the forecaster predicts *higher* glucose 60 min after extra activity. In CGMacros, activity tends to follow meals, so the model learned that association, not an effect of exercise.
- **SGLT2 inhibitor:** adding one raises the predicted HbA1c (+0.1 %), although SGLT2 inhibitors lower HbA1c. This is confounding by indication.

So the simulation endpoints demonstrate the twin's interface. They are not a basis for treatment or lifestyle advice. Causal what-ifs need either within-person data where the intervention varies (ShanghaiT2DM doses, trials) or explicit causal methods, and meal data for glucose.

## Source data notes

- CGMacros interpolates both CGMs linearly onto a 1-minute grid. Ingest keeps only the native readings: Dexcom every 5 min (about 2,860 per participant) and Libre every 15 min (about 1,000). These are recovered as the vertices of the piecewise-linear signal, plus grid points inside straight runs.
- Fitbit exports differ between participants. Most have METs (stored ÷10, as exported ×10). Others have a 0–3 intensity level instead, stored as `activity_level`. Steps exist for only one non-T2D participant and are not stored. CGMacros has no sleep data.
- Timestamps are treated as `America/Chicago` local time.

## Honest limitations

- Every twin is a **composite patient: real CGM/wearable data + synthetic EHR history**. Tags in both stores make this visible.
- Synthea's historic HbA1c values are sometimes implausible (about 3.1 % for 4 of the 14 matched patients). History is not rewritten; the real lab is the newest value.
- Synthea rarely generates BMI ≥ 40, so participants with severe obesity are matched at a larger BMI gap (recorded in `match_bmi_diff`). The real BMI then replaces it as the latest value.
- Meals are out of scope for now. CGMacros meal times are read from the source file only to time-check the CGM clocks during fusion; nothing about meals is stored.
- One patient (047) has HbA1c and GMI more than 1.0 point apart. This comes from the real data, and the patient is tagged `gmi-inconsistent`. On the fused stream, 014 sits just past the 0.5 line (0.51) and is tagged `gmi-warn`.
- CGMacros has about 10 days of CGM per person. Consensus CGM metrics assume at least 14 days with at least 70 % wear, so GMI and TIR here are indicative.

## Development

```bash
uv sync
uv run pytest            # SQL view tests run when the twin DB is reachable, else skip
```

`DATABASE_URL` can be a plain `postgresql://` URL; the asyncpg driver is selected
automatically. The session time zone is set to `America/Chicago`.
