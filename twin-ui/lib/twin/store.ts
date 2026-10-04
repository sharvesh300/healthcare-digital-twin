// The live twin on the client: one small external store per patient, read with
// useSyncExternalStore. Snapshots replace the state; deltas (flat paths such as
// "glucose.status") are applied immutably, in version order. Glucose and heart-rate points
// are kept in ring buffers for sparklines and the live tail of the charts.

import type { LiveMessage, ReplayProgress, SnapshotMessage, Transition, TwinState } from "@/lib/api/types";

export type Point = { t: number; v: number };
export type ConnStatus = "connecting" | "live" | "reconnecting" | "offline" | "not_found";
export type SeriesKey = "glucose" | "heart_rate";
export interface FeedItem extends Transition {
  id: string;
}

export interface TwinView {
  state: TwinState;
  status: ConnStatus;
  feed: FeedItem[];
  series: Record<SeriesKey, Point[]>;
  /** increments each time a signal's status changes: keys one-shot animations */
  pulse: Partial<Record<Transition["signal"], number>>;
  /** set while viewing a replay: the replay clock and controls' state */
  replay: ReplayProgress | null;
}

export interface TwinInit {
  state: TwinState;
  transitions: Transition[];
  series: Partial<Record<SeriesKey, Point[]>>;
}

const KEEP_MS = 26 * 3600 * 1000;
const FEED_MAX = 60;
const SERIES: SeriesKey[] = ["glucose", "heart_rate"];

export const feedId = (t: Transition) => `${t.signal}|${t.time}|${t.to}`;

/** Apply flat-path changes ("glucose.value", "streaming") to a copy of the state. */
export function applyChanges(state: TwinState, changes: Record<string, unknown>): TwinState {
  const next: Record<string, unknown> = { ...state };
  for (const [path, value] of Object.entries(changes)) {
    const dot = path.indexOf(".");
    if (dot < 0) {
      next[path] = value;
      continue;
    }
    const key = path.slice(0, dot);
    const field = path.slice(dot + 1);
    next[key] = { ...(next[key] as object), [field]: value };
  }
  return next as unknown as TwinState;
}

/** Append the state's latest glucose / heart-rate reading to the buffers if it is new. */
export function extendSeries(series: Record<SeriesKey, Point[]>, state: TwinState): Record<SeriesKey, Point[]> {
  let out = series;
  for (const key of SERIES) {
    const s = state[key];
    const v = typeof s.value === "number" ? s.value : Number(s.value);
    if (!s.time || s.value == null || !Number.isFinite(v)) continue;
    const t = Date.parse(s.time);
    const pts = out[key];
    const last = pts[pts.length - 1];
    if (last && t < last.t) continue;
    let next = last && t === last.t ? [...pts.slice(0, -1), { t, v }] : [...pts, { t, v }];
    if (next.length > 2000 || next[0].t < t - KEEP_MS) next = next.filter((p) => p.t >= t - KEEP_MS);
    out = { ...out, [key]: next };
  }
  return out;
}

export class TwinStore {
  private view: TwinView;
  private listeners = new Set<() => void>();
  private awaitingSnapshot = false;

  constructor(init: TwinInit) {
    const series = { glucose: init.series.glucose ?? [], heart_rate: init.series.heart_rate ?? [] };
    const feed = dedupe(init.transitions.map((t) => ({ ...t, id: feedId(t) })));
    this.view = { state: init.state, status: "connecting", feed, series: extendSeries(series, init.state), pulse: {}, replay: null };
  }

  get version(): number {
    return this.view.state.version;
  }

  getSnapshot = (): TwinView => this.view;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private set(next: Partial<TwinView>) {
    this.view = { ...this.view, ...next };
    this.listeners.forEach((l) => l());
  }

  setStatus(status: ConnStatus) {
    if (status !== this.view.status) this.set({ status });
  }

  /** A snapshot replaces the state, and the chart buffers and feed when it carries them. */
  snapshot(msg: Pick<SnapshotMessage, "state" | "series" | "feed" | "replay">) {
    this.awaitingSnapshot = false;
    const base = msg.series
      ? {
          glucose: toPoints(msg.series.glucose),
          heart_rate: toPoints(msg.series.heart_rate),
        }
      : this.view.series;
    const feed = msg.feed ? dedupe(msg.feed.map((t) => ({ ...t, id: feedId(t) }))) : this.view.feed;
    const replay = msg.replay ? progressOf(msg.replay) : this.view.replay;
    this.set({ state: msg.state, series: extendSeries(base, msg.state), feed, replay });
  }

  setReplay(progress: ReplayProgress) {
    const r = this.view.replay;
    if (!r || r.status !== progress.status || r.cursor !== progress.cursor || r.speed !== progress.speed) {
      this.set({ replay: progressOf(progress) });
    }
  }

  /** Apply a delta. Returns false when a version was missed: the caller asks for a resync. */
  delta(msg: Extract<LiveMessage, { type: "delta" }>): boolean {
    if (this.awaitingSnapshot) return true;
    if (msg.version <= this.version) return true; // already contained in the snapshot
    if (msg.version !== this.version + 1) {
      this.awaitingSnapshot = true;
      return false;
    }
    const state = { ...applyChanges(this.view.state, msg.changes), version: msg.version };
    const pulse = { ...this.view.pulse };
    for (const t of msg.transitions) pulse[t.signal] = (pulse[t.signal] ?? 0) + 1;
    const fresh = msg.transitions.map((t) => ({ ...t, id: feedId(t) })).reverse();
    this.set({
      state,
      series: extendSeries(this.view.series, state),
      feed: fresh.length ? dedupe([...fresh, ...this.view.feed]) : this.view.feed,
      pulse,
    });
    return true;
  }
}

const toPoints = (pts: [string, number][] | undefined): Point[] => (pts ?? []).map(([t, v]) => ({ t: Date.parse(t), v }));
const progressOf = ({ status, cursor, start, end, speed }: ReplayProgress): ReplayProgress => ({ status, cursor, start, end, speed });

function dedupe(items: FeedItem[]): FeedItem[] {
  const seen = new Set<string>();
  return items.filter((i) => !seen.has(i.id) && seen.add(i.id)).slice(0, FEED_MAX);
}
