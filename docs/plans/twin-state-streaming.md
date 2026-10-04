# Plan: live twin state, `/patients/{id}` and WebSocket state streaming

Status: implemented 2026-10-04 (see "As built" at the end) · scope: a device simulator, event ingestion, the per-patient twin
state (`PatientTwinStateManager`), an in-process event bus, `GET /patients/{id}` and a WebSocket
that pushes state changes to the UI.

## 1. Goal

Turn the twin from a store you query into one that **reacts**. A simulated sensor device sends
readings. The API stores each reading in TimescaleDB and folds it into the patient's live state.
When anything changes (a new glucose value, a glucose band crossing, the patient falling asleep),
the change is recorded and pushed to every UI watching that patient.

```
 simulator (twin simulate-stream)        one process per run; acts as the patient's devices
        │  POST /ingest/events  (batches of SensorEvent)
        ▼
 EVENT INGESTION   validate → resolve device → patient → write ts.* (ON CONFLICT DO NOTHING)
        │  accepted events (after commit)
        ▼
 TimescaleDB  ── ts.glucose_reading / ts.wearable_sample / ts.sleep_segment
        │                               ts.twin_state_transition (new)
        ▼
 PatientTwinStateManager   load ← report.twin_latest (new view)
        │  apply(event) → StateDelta → update(state) → publish(delta)
        ▼
 EventBus (in-process, per-patient topics)
        │
        ▼
 WS /ws/patients/{id}/state   snapshot, then deltas      GET /patients/{id}   current snapshot
        │
        ▼
       UI
```

How this differs from what exists: today `WS /ws/patients/{id}` (src/twin/api/replay.py) reads
history from `report.replay_stream` and sends it **straight to the client**. Nothing is stored,
and no state is kept. In the new flow, data enters the way a real device's would, and the UI sees
**state**, not raw rows.

## 2. Design decisions

| Decision | Choice | Why |
|---|---|---|
| Simulator → API transport | `POST /ingest/events`, batched (≤ 500 events or 1 s) | Idempotent and easy to retry. Real CGM/wearable gateways upload in batches and backfill after dropouts. `httpx` is already a dependency. |
| Write before apply | Commit to TimescaleDB **first**, then apply to state | The DB is the source of truth. State is derived and can always be rebuilt with `load()`. A crash never leaves state ahead of storage. |
| Where state lives | In memory in the API process, one `PatientTwinState` per patient, loaded lazily | It is derived data. Following the schema rule "no derived columns", the latest values are not stored. On restart they are rebuilt from the `report.twin_latest` view. |
| What is persisted | Only **status transitions** (glucose band in_range→high, trend, sleep stage, SpO₂ band, device stale/fresh) in `ts.twin_state_transition` | "The change should be noted." Raw values are already in `ts.*`. Transitions are low-volume events that are not easy to recompute, and they are the audit trail of what the twin told the UI. |
| Event bus | In-process `asyncio` pub/sub behind a small `EventBus` protocol | No new infrastructure (Docker stays TimescaleDB + HAPI only). Requires **one uvicorn worker**. The protocol allows a later swap to Postgres `LISTEN/NOTIFY` if ingestion moves to its own process. |
| Live data vs research data | The simulator writes under **dedicated simulator devices**. A new `ref.device_model.is_live_simulator` flag keeps these devices out of fusion, continuous aggregates and `ml.*` views | Replayed history shifted to "now" would otherwise duplicate each patient's series in the feature store. |
| WebSocket path | New `WS /ws/patients/{id}/state`; the existing replay WS is unchanged | The replay WS is not a breaking change. It could later move to `/ws/patients/{id}/replay`. |

## 3. Components

### 3.1 Device simulator: `src/twin/streaming/simulator.py`, `twin simulate-stream`

```
uv run twin simulate-stream --patient <uuid>|--tag composite-patient \
    --speed 60 --api http://127.0.0.1:8765 [--loop] [--jitter 0.1] [--drop-rate 0.01] [--late-rate 0.02]
```

- **Pairing.** On start, for each patient it calls `POST /patients/{id}/devices` with model
  codes `live-cgm` / `live-wearable` and receives `device_id`s. This is the same as a real device
  being paired.
- **Source signal.** The simulator replays the patient's own recorded data:
  - CGM: `ts.glucose_fused`, so one calibrated value every 5 minutes. Censored rows are sent
    as-is.
  - Wearable: `ts.wearable_sample`, all metrics.
  - Sleep: `ts.sleep_segment`.

  The data is read through the same ordered, server-side cursor pattern as `replay.py`.
- **Re-timing.** `device_time = start_wallclock + (t − t₀)`, advanced on a virtual clock that
  runs `speed`× faster than real time.
  - `--speed 1` is true real time.
  - At `--speed 60`, one hour of data plays in one minute, and device timestamps run ahead of
    the wall clock. This is intended and documented.
- **Realism knobs.** These exercise the ingest and state edge cases:
  - `--jitter`: noise on values, ±2 mg/dL and ±1 bpm.
  - `--drop-rate`: missing readings, which trigger stale detection.
  - `--late-rate`: a reading held back and sent in a later batch out of order, as a CGM backfill
    would.
  - `--loop`: restarts with a new offset when the recording runs out.
- **Sending.** Events are batched per tick. Failed POSTs are retried with backoff, and the
  batch is kept until it is accepted. Each event carries `seq` per device, so the API can drop
  duplicates.
- Patients without sensor data (for example NHANES) are skipped with a log line.

### 3.2 Event model: `src/twin/streaming/events.py`

A Pydantic discriminated union on `kind`:

```python
class GlucoseEvent(BaseModel):  kind: Literal["glucose"];  device_id: int; time: datetime; seq: int
                                glucose_mg_dl: int = Field(ge=20, le=600)
class WearableEvent(BaseModel): kind: Literal["wearable"]; device_id: int; time: datetime; seq: int
                                metric: str   # ref.wearable_metric.code
                                value: Decimal
class SleepEvent(BaseModel):    kind: Literal["sleep"];    device_id: int; time: datetime; seq: int
                                stage: SleepStage; until: datetime
SensorEvent = Annotated[GlucoseEvent | WearableEvent | SleepEvent, Field(discriminator="kind")]
```

Unit handling: the canonical unit comes from `ref.wearable_metric.unit`, and events must use it.
The ingest endpoint rejects unknown metric codes with a 422.

### 3.3 Ingestion: `src/twin/streaming/ingest.py` + `src/twin/api/ingest.py`

`POST /ingest/events` takes `{"events": [SensorEvent, ...]}` and returns
`{"accepted": n, "duplicates": m, "rejected": [{index, reason}]}`.

1. Resolve `device_id → (patient_id, model)` from a cache, loaded from `core.device` on a miss.
   Unknown devices are rejected.
2. Write, in one transaction, with `INSERT … ON CONFLICT DO NOTHING RETURNING` on the
   hypertable primary keys:
   - glucose → `ts.glucose_reading`
   - wearable → `ts.wearable_sample`
   - sleep → `ts.sleep_segment`

   `RETURNING` reveals which rows were new, and only new rows go on to the state. The existing
   `upsert()` helper does not return rows. Add an `insert_new()` beside it in `twin/db/engine.py`.
3. After commit, call `await manager.handle(patient_id, new_events)`, grouped per patient and
   sorted by time.

### 3.4 Twin state: `src/twin/streaming/state.py` (pure, no I/O)

```python
@dataclass
class Signal:                 # one live channel
    value: float | str | None
    unit: str | None
    time: datetime | None     # device time of the latest reading
    source: str | None        # device model
    status: str | None        # band / stage / stale, see rules below
    previous: float | None = None

@dataclass
class PatientTwinState:
    patient_id: UUID
    version: int              # +1 on every published change
    as_of: datetime           # wall clock of the last update
    glucose: Signal           # + trend: Literal["rising_fast","rising","steady","falling","falling_fast"] | None
                              # + rate_mg_dl_min, from readings in the last 15 min (ring buffer)
    heart_rate: Signal        # + mean_5min
    activity: Signal          # level: sedentary|light|moderate|vigorous (from mets or activity_level)
    steps_today: int | None
    sleep: Signal             # stage awake|light|deep|rem, until
    spo2: Signal
    respiration_rate: Signal
    hrv_rmssd: Signal
    skin_temp: Signal
    stress: Signal
    last_medication: dict | None
    devices: dict[int, DeviceStatus]   # last_seen, stale
```

Rules: the thresholds live in one `RULES` table in `state.py` so they are easy to review.

| Signal | Status rule |
|---|---|
| glucose band | `very_low` < 54, `low` < 70, `in_range` 70–180, `high` > 180, `very_high` > 250 mg/dL (international CGM consensus TIR ranges) |
| glucose trend | rate over 15 min: ≥ +2 `rising_fast`, ≥ +1 `rising`, ≤ −1 `falling`, ≤ −2 `falling_fast` mg/dL/min |
| SpO₂ band | `low` < 90 %, `borderline` 90–94, `normal` ≥ 95 |
| activity | METs < 1.5 sedentary, < 3 light, < 6 moderate, else vigorous (or the `activity_level` 0–3 code) |
| staleness | glucose: no reading for 15 min; heart rate: 10 min. Sets `stale`, and the next reading clears it |

The reducer `apply(state, event) -> StateDelta | None`:

- returns `None` when nothing visible changed (same value and same status), so no version bump
  and nothing is published;
- ignores events older than the signal's current `time` for the **latest** value (late or
  backfilled rows are still stored by ingestion);
- returns `StateDelta(version, time, changes={path: new_value}, transitions=[Transition(signal,
  from, to, value, time)])`.

Because the reducer is pure, it can be unit-tested with no DB and no event loop.

### 3.5 `PatientTwinStateManager`: `src/twin/streaming/manager.py`

One instance is created in the FastAPI `lifespan` and stored on `app.state`.

```python
class PatientTwinStateManager:
    def __init__(self, bus: EventBus, loader: StateLoader, store: TransitionStore, max_patients=256): ...

    async def load(self, patient_id) -> PatientTwinState
        # build from report.twin_latest + glucose ring buffer (last 15 min of readings); cache it
    async def get(self, patient_id) -> PatientTwinState
        # cached or load(); raises UnknownPatient
    def apply(self, state, event) -> StateDelta | None
        # delegates to state.apply (pure)
    async def update(self, patient_id, delta) -> PatientTwinState
        # mutate cached state, version += 1, persist delta.transitions to ts.twin_state_transition
    async def publish(self, patient_id, delta) -> None
        # bus.publish(f"patient:{id}", {"type": "delta", ...})
    async def handle(self, patient_id, events) -> list[StateDelta]
        # under a per-patient asyncio.Lock: for e in events: apply → update → publish.
        # Consecutive deltas from one batch are coalesced into one message.
    async def snapshot(self, patient_id) -> dict
        # JSON-ready, used by GET and on WS connect
    async def tick(self) -> None
        # background task every 30 s: staleness checks → update/publish
    def evict_idle(self) -> None
        # LRU / no subscribers for 10 min; state is rebuilt from the DB on demand
```

- `loader` and `store` are small protocols. Tests use in-memory fakes, and production uses
  SQLAlchemy over `report.twin_latest` and `ts.twin_state_transition`.
- The per-patient lock keeps `apply → update → publish` ordered. Versions on the wire are
  therefore strictly sequential per patient.

### 3.6 Event bus: `src/twin/streaming/bus.py`

```python
class EventBus(Protocol):
    async def publish(self, topic: str, message: dict) -> None: ...
    def subscribe(self, topic: str) -> AsyncContextManager[AsyncIterator[dict]]: ...

class InProcessBus:  # dict[topic, set[asyncio.Queue(maxsize=256)]]
```

- **Slow consumers.** When a subscriber's queue is full, its queue is cleared and a single
  `{"type": "resync"}` marker is queued. The WS handler then sends a fresh snapshot. One slow
  browser tab never blocks ingestion.

### 3.7 API routes: `src/twin/api/patients.py` (new router, included in `replay.py`'s `app`)

| Route | Returns |
|---|---|
| `GET /patients/{id}` | `{"patient": {id, name, sex, age, tags}, "state": snapshot, "streaming": bool}`. 404 for an unknown patient. A patient with no sensors gets empty signals and `streaming: false`. |
| `WS /ws/patients/{id}/state` | `snapshot` on connect, then `delta`s, then `heartbeat` every 20 s. Closes with code 4404 for an unknown patient. |
| `GET /patients/{id}/transitions?since=&signal=` | The persisted transitions, for the UI's event list. |
| `POST /patients/{id}/devices` | Pairs a simulator device (`{"model": "live-cgm"}`) and returns `{"device_id"}`. Idempotent through the `(patient_id, model_id)` unique key. |
| `POST /ingest/events` | See 3.3. |

The existing `GET /patients` (list) stays in `replay.py`. `/twin/{id}` remains the full record
(EHR, baseline, daily summaries). `/patients/{id}` is the **live** view.

WebSocket protocol:

```jsonc
// server → client
{"type": "snapshot", "version": 41, "state": { ... }}
{"type": "delta", "version": 42, "time": "2026-10-04T09:15:00-05:00",
 "changes": {"glucose.value": 186, "glucose.status": "high", "glucose.trend": "rising"},
 "transitions": [{"signal": "glucose_band", "from": "in_range", "to": "high", "value": 186}]}
{"type": "heartbeat", "version": 42}
// client → server (optional)
{"type": "resync"}       // e.g. after the client sees a version gap
```

Client rule: if `delta.version != last + 1`, send `resync` (or reconnect). The server replies
with a snapshot.

## 4. Schema changes (normalised, patient-centric)

1. **`ref.device_model`**: new column `is_live_simulator boolean NOT NULL DEFAULT false`.
   - `init-db` does not migrate existing tables, so `schema.py` gets one idempotent
     `ALTER TABLE … ADD COLUMN IF NOT EXISTS` before seeding. This avoids a full `reset.sh`.
   - Add the matching ORM column.
   - Add two seed rows in `seeds/reference/device_model.csv`, both `is_synthetic=true,
     is_live_simulator=true`:
     - `Twin simulator, Live CGM`: `cgm`, interstitial, 5 min
     - `Twin simulator, Live wearable`: `wearable`
2. **`ts.twin_state_transition`**, a hypertable, model in `twin/models/sensors.py`:
   - `patient_id` FK `core.patient` ON DELETE CASCADE
   - `signal` (enum `state_signal`: glucose_band, glucose_trend, sleep_stage, spo2_band,
     activity_level, device_stale)
   - `time` (device time), `from_status` text NULL, `to_status` text NOT NULL, `value` numeric NULL
   - `state_version` bigint
   - PK `(patient_id, signal, time)`

   Add it to `HYPERTABLES` in `schema.py`.
3. **`report.twin_latest`** view, in `report_views.sql`, plus a table definition in
   `models/views.py`: one row per `(patient_id, signal)` with `value`, `unit`, `time` and
   `source`.
   - Built with `LATERAL (… ORDER BY time DESC LIMIT 1)` per device and metric, which uses the
     hypertables' `(device_id, …, time)` primary keys.
   - It covers glucose (live CGM if present, else `glucose_fused`), every wearable metric, the
     current sleep segment, the last medication dose, and `steps_today` (sum since local midnight).
   - Status values (band/trend) are **not** stored. The reducer recomputes them on `load()`.
4. **Keep live data out of research outputs.** Add `AND NOT dm.is_live_simulator`, or the
   equivalent device filter, to the following:
   - `twin/pipeline/fusion.py`: CGM selection at line 80. Otherwise the live CGM becomes a third
     CGM.
   - `continuous_aggregates.sql`: the `ts.glucose_reading` and `ts.wearable_sample` aggregates.
   - `report_views.sql`: activity, sleep, HRV and `sensor_window`. `replay_stream` should keep
     live rows only if we want them replayable. Proposal: exclude them.
   - `ml_views.sql`: the `ts.wearable_sample` and `ts.sleep_segment` sub-selects.
5. **`twin stream-reset` CLI**: deletes the live-simulator devices. The cascade removes their
   readings. It also truncates `ts.twin_state_transition`.

## 5. Implementation order

Each step is shippable and tested before the next.

1. **Pure core**: `events.py`, `state.py` (rules, reducer, trend ring buffer), and
   `tests/test_twin_state.py`.
2. **Bus + manager** with fake loader/store, and `tests/test_state_manager.py`: version
   sequence, coalescing, per-patient lock ordering, slow-consumer resync, eviction, staleness
   `tick`.
3. **Schema**: the device model column and seeds, `ts.twin_state_transition`,
   `report.twin_latest`, the live-simulator filters (4.4), and the SQLAlchemy loader/store.
   Check: `uv run twin init-db` on the existing DB; `report.twin_latest` returns rows for the
   composite patients; `ml.series_5min` row counts are unchanged.
4. **Ingestion + routes**: `api/ingest.py`, `api/patients.py`, lifespan wiring, and the `tick`
   background task. `tests/test_stream_api.py` uses FastAPI's `TestClient`
   (`websocket_connect`) with the fakes injected through `app.dependency_overrides`, so no DB is
   needed. It covers: GET 404 and 200; WS snapshot then delta after a POST; resync on a version
   gap; a duplicate POST gives no second delta.
5. **Simulator**: `simulator.py` and the `twin simulate-stream` / `twin stream-reset`
   commands. `tests/test_simulator.py` covers re-timing, batching, and the drop/late knobs as
   pure functions over a fixed series.
6. **Docs**: a README section ("Live twin"), a `scripts/stream.sh`, the new routes in the README
   API table, and a regenerated `docs/diagrams/data-pipeline` diagram with the streaming path.

## 6. End-to-end check

```bash
docker compose up -d
uv run twin init-db
uv run twin serve                                  # terminal 1 (single worker)
uv run twin simulate-stream --tag composite-patient --speed 60   # terminal 2
uv run python -m websockets ws://127.0.0.1:8765/ws/patients/<id>/state   # terminal 3
curl -s http://127.0.0.1:8765/patients/<id> | jq '.state.glucose'
```

Expected results:

- A snapshot arrives, then deltas roughly every 5 seconds: one 5-minute CGM step at 60×, plus
  heart-rate deltas.
- Versions increase by exactly 1.
- Stopping the simulator gives `device_stale` transitions within about 15 minutes of device time
  on the next tick.
- `ts.twin_state_transition` gains rows.
- Restarting `twin serve` gives the same snapshot values. The version restarts, which is
  acceptable because clients resync on connect.
- `ml.series_5min` and `report.cgm_daily` counts match their values before the run.

## 7. Risks and open questions

- **Single worker.** In-memory state and the in-process bus only work with one uvicorn worker.
  `serve` already runs one, and this should be documented. Scaling out means Postgres
  `LISTEN/NOTIFY` (or Redis) behind `EventBus`, and owning state per patient shard.
- **Speed > 1 puts device timestamps in the future** relative to the wall clock. This is fine for
  the demo. Staleness is measured on device time (latest event time), not on the wall clock, so it
  stays consistent.
- **Hypertable compression.** If compression policies cover recent chunks, inserting
  late-arriving rows into compressed chunks is slower. Live data is near "now", so this should
  not matter. Check `schema.py`'s compression `after` interval.
- **Clinical thresholds** are display bands, not alerts or advice. The UI should say so, as the
  simulation endpoints already do.
- **Open:**
  - Should live simulator rows appear in `report.replay_stream`? The proposal is no.
  - Should `/ws/patients/{id}` (replay) move to `/ws/patients/{id}/replay` now, or later?

## 8. As built

Implemented as planned, with these differences:

- **Events carry no `seq`.** Deduplication relies on the hypertable primary keys alone
  (`ON CONFLICT DO NOTHING RETURNING`).
- **Pairing takes a device kind.** `POST /patients/{id}/devices` takes `{"kind": "cgm" | "wearable"}`,
  not a model code.
- **One delta per batch.** Each ingested batch publishes at most one delta, and its version
  bumps once. Every transition inside the batch is still recorded.
- **Staleness uses an estimated device clock.** The manager learns the device clock's rate from
  successive batches, so silence at 60× is detected in seconds. Device time alone cannot tell
  that a stream has stopped.
- **`--from-now` was added to the simulator.** Twin time spans the present for most recordings,
  so the stream can continue the patient's history instead of replaying it from the start.
- **`last_medication` is left out of the state.** The simulator does not stream doses.
- **Answers to the open questions:**
  - Live rows are excluded from `report.replay_stream`.
  - The history replay WebSocket stays at `/ws/patients/{id}`.

Verified end to end against the local database:

- One patient at 60×: sequential versions 1–26 and activity band transitions. After the
  simulator stopped, heart rate went `stale` about 11 s later and glucose about 16 s later, and
  `streaming` turned false after 60 s.
- 30 patients at 120×: 3,961 events accepted, none rejected.
- `ml.series_5min`, `report.cgm_daily`, `activity_daily`, `sleep_nightly`, `hrv_nightly`,
  `sensor_window` and `cgm_device_daily` row counts were identical before and after streaming.

