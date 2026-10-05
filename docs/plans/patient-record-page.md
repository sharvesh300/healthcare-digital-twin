# Patient record: overview and detail pages (plan, 2026-10-05)

**Status: built (2026-10-05).** Two things changed from the plan:
- The API is split into `twin.record.store` (loads a patient's rows) and `twin.record.assemble`
  (pure, tested through a fake store), with the routes in `twin.api.record`.
- Visit paging in the UI grows the list ("Show more", `?limit=`) instead of handing out cursors.
  The API still pages by cursor.

One **Record** area replaces today's **History** and **Record** tabs. It has an overview page and
detail pages for every kind of entry: a test or vital, a diagnosis, a medication, and a visit. A
record holds many diagnoses, each possibly recurring, and many results for each test over the
years. The overview summarises them, and every summary row opens a detail page with the full
history. Every endpoint and page is built so new entry types can follow the same pattern.

## Why

- **History duplicates Live.** Its 24 h sensor charts repeat the Live tab, whose replay now opens
  any moment. Only the daily CGM table is unique; it moves into Record.
- **Today's Record misses most of the record.**
  - It shows only conditions that roll up to a clinical group: 1 of 33 for BIG IDEAs 001.
  - It shows only the latest lab value, not the history behind it.
  - It shows no visits.
  - The medication list is capped at 14 and has no dosage form.
- **The data really is multi-valued** (whole twin DB):

  | Kind | Repetition |
  |---|---|
  | Tests | up to 104 results for one test in one patient (1.2 on average) |
  | Diagnoses | 213 patient–diagnosis pairs recur; one recurs 44 times (e.g. bronchitis episodes) |
  | Medications | the same ingredient is prescribed again in later episodes; dose and product can change |
  | Visits | BIG IDEAs 001 alone has 46 (41 ambulatory, 5 inpatient); visits can overlap (19 overlapping pairs) |

- **Entries can be tied to their visit exactly.**
  - All 8,034 Synthea observations and 307 of 311 prescriptions fall inside a visit.
  - Each FHIR resource carries `encounter.reference`, but the parser drops it today. Storing it
    avoids matching by time, which overlapping visits would make ambiguous.
  - Each visit's type ("General examination", "Emergency room admission") and reason are in the
    bundle too, and are also dropped.
- **Dosage is sparse at the source.**
  - Only 44 of 311 Synthea regimens have `dose_value`.
  - The prescribed product (`Warfarin Sodium 5 MG Oral Tablet`) is dropped at load time. Keeping it
    gives strength and form for every prescription.

## Information architecture

```
/patients/[id]/record                         Overview: summary tiles, sections, "View all" links
/patients/[id]/record/tests                   All tests and vitals, by panel (filter: panel, out of range)
/patients/[id]/record/tests/[measure]         One test or vital: every result, chart, visits, related
/patients/[id]/record/conditions              All diagnoses and findings (filter: active, kind, group)
/patients/[id]/record/conditions/[conceptId]  One diagnosis: every episode, visits, related meds and tests
/patients/[id]/record/medications             All prescriptions (filter: active, class, glucose-lowering)
/patients/[id]/record/medications/[rxcui]     One medication: every prescription episode, dose changes
/patients/[id]/record/visits                  All visits, paginated (filter: year, class)
/patients/[id]/record/visits/[encounterId]    One visit: everything recorded at it
/patients/[id]/history                        → redirect to /record (old links)
```

- **Identifiers are stable:**
  - `measure`: an analyte key such as `hba1c` or `ldl`, or a composite such as `blood_pressure`,
    which covers SBP and DBP;
  - `conceptId`: the `ref.concept` id;
  - `rxcui`: the RxNorm ingredient;
  - `encounterId`: the visit UUID.
- **Every entry links to the others.** A test result links to its visit, a visit to its diagnoses,
  a diagnosis to its medications, and so on. Any page reaches any related page in one click.
- **Breadcrumbs** read `Record / Tests / LDL cholesterol`. The patient tabs become **Live ·
  Record · Predict**.

## Data model changes (normalised; nothing derived is stored)

| Change | Why |
|---|---|
| `core.medication_regimen.product_rxcui` (nullable, composite FK → `ref.medication_product`) | Show strength and form on every prescription |
| `encounter_id` (nullable FK → `core.encounter`, `ON DELETE SET NULL`) on `core.observation`, `core.condition` and `core.medication_regimen` | Exact result → visit, diagnosis → visit and prescription → visit links |
| `core.encounter.type_concept_id`, `reason_concept_id` (nullable FK → `ref.concept`) | Visits read "General examination · for Hypertension", not just "ambulatory" |

- Apply the columns through the existing `ALTER … ADD COLUMN IF NOT EXISTS` list in
  `twin/db/schema.py`. Index `(patient_id, encounter_id)`.
- **Parser** (`sources/synthea_ehr.py`): keep `encounter.reference` on observations, conditions and
  medication requests. Keep `Encounter.type[0]` and `reasonCode[0]`.
- **Loader** (`pipeline/ehr.py`, `copy-ehr`):
  - insert encounters first, then the rows that reference them;
  - set `product_rxcui`.

  It already replaces each twin's Synthea rows, so `uv run twin copy-ehr` backfills locally from
  the bundles on disk, with no network. Rows from CGMacros and BIG IDEAs keep
  `encounter_id = NULL`; the UI labels them "Study visit".
- **Views** (`db/sql/report_views.sql`):
  - `report.medication_regimen` adds `product`, `drug_class_display`, `encounter_id`;
  - new `report.condition_episode`: one row per episode, with display, semantic kind (from the
    `(disorder)` / `(finding)` / `(situation)` tag, stripped), group and encounter;
  - new `report.observation_result`: every result with analyte, display, unit, value or coded text,
    source, synthetic flag and encounter. It feeds both the overview and the detail pages.
- **Measures and reference ranges** live in one module, `twin/clinical/measures.py`. It maps each
  measure to its analytes, panel, display name and adult reference range, so High/Low flags are
  computed in one place for every endpoint.

## API

New module `src/twin/api/record.py`, router prefix `/patients/{patient_id}/record`, mounted in
`twin.api.replay:app`.

- **Conventions:**
  - every endpoint returns 404 for an unknown patient or entry;
  - times are in the clinic zone;
  - every entry carries `source` and `is_synthetic`;
  - lists of unbounded length take `limit` and an opaque `cursor` and return `next_cursor`;
  - every entry has an `href`-ready id and a `links` object for its related entries.

### Overview: `GET /record`

Bounded, for one page load. It returns counts and the latest items, never full histories.

```jsonc
{
  "patient": { "patient_id", "display_name", "mrn", "sex", "birth_date", "age", "race_ethnicity",
               "address_city", "address_state", "source", "source_subject_id", "tags" },
  "provenance": { "composite": true, "note": "…" },
  "summary": {
    "medications_active": 2, "glucose_lowering_active": 0, "diagnoses_active": 3,
    "last_visit": { "encounter_id", "class", "type", "start" },
    "headline": [ /* HbA1c, BP, BMI, LDL, eGFR: measure cards, shape below */ ]
  },
  "medications": { "total": 14, "active": [ MedicationSummary… ], "recent_past": [ … up to 5 ] },
  "conditions":  { "total": 21, "items": [ ConditionSummary… active first, then the 5 most recently resolved ] },
  "tests":       { "total": 22, "panels": [ { "panel": "lipids", "display": "Lipids",
                   "measures": [ MeasureSummary… ] } ] },
  "visits":      { "total": 46, "recent": [ VisitSummary… up to 8 ] },
  "cgm":         { "window", "consistency", "daily" }
}
```

The summary shapes are shared by the overview and the list endpoints:

- `MeasureSummary`:
  - `measure`, `display`, `panel`, `unit`, `range`;
  - `count`: how many results;
  - `latest` (`value` or `text`, `at`, `flag`, `encounter_id`, `is_synthetic`);
  - `previous` (`value`, `at`);
  - `spark`: the last 12 values, for the sparkline.
- `ConditionSummary`:
  - `concept_id`, `display`, `kind` (`diagnosis` / `finding`), `group`, `group_display`;
  - `active`, `episodes`, `first_onset`;
  - `current` (onset and abatement of the latest episode).
- `MedicationSummary`:
  - `rxcui`, `medication`, `product`, `drug_class_display`, `glucose_lowering`, `active`;
  - `dosage` (`dose_value`, `dose_unit`, `times_per_day`, `as_needed`);
  - `started_at`, `ended_at`;
  - `episodes`: how many times it was prescribed;
  - `single_day`: true when given during one visit only.
- `VisitSummary`:
  - `encounter_id`, `class`, `type`, `reason`, `start`, `end`, `duration_h`;
  - `counts` (`tests`, `diagnoses`, `medications`).

### Lists

| Endpoint | Query | Returns |
|---|---|---|
| `GET /record/tests` | `panel`, `flag=out_of_range` | `{ panels: [{ panel, measures: MeasureSummary[] }] }` |
| `GET /record/conditions` | `active`, `kind`, `group` | `{ items: ConditionSummary[] }` |
| `GET /record/medications` | `active`, `glucose_lowering`, `drug_class` | `{ items: MedicationSummary[], single_day: MedicationSummary[] }` |
| `GET /record/visits` | `year`, `class`, `limit`, `cursor` | `{ total, items: VisitSummary[], next_cursor, years: [{year, count}] }` |

### Details

- **`GET /record/tests/{measure}`**
  - Returns `measure`, `display`, `panel`, `unit`, `range` and `analytes` (`["sbp", "dbp"]` for
    BP).
  - `stats`: `count`, `first`, `latest`, `min`, `max`, `mean`, and `out_of_range` (the count).
  - `results`: every result, oldest first, each with `at`, `values` (`{ "sbp": 128, "dbp": 82 }`)
    or `text`, `flag`, `source`, `is_synthetic` and `encounter` (`{ encounter_id, class, type }`).
  - `related`: other measures in the panel, and medications that affect it (HbA1c ↔
    glucose-lowering, LDL ↔ statins, BP ↔ antihypertensives), from the drug-class map.
  - Results are complete. The largest series is 104 results, so this endpoint needs no
    pagination.
- **`GET /record/conditions/{concept_id}`**
  - `concept`: `code`, `system`, `display`, `kind`, `group`.
  - `episodes`: every episode, with `onset_at`, `abated_at`, `duration_days`, `active` and
    `encounter`.
  - `related`: medications prescribed at those visits; for a known group, the tests that track it
    (for example diabetes → HbA1c and glucose, and CKD → eGFR and UACR).
- **`GET /record/medications/{rxcui}`**
  - `medication`: `name`, `drug_class_display` and `glucose_lowering`.
  - `episodes`: every prescription, with `product`, `dosage`, `started_at`, `ended_at`,
    `as_needed` and `encounter`.
  - `dose_changes`: when consecutive episodes differ in product or dose. This is derived in the
    API, not stored.
  - `related`: diagnoses recorded at the prescribing visits, and the measures this class affects,
    with their results while it was taken.
- **`GET /record/visits/{encounter_id}`**
  - `visit`: `class`, `type`, `reason`, `start`, `end` and `duration_h`.
  - `tests`: results recorded at the visit, grouped by panel, with flags.
  - `diagnoses`: those recorded at the visit (onset) and those resolved there.
  - `medications`: prescriptions started at the visit, and any it stopped.
  - `previous` and `next`: the neighbouring visits, to step through them.

`/twin/{id}` is unchanged for API and FHIR consumers. The UI stops calling it.

## UI

### Shared building blocks (`components/record/`)

Every detail page is the same template filled differently. Adding a new entry type, such as
immunisations, means writing one endpoint and one page from these parts:

| Component | Used for |
|---|---|
| `RecordShell` (`app/patients/[id]/record/layout.tsx`) | Breadcrumbs, the section's back link, and the page title slot |
| `DetailHeader` | Title, status chip, kind, "Synthetic" badge, and 3–4 stat tiles |
| `EntryTable` | A sortable table of every occurrence (results, episodes, prescriptions, visits). Each row links to its visit. Rows become two-line items at 375 px |
| `MeasureChart` | The existing `TimeSeriesChart`, extended with a shaded reference band, dots per result, multi-series (SBP and DBP), and a click on a result that opens its visit |
| `EpisodeTimeline` | Horizontal bars over years: diagnosis episodes, prescription episodes, and later a medication Gantt |
| `RelatedPanel` | A side card of links to related tests, diagnoses, medications and visits |
| `SummaryRow`s | `MeasureRow`, `ConditionRow`, `MedicationRow`, `VisitRow`, each with a chevron to its detail page. The overview and the list pages use the same rows |
| `FilterBar` | Segmented filters and chips that sync to the URL query (`?panel=lipids&flag=out_of_range`), so filtered views can be shared |

### Overview (`/record`)

```
┌ tabs: Live · Record · Predict ─────────────────────────────────────────────────────────┐
│ ⓘ Composite twin: sensors and baseline labs real; EHR history synthetic.               │
│ [Active meds 2] [Diagnoses 3 active] [HbA1c 6.6 % High] [BP 128/82] [Last visit Sep 10]│
│ [Medications] [Conditions] [Tests and vitals] [Visits] [Glucose]   ← sticky section nav │
├ MEDICATIONS · 2 active ──────────────────────────────────────── View all 14 → ─────────┤
│ Warfarin  Warfarin Sodium 5 MG Oral Tablet  Vitamin K antag.  5 mg · daily  since 2019 ›│
├ CONDITIONS · 3 active ──────────────── View all 21 → ┬ SOCIAL HISTORY ─────────────────┤
│ Aortic valve regurgitation        Active since 1963 ›│ Unemployed      since Aug 2026 ›│
│ Acute bronchitis   ×3 episodes   last resolved 2024 ›│ Stress ×3       resolved       ›│
├ TESTS AND VITALS · 22 tests ─────────── [All | Out of range] ── View all → ─────────────┤
│ Lipids    LDL  131 mg/dL  High  Aug 2024  −6  4 results  ▆▅▅▄                          ›│
│ Vitals    BP   128/82     Normal Aug 2026      12 results ▃▄▃▃▄▃                        ›│
├ VISITS · 46 ──────────────────── View all → ┬ GLUCOSE (CGM) ───────────────────────────┤
│ Sep 10 2026  General examination  3 tests ›│ Sep 11–20 · mean 118 · GMI 6.1 % · daily ▾│
│ Dec 10 2019  Inpatient · 2 days   9 tests ›│ Replay these days in Live ↗               │
└─────────────────────────────────────────────┴──────────────────────────────────────────┘
```

### Detail page template

```
Record / Tests / LDL cholesterol                                    ← breadcrumbs, back link
┌ LDL cholesterol   [High] [Lipids] [Synthetic]                                          ┐
│ [Latest 131 mg/dL · Aug 15 2024] [Change −6 since Jul 2023] [Range <100] [4 results] │
├ Chart: every result as a dot on a line, reference band shaded, click → visit ──────────┤
├ All results ─────────────────────────────────────────┬ Related ────────────────────────┤
│ Date        Value   Flag   Source   Visit            │ Lipid panel: total, HDL, TG ›   │
│ Aug 15 2024 131     High   Synthea  Check-up ›       │ Medications: none on a statin   │
│ Jul 12 2023 137     High   Synthea  Check-up ›       │ Diagnoses: Obesity ›            │
└──────────────────────────────────────────────────────┴─────────────────────────────────┘
```

The other detail pages fill the same template:

| Page | Header | Main | Table | Related |
|---|---|---|---|---|
| Diagnosis | Active/Resolved, group, episodes, first onset | `EpisodeTimeline` of every episode | Episodes: onset, resolved, duration, visit | Medications started at those visits; tests that track the group |
| Medication | Active, class, current dosage | `EpisodeTimeline` of prescriptions, with dose changes marked | Prescriptions: product, dose, frequency, start, end, visit | Diagnoses at the prescribing visits; affected tests (e.g. HbA1c while on insulin) |
| Visit | Class, type, reason, date, duration, prev/next | Sections for tests (by panel, flagged), diagnoses made or resolved, and meds started or stopped | Each row links to its own detail page | — |
| Test / vital | Latest, change, range, count | `MeasureChart` (two series for BP) | Every result with flag and visit | Panel siblings, affecting meds, diagnoses |

### Interaction rules

- Every row anywhere is a link, with a chevron, a hover state and keyboard focus. Detail pages
  load server-side, so deep links and refresh work.
- Filters live in the URL query. Every list keeps its filters on back navigation.
- Counts are explicit: "×3 episodes", "12 results", "View all 46". Nothing is silently capped.
- Synthetic values keep the hatch and the badge everywhere. A study-sourced result (CGMacros,
  BIG IDEAs) reads "Study visit" where a Synthea one shows the visit name.
- Flags pair a colour with a word and an icon, never colour alone.
- **Empty states:** one line, e.g. "No tests in this panel."
- **Missing detail:** an unknown measure, concept, medication or visit renders the existing
  `not-found`.
- At 375 px, tables become stacked rows, the related panel moves below the table, and the section
  nav scrolls horizontally.

## Delivery, in commits

1. Schema, parser and loader: `product_rxcui`, `encounter_id` links, visit type and reason.
   Re-run `copy-ehr`.
2. Views and `twin/clinical/measures.py`, with tests.
3. The overview and list endpoints in `twin/api/record.py`, with tests.
4. The detail endpoints (tests, conditions, medications, visits), with tests.
5. UI: types and client, `components/record/*` building blocks, and the record layout.
6. UI: the overview page. Remove History, add the redirect, move `DailyCgm`.
7. UI: list pages and detail pages.
8. Docs: the README dashboard section, `twin-ui/README.md` and this plan.

## Verification

- `uv run pytest`, including `tests/test_record_api.py`. It covers:
  - the overview shape;
  - 404s for an unknown patient and for unknown detail ids;
  - a recurring diagnosis returning every episode;
  - a test with several results returning every result, with flags;
  - BP pairing SBP and DBP;
  - single-day medications;
  - visit cross-links;
  - cursor paging on visits.
- After the `copy-ehr` backfill, check counts on BIG IDEAs 001 (46 visits, 33 conditions, 14
  regimens) and CGMacros 003 (insulin products).
- Check the UI with `bun run lint`, `bun run typecheck` and `bun test`.
- In the browser, test BIG IDEAs and CGMacros twins:
  - the overview → detail → visit → back flow;
  - each filter, through the URL;
  - the `/history` redirect;
  - 375 px.

## Not in this change

- Administered doses (`core.medication_dose` is empty).
- Allergies and immunisations: they aren't ingested yet. They would follow the same
  list-and-detail pattern.
- Editing the record.
- Writing back to FHIR.
