# Glucose forecast in the Predict tab (plan, 2026-10-06)

**Status: built (2026-10-06).**
- Step 1: `ts.meal` holds the 455 logged meals of the 14 CGMacros twins, matching the raw files.
- Step 2: `twin train-glucose-forecaster` exports a 3-seed GRU as safetensors + `meta.json`; test
  RMSE 10.0 / 15.7 / 19.4 / 22.1 mg/dL at +15/30/45/60 min.
- Step 3: `twin.prediction`. Forecasts served from database rows match the training path within
  0.07 mg/dL (42 origins, all 14 CGMacros twins), and a GRU request takes about 45 ms. It
  differs from the plan in three small ways:
  - the warning rules live in `rules.py`, which avoids a module named like the standard
    library's `warnings`;
  - the trend reuses the live twin's `glucose_trend`;
  - the ARIMA fallback uses a fixed order (3,1,2), the benchmark's most common pick.
- Step 4: `GET /patients/{id}/predictions/glucose[?at=]` in `twin.api.prediction`, as specified. It
  runs the model in the thread pool (torch, ARIMA fits). A missing bundle and a missing `ml`
  extra both surface as `ModelUnavailable` and answer 503. Warm requests take about 140 ms (GRU)
  and 0.6 s (ARIMA).
- Step 5: the Predict tab (`twin-ui/components/predict/`). It was checked in the browser for:
  - a CGMacros twin, latest and past origins, including a spike warning that the real readings
    confirmed;
  - a BIG IDEAs twin (ARIMA);
  - phone width.

  Three changes came out of those checks:
  - the chart shows 90 min of history on phones, so the future region stays readable;
  - the forecast line fades in instead of drawing in, because a draw-in animation replaces the
    dash pattern;
  - the caveat and accuracy note are per model.

  The UI has no dark theme, so there was no dark-mode check.
- The three decisions below were taken as recommended.

The Predict tab shows a glucose forecast at +15, +30, +45 and +60 minutes. It is drawn on the
glucose chart as a highlighted future segment, with one card per horizon and a warning when the
forecast shows a spike or leaves the target range. The model is the GRU from the benchmark
(`twin bench-glucose`, `data/benchmarks/cgmacros-real/`), retrained with a 45-minute output.

The work has five steps, each one usable and testable before the next:

1. Store meals.
2. Train and export the model.
3. Prediction service.
4. FastAPI route.
5. Predict tab UI.

## Decisions needed

| # | Question | Recommendation |
|---|---|---|
| 1 | **BIG IDEAs twins** (16 of 30) have no meal log and no Fitbit activity, which are two of the GRU's inputs. What do they get? | Fall back to a **per-patient ARIMA** fitted on the twin's own glucose history (glucose-only, about 1 s per fit, cached). The card names the model. The benchmark puts ARIMA at 25.8 mg/dL RMSE at +60, against 22.4 for the GRU and 27.9 for persistence. Alternative: show "not available" for those twins. |
| 2 | **Forecast origin.** The twin's data is recorded, so "now" is the last reading. | The forecast starts from the latest reading by default. `?at=` forecasts from any earlier moment and overlays what actually happened, so the forecast can be checked by eye. |
| 3 | **Train on which segments?** | Keep the benchmark protocol: train on 60 %, early-stop and calibrate the bands on the next 15 %. The exported model then carries its own held-out test metrics, which the UI quotes. Retraining on everything would make those numbers untestable. |

## Why these steps are needed

- **Meals are not in the database.** `twin load-sensors` reads them only to check the CGM clocks
  (`pipeline/fusion.py`: "Meals are not stored"). The GRU needs them; they carry most of its
  advantage at 60 min (skill 0.20 for the GRU against 0.07 for glucose-only ARIMA).
- **The benchmark has no +45 horizon.** The GRU head predicts 3 outputs. It has to be retrained
  with 4, and +45 needs its own test metrics before the UI shows it.
- **Train/serve skew is the main risk.** Training read the raw CGMacros CSVs. Serving reads the
  database, in twin time (source time + `core.patient.time_offset`). The model must see the same
  features both ways, so a parity test checks this (step 3).
- **The twin's glucose is fused (Dexcom + Libre); the model was trained on Dexcom alone.**
  Inference reads the twin's native Dexcom readings from `ts.glucose_reading`, matching
  training, not `ts.glucose_fused`. The chart can still show the fused line as the measured
  history.
- **No synthetic inputs.** Inference uses only real channels: Dexcom, Fitbit heart rate and
  activity kcal, meals, and the static factors (age, sex, BMI, HbA1c, fasting glucose).
  - Generator devices (`is_synthetic`) and live-simulator devices are excluded.
  - Static factors come from the CGMacros side of the composite patient, never from Synthea.
    HbA1c, fasting glucose, weight and height are the real labs that `reconcile` writes as
    `composite-override`.
  - Age needs a check. The twin's birth date comes from the matched Synthea patient
    (`match_age_diff`), so the model must use the participant's own age from `bio.csv`.

## Step 1: store meals

The table follows the schema conventions: patient-centric, `patient_id` as the FK, and no
derived columns.

```
ts.meal (hypertable on time)
  patient_id   uuid  FK core.patient
  time         timestamptz        -- twin time of the logged meal
  meal_type    meal_type enum     -- breakfast | lunch | dinner | snack
  energy_kcal, carbs_g, protein_g, fat_g, fiber_g   numeric, nullable
  PK (patient_id, time)
```

- `load-sensors` writes them using the same time shift as the sensor readings. Only CGMacros twins
  have meals.
- `Amount Consumed` stays out, as in the benchmark (it mixes 0–4 codes with percentages).
- A `report.meal_window` view supplies per-meal summaries for the UI, so no derived columns are
  stored.
- Check: the meal count for the 14 CGMacros twins matches the raw files.

## Step 2: train and export the model

`twin train-glucose-forecaster` (new) trains the model and writes a self-describing bundle. The
prediction service loads that bundle. The command reuses `twin.ml.bench` rather than copying it:

- **Horizons** become `(15, 30, 45, 60)` everywhere (`bench/data.py`, done). The GRU head gets 4
  outputs.
- **Shared features.** Frame building is split out of the raw loader (`bench/data.build_frame`,
  done). Window building is split out of `bench/neural.build_tensors` into
  `window(frame, origin, scaling)`. Training and serving call the same two functions.
- **Training:** GRU, 3 seeds, all 45 CGMacros participants, the benchmark protocol (decision 3),
  on MPS.
- **Prediction bands:** split-conformal from the ensemble's validation residuals, giving the 10th
  and 90th error percentiles per horizon (an 80 % band). Coverage on the test set is measured and
  recorded; it should come out near 80 %.

### Export format

| Format | Serving needs | For | Against |
|---|---|---|---|
| **safetensors weights + `meta.json`** (recommended) | torch, the `Forecaster` class, `safetensors` (~0.5 MB) | Plain tensors, no pickle, so loading can't run code. One code path: the same class trains and serves, so serving matches training exactly. The JSON is human-readable. | Serving needs torch (491 MB), which the `ml` extra installs anyway. |
| PyTorch state_dict (`torch.save`, `.pt`) | torch, the `Forecaster` class | No new dependency. | The file is a pickle zip. `weights_only=True` makes loading safe, but the file is less transparent than safetensors. |
| TorchScript (`torch.jit.script`) | torch | The graph is self-contained. | Deprecated in PyTorch in favour of `torch.export`. |
| `torch.export` (`.pt2`) | torch | The current graph-export format. | Still needs torch. Support for RNNs like the GRU would have to be verified. |
| ONNX (`.onnx`) + onnxruntime | onnxruntime (tens of MB); no torch | The API could run without torch, and it's portable to other runtimes. | Adds `onnx` and `onnxscript` at export time and `onnxruntime` at serving, none installed (slow network). ONNX outputs must be checked against PyTorch. Worth it only if the API is ever deployed without torch. |

**Recommendation: safetensors + `meta.json`.** The API already runs in the environment that has
torch, and keeping one model class removes a whole class of train/serve mismatch. An ONNX file can
be added to the same bundle later without changing `meta.json`.

### Bundle layout

```
data/models/glucose_forecast/            gitignored, like the other models
  CURRENT                                one line: the run directory the API loads
  gru-20261006-<git sha>/                one immutable directory per training run
    weights.safetensors                  3 seeds, keys prefixed seed0. / seed1. / seed2.
    meta.json                            the model card and the preprocessing contract
```

Rolling back is a one-line edit to `CURRENT`. Old runs stay on disk until deleted.

### `meta.json` (format 1)

```jsonc
{
  "format_version": 1,
  "model": {
    "name": "gru", "version": "gru-20261006-2bcb541",
    "architecture": { "cell": "gru", "hidden": 64, "layers": 2, "dropout": 0.1 },
    "seeds": [0, 1, 2], "ensemble": "mean of seed predictions"
  },
  "inputs": {                                   // the preprocessing contract
    "glucose_source": "Dexcom native readings",
    "step_minutes": 5, "lookback_steps": 36, "max_bridged_gap_min": 30,
    "step_features": ["glucose_in", "hr", "active_kcal", "energy_kcal", "carbs_g", "protein_g",
                      "fat_g", "fiber_g", "tod_sin", "tod_cos", "hr_missing", "kcal_missing"],
    "static_features": ["age", "male", "bmi", "hba1c", "fasting_glucose"],
    "scaling": {
      "glucose_in": { "mean": 0, "std": 0 }, "hr": { "mean": 0, "std": 0 }, "active_kcal": { "mean": 0, "std": 0 },
      "macros": "log1p(x) / 3",
      "static": { "mean": [0, 0, 0, 0, 0], "std": [0, 0, 0, 0, 0] },
      "missing": "NaN -> 0 after scaling"
    }
  },
  "outputs": {
    "horizons_min": [15, 30, 45, 60],
    "target": "glucose change from the origin, mg/dL / 30",
    "band": { "level": 0.8, "method": "split conformal, validation residuals",
              "low": { "15": 0, "30": 0, "45": 0, "60": 0 }, "high": { "15": 0, "30": 0, "45": 0, "60": 0 } }
  },
  "training": {
    "dataset": "CGMacros raw files, real data only", "participants": 45,
    "split": "per participant, chronological 60/15/25, purged",
    "epochs": [0, 0, 0], "device": "mps",
    "created": "…", "git_sha": "…", "python": "3.14.4", "torch": "2.13.0"
  },
  "evaluation": {                               // held-out test segment
    "model":       { "15": { "rmse": 0, "mae": 0, "mard_pct": 0, "skill": 0, "clarke_ab_pct": 0, "band_coverage": 0 } },
    "persistence": { "15": { "rmse": 0, "mae": 0, "mard_pct": 0 } }
  },
  "checksums": { "weights.safetensors": "sha256:…" }
}
```

The zeros are placeholders; the export fills them in. The UI reads `evaluation` for its accuracy
note and `outputs.band` for the hatched band.

### Loading (step 3)

The prediction service:
1. Reads `CURRENT`, then `meta.json`.
2. Checks `format_version` and the weights checksum.
3. Checks that `step_features` and `static_features` match, in order, what
   `build_frame` / `window` produce today.
4. Builds the 3 `Forecaster`s from `architecture`, loads each seed's weights with `strict=True`,
   and runs them on the CPU in eval mode.

Any mismatch makes the route answer 503 with the reason and the command to retrain. The service
never guesses its way past a mismatch. The model is loaded once per process.

### Dependencies

`safetensors` joins the `ml` extra.

### Tests

- **Round trip:** a tiny model trained for one epoch on synthetic frames, exported then loaded,
  gives identical predictions.
- **Contract:** a changed feature list, a format version from the future or a corrupted weights
  file all refuse to load, each with a clear message.
- **Accuracy:** the exported ensemble's test RMSE per horizon equals the `evaluation` block in
  `meta.json`.

## Step 3: prediction service

The package follows the `twin.record` pattern: a store that does the I/O, a pure assembler, and
routes in `twin.api`. It is called `twin.prediction` to keep it apart from the old
gradient-boosting module `twin.ml.forecast`.

```
src/twin/prediction/
  model.py     GlucoseForecaster: load the bundle once (lru_cache); predict(window) -> per-horizon
               value + band. CPU inference (a single forecast takes milliseconds; MPS isn't worth it
               in the API). ArimaForecaster for decision 1, using classical._forecasts.
  store.py     SqlForecastStore: the last 4 h (lookback plus meal context) of native Dexcom, Fitbit
               HR and kcal, and meals, up to `at` (never after), plus readings after `at` for the
               overlay, plus the static factors. Builds the same 5-minute frame as bench/data.py.
  assemble.py  Pure: frame + forecasts -> response. Origin, trend, per-horizon cards, bands and
               warnings, the inputs the model saw, and the missing ones.
  warnings.py  Pure rules (below), with thresholds shared with the live twin's glucose bands
               (54 / 70 / 180 / 250, as in twin.streaming.state and twin-ui glucoseBand).
```

**Warnings**, evaluated per horizon on the point forecast. The band's edge only raises a softer
"possible" warning.

| Kind | Rule | Severity |
|---|---|---|
| `spike` | rise ≥ 50 mg/dL from now within 60 min, or ≥ 2 mg/dL/min between two horizons | warning |
| `high` | forecast > 180 | warning |
| `very_high` | forecast > 250 | danger |
| `low` | forecast < 70 | warning |
| `very_low` | forecast < 54 | danger |
| `possible_*` | only the 80 % band crosses the line | info |

A forecast is not given, and the response says why, when:
- the 3-hour lookback has gaps longer than 30 min;
- the last reading is more than 15 min before `at`;
- the twin has no Dexcom (decision 1).

**Tests:**
- **Parity:** for a CGMacros twin, the database-built frame equals the raw-CSV frame after the time
  shift, so the predictions are equal.
- **No leakage:** nothing after `at` reaches the window.
- The warning rules, including the edge values 180 and 250.
- The assembler with a fake store and a stub model, as in `tests/test_record*`.

## Step 4: FastAPI route

`src/twin/api/prediction.py`, mounted next to the record routes:

```
GET /patients/{patient_id}/predictions/glucose?at=<twin time, optional>
```

```jsonc
{
  "patient_id": "…",
  "model": { "name": "gru", "label": "GRU · meals, activity, glucose", "version": "<git sha>",
             "trained_on": "45 CGMacros participants", "horizons": [15, 30, 45, 60],
             "test_rmse": { "15": 10.0, "30": 15.8, "45": null, "60": 22.4 } },  // from meta.json
  "origin": { "time": "…", "glucose": 142, "band": "in_range", "trend_mg_dl_min": 1.4 },
  "history": [ { "t": "…", "v": 138 } ],            // 3 h of measured glucose
  "forecast": [ { "horizon_min": 15, "time": "…", "glucose": 155, "low": 143, "high": 167,
                  "change": 13, "band": "in_range", "warnings": [] } ],
  "actual": [ { "t": "…", "v": 160 } ],             // readings after origin, when `at` is in the past
  "warnings": [ { "kind": "spike", "severity": "warning", "horizon_min": 45,
                  "message": "Rising about 55 mg/dL within 45 min" } ],
  "inputs": { "meals": [ { "time": "…", "carbs_g": 62, "energy_kcal": 540 } ],
              "heart_rate": true, "activity": true, "missing": [] },
  "unavailable": null,                               // or { "reason": "…" } with no forecast
  "caveat": "Model estimate from 45 CGMacros participants; not a clinical prediction."
}
```

- The error contract matches the existing routes:
  - 404 for an unknown patient;
  - 503 when the model isn't exported (with the command to run) or the `ml` extra isn't installed;
  - 200 with `unavailable` when the data can't support a forecast.
- The old `POST /twin/{id}/simulate/glucose` stays as it is. The Predict tab's what-if sandbox
  is a separate piece of work.
- **Tests:** the route through the FastAPI test client with a fake store, covering 200,
  `unavailable`, 404 and 503.

## Step 5: Predict tab UI

`twin-ui` runs Next 16, so the docs in `node_modules/next/dist/docs/` are read first (AGENTS.md).

```
app/patients/[id]/predict/page.tsx        server component: fetch the forecast (?at= passed through)
components/predict/glucose-forecast.tsx    client: layout, refresh, origin picker
components/predict/forecast-chart.tsx      measured line + future segment
components/predict/horizon-cards.tsx       +15 / +30 / +45 / +60 cards
components/predict/forecast-warning.tsx    banner for the most severe warning
components/predict/model-inputs.tsx        "what the model saw": meals, HR, activity, missing inputs
lib/api/types.ts, lib/api/server.ts        GlucoseForecast type, api.predictions.glucose(id, at)
lib/predict/format.ts (+ .test.ts)         warning copy, change arrows, band → token
```

**Layout**, top to bottom:

1. **Header.** "Glucose forecast" with the model chip ("Model estimate · GRU", or "ARIMA ·
   glucose only"), the origin ("from 14:35 · latest" or a picked time) and a Refresh button.
2. **Warning banner.** Shown only when there is a warning. It shows the most severe one: danger
   in the very-high/very-low token colour, warning in amber. For example, "Spike likely: about
   +55 mg/dL by 15:20 (+45 min)".
3. **Chart**, the highlighted future:
   - the last 3 h measured, as the solid glucose line;
   - a "Now" rule at the origin, with the future region tinted;
   - the forecast as a dashed line through the four horizon points, with a hatched 80 % band.
     This follows the tab's existing language: model output is never styled like a measurement;
   - the target band (70–180) and the dashed 250 line;
   - forecast points coloured by band;
   - for a past origin, the actual readings drawn dotted over the future region;
   - hovering a horizon point shows its value, band and range.
4. **Horizon cards**, in a 4-column grid (2 × 2 on phones). Each shows:
   - the predicted mg/dL as a large number, with the band chip;
   - the change from now, with a trend arrow;
   - the 80 % range;
   - the clock time.

   A card with a warning gets a coloured edge and an icon, with the message on the card.
5. **Inputs and accuracy.** Which recent meals the model saw (time and carbs), whether heart rate
   and activity were present, and the test error at each horizon ("±22 mg/dL typical error at
   +60"). The caveat is always visible.

**Chart component.** `time-series-chart.tsx` is 447 lines and built for measured series. Its
scale helpers (`niceTicks`, `useWidth`) move into `components/charts/scale.ts`, and the new
`forecast-chart.tsx` uses them. This avoids adding a forecast mode to the existing chart.

**Refresh.** When the origin is "latest", the page re-fetches every 5 minutes, the CGM reading
interval, via `router.refresh()`. The origin picker writes `?at=`.

**States:**
- loading (the existing `loading.tsx` pattern);
- `unavailable`: the reason, and the chart without a forecast;
- API unreachable (the existing error screen);
- model not exported (503): a message with the command to run.

**Checks:**
- `bun test` (format and warning helpers), `bun run typecheck`, `bun run lint`;
- the page checked in the browser preview for one CGMacros twin (latest and a past `?at=`), one
  BIG IDEAs twin and one twin without CGM, at phone width and in dark mode.

## Order and sizing

| Step | Depends on | Size |
|---|---|---|
| 1. `ts.meal` + load | – | small |
| 2. 4-horizon benchmark rerun, train + export | 1 is not needed (trained from raw files) | medium; about 40 min of benchmark compute, mostly SARIMA. The rerun can skip SARIMA, since it adds nothing over ARIMA. |
| 3. `twin.prediction` + parity test | 1, 2 | medium |
| 4. Route + tests | 3 | small |
| 5. UI | 4 (the response shape can be mocked earlier) | medium–large |
| Docs | all | small: README sections for the command, the route and the Predict tab |

Commits follow the same split: data, model export, service and route, UI pieces, docs.

## Out of scope

- The what-if sandbox (activity, insulin and meal scenarios). It needs causal care (see README,
  "Scenarios are model-based what-ifs"), so it is a separate plan.
- Forecasting from the live simulator stream. It replays CGM and wearables but not meals, so v1
  forecasts from recorded data.
- Push alerts. Warnings show on the tab only.
