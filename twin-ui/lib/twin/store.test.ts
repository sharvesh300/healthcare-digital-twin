import { describe, expect, test } from "bun:test";

import type { LiveMessage, Transition, TwinState } from "@/lib/api/types";

import { applyChanges, extendSeries, TwinStore } from "./store";

const signal = { value: null, unit: null, time: null, source: null, status: null };
const state = (over: Partial<TwinState> = {}): TwinState => ({
  patient_id: "p1",
  version: 0,
  as_of: null,
  streaming: false,
  glucose: { ...signal, trend: null, rate_mg_dl_min: null },
  heart_rate: signal,
  activity: signal,
  steps_today: signal,
  sleep: { ...signal, until: null },
  spo2: signal,
  respiration_rate: signal,
  hrv_rmssd: signal,
  skin_temp: signal,
  stress: signal,
  eda: signal,
  active_kcal: signal,
  ...over,
});

const delta = (version: number, changes: Record<string, unknown>, transitions: Transition[] = []) =>
  ({ type: "delta", patient_id: "p1", version, time: null, changes, transitions }) as Extract<LiveMessage, { type: "delta" }>;

describe("applyChanges", () => {
  test("sets flat paths without mutating the input", () => {
    const before = state();
    const after = applyChanges(before, { "glucose.value": 186, "glucose.status": "high", streaming: true });
    expect(after.glucose.value).toBe(186);
    expect(after.glucose.status).toBe("high");
    expect(after.streaming).toBe(true);
    expect(before.glucose.value).toBeNull();
    expect(after.heart_rate).toBe(before.heart_rate); // untouched signals keep identity
  });
});

describe("TwinStore", () => {
  test("applies deltas in version order and records transitions and pulses", () => {
    const store = new TwinStore({ state: state(), transitions: [], series: {} });
    const t: Transition = { signal: "glucose", time: "2026-10-04T09:05:00-05:00", from: "in_range", to: "high", value: 190 };
    expect(store.delta(delta(1, { "glucose.value": 190, "glucose.time": t.time }, [t]))).toBe(true);
    const v = store.getSnapshot();
    expect(v.state.version).toBe(1);
    expect(v.feed[0].to).toBe("high");
    expect(v.pulse.glucose).toBe(1);
    expect(v.series.glucose).toEqual([{ t: Date.parse(t.time), v: 190 }]);
  });

  test("a version gap asks for a resync and ignores deltas until the next snapshot", () => {
    const store = new TwinStore({ state: state(), transitions: [], series: {} });
    expect(store.delta(delta(2, { "glucose.value": 120 }))).toBe(false);
    expect(store.delta(delta(3, { "glucose.value": 130 }))).toBe(true); // ignored, no second resync
    expect(store.getSnapshot().state.glucose.value).toBeNull();
    store.snapshot({ state: state({ version: 3, glucose: { ...signal, value: 130, trend: null, rate_mg_dl_min: null } }) });
    expect(store.delta(delta(4, { "glucose.value": 140 }))).toBe(true);
    expect(store.getSnapshot().state.glucose.value).toBe(140);
  });

  test("deltas already contained in the snapshot are skipped", () => {
    const store = new TwinStore({ state: state({ version: 5 }), transitions: [], series: {} });
    expect(store.delta(delta(5, { "glucose.value": 99 }))).toBe(true);
    expect(store.getSnapshot().state.glucose.value).toBeNull();
  });

  test("the feed is newest first without duplicates", () => {
    const old: Transition = { signal: "activity", time: "2026-10-04T09:00:00-05:00", from: "light", to: "moderate", value: 3.2 };
    const store = new TwinStore({ state: state(), transitions: [old], series: {} });
    const a: Transition = { ...old, time: "2026-10-04T09:10:00-05:00", from: "moderate", to: "light" };
    store.delta(delta(1, {}, [old, a]));
    expect(store.getSnapshot().feed.map((f) => f.time)).toEqual([a.time, old.time]);
  });
});

describe("snapshots that carry context", () => {
  test("series and feed replace the buffers; replay progress is kept", () => {
    const old: Transition = { signal: "sleep", time: "2026-10-03T23:00:00-05:00", from: "awake", to: "light", value: null };
    const store = new TwinStore({ state: state(), transitions: [old], series: { glucose: [{ t: 1, v: 99 }] } });
    const t = "2026-10-04T09:00:00-05:00";
    store.snapshot({
      state: state(),
      series: { glucose: [[t, 140]], heart_rate: [] },
      feed: [{ signal: "glucose", time: t, from: null, to: "in_range", value: 140 }],
      replay: { type: "replay", status: "paused", cursor: t, start: t, end: t, speed: 120 },
    });
    const v = store.getSnapshot();
    expect(v.series.glucose).toEqual([{ t: Date.parse(t), v: 140 }]);
    expect(v.feed.map((f) => f.signal)).toEqual(["glucose"]);
    expect(v.replay?.status).toBe("paused");
    store.setReplay({ status: "playing", cursor: t, start: t, end: t, speed: 300 });
    expect(store.getSnapshot().replay).toEqual({ status: "playing", cursor: t, start: t, end: t, speed: 300 });
  });

  test("a snapshot without context keeps the buffers", () => {
    const store = new TwinStore({ state: state(), transitions: [], series: { glucose: [{ t: 1, v: 99 }] } });
    store.snapshot({ state: state({ version: 2 }) });
    expect(store.getSnapshot().series.glucose).toEqual([{ t: 1, v: 99 }]);
  });
});

describe("extendSeries", () => {
  test("appends only newer readings and replaces a same-time value", () => {
    const s0 = { glucose: [{ t: 1000, v: 100 }], heart_rate: [] };
    const at = (iso: number) => new Date(iso).toISOString();
    const s1 = extendSeries(s0, state({ glucose: { ...signal, value: 110, time: at(1000), trend: null, rate_mg_dl_min: null } }));
    expect(s1.glucose).toEqual([{ t: 1000, v: 110 }]);
    const s2 = extendSeries(s1, state({ glucose: { ...signal, value: 90, time: at(500), trend: null, rate_mg_dl_min: null } }));
    expect(s2).toBe(s1); // a late reading never rewrites the line
  });
});
