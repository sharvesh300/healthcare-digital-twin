// Display formatting: one clinic time zone on server and client (no hydration drift), numbers
// per metric, and the human labels for bands, trends, stages and transitions.

import type { GlucoseTrend, SignalKey, Transition } from "@/lib/api/types";

export const TWIN_TZ = process.env.NEXT_PUBLIC_TWIN_TZ ?? "America/Chicago";

const timeFmt = new Intl.DateTimeFormat("en-US", { timeZone: TWIN_TZ, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const timeSecFmt = new Intl.DateTimeFormat("en-US", {
  timeZone: TWIN_TZ,
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});
const dateFmt = new Intl.DateTimeFormat("en-US", { timeZone: TWIN_TZ, month: "short", day: "numeric" });
const dayKeyFmt = new Intl.DateTimeFormat("en-CA", { timeZone: TWIN_TZ, year: "numeric", month: "2-digit", day: "2-digit" });
const tzNameFmt = new Intl.DateTimeFormat("en-US", { timeZone: TWIN_TZ, timeZoneName: "short" });

export const fmtTime = (iso: string | number | null | undefined, seconds = false) =>
  iso == null ? "—" : (seconds ? timeSecFmt : timeFmt).format(new Date(iso));
export const fmtDate = (iso: string | number | null | undefined) => (iso == null ? "—" : dateFmt.format(new Date(iso)));
export const fmtDateTime = (iso: string | null | undefined) => (iso == null ? "—" : `${fmtDate(iso)}, ${fmtTime(iso)}`);
/** yyyy-mm-dd in the clinic time zone: groups points into the twin's local days. */
export const dayKey = (t: number | string) => dayKeyFmt.format(new Date(t));
export const tzAbbr = (t: number | string = Date.now()) =>
  tzNameFmt.formatToParts(new Date(t)).find((p) => p.type === "timeZoneName")?.value ?? "";

const intFmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
export function fmtNumber(value: number | string | null | undefined, digits = 0): string {
  if (value == null || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return String(value);
  return digits === 0 ? intFmt.format(n) : n.toFixed(digits);
}

/** "just now", "12 s ago", "4 min ago", "3 h ago", "2 d ago". Future (a fast replay's device clock) reads as now. */
export function fmtAge(iso: string | null | undefined, now: number): string {
  if (!iso) return "no data";
  const s = Math.round((now - Date.parse(iso)) / 1000);
  if (s < 5) return "just now";
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export const titleCase = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export const BAND_LABEL: Record<string, string> = {
  very_low: "Very low",
  low: "Low",
  in_range: "In range",
  high: "High",
  very_high: "Very high",
  stale: "Stale",
};

export const TREND_LABEL: Record<GlucoseTrend, string> = {
  rising_fast: "Rising fast",
  rising: "Rising",
  steady: "Steady",
  falling: "Falling",
  falling_fast: "Falling fast",
};

/** Arrow angle for a trend, degrees from "right" (steady); negative = up. */
export const TREND_ANGLE: Record<GlucoseTrend, number> = {
  rising_fast: -90,
  rising: -45,
  steady: 0,
  falling: 45,
  falling_fast: 90,
};

export const SIGNAL_LABEL: Record<Transition["signal"], string> = {
  glucose: "Glucose",
  glucose_trend: "Glucose trend",
  heart_rate: "Heart rate",
  activity: "Activity",
  sleep: "Sleep",
  spo2: "SpO₂",
};

export const STATUS_LABEL: Record<string, string> = {
  ...BAND_LABEL,
  ...TREND_LABEL,
  normal: "Normal",
  elevated: "Elevated",
  borderline: "Borderline",
  sedentary: "Sedentary",
  light: "Light",
  moderate: "Moderate",
  vigorous: "Vigorous",
  awake: "Awake",
  deep: "Deep",
  rem: "REM",
};
export const statusLabel = (s: string | null | undefined) => (s ? (STATUS_LABEL[s] ?? titleCase(s)) : "—");

/** Tone of a non-glucose status chip; UI status colours, never a vital hue. */
export function statusTone(signal: SignalKey | Transition["signal"], status: string | null): "ok" | "warn" | "danger" | "neutral" {
  if (!status) return "neutral";
  if (status === "stale") return "neutral";
  if (signal === "heart_rate") return status === "normal" ? "ok" : "warn";
  if (signal === "spo2") return status === "normal" ? "ok" : status === "borderline" ? "warn" : "danger";
  return "neutral";
}

const ABNORMAL: Partial<Record<Transition["signal"], string[]>> = {
  glucose: ["very_low", "low", "high", "very_high"],
  glucose_trend: ["rising_fast", "falling_fast"],
  heart_rate: ["low", "elevated"],
  spo2: ["borderline", "low"],
};
/** A status worth a look: out-of-range glucose, a fast glucose swing, heart rate or SpO₂ out of band. */
export const isAbnormal = (signal: Transition["signal"], status: string | null | undefined) =>
  !!status && (ABNORMAL[signal]?.includes(status) ?? false);

/** Device model for display: "Twin simulator Live CGM (simulated)" → "Live CGM (simulated)". */
export const deviceName = (source: string | null | undefined) => source?.replace(/^Twin (simulator|generator) /, "") ?? null;

export const isAsleep = (stage: string | null | undefined) => stage === "light" || stage === "deep" || stage === "rem";

// ── clinic-zone date-time inputs (<input type="datetime-local"> holds a zone-less "YYYY-MM-DDTHH:mm") ──

const partsFmt = new Intl.DateTimeFormat("en-US", {
  timeZone: TWIN_TZ,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

function zoneParts(ms: number): Record<string, number> {
  return Object.fromEntries(
    partsFmt.formatToParts(new Date(ms)).filter((p) => p.type !== "literal").map((p) => [p.type, Number(p.value)]),
  );
}

/** Offset of the clinic zone from UTC at `ms`, in ms (e.g. −5 h in CDT). */
function zoneOffset(ms: number): number {
  const p = zoneParts(ms);
  return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second) - Math.floor(ms / 1000) * 1000;
}

/** A time as a datetime-local value in the clinic zone. */
export function toZonedInput(t: number | string): string {
  const p = zoneParts(typeof t === "number" ? t : Date.parse(t));
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${p.year}-${pad(p.month)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}`;
}

/** A datetime-local value read as clinic time; null if incomplete. Correct across DST changes. */
export function fromZonedInput(value: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value);
  if (!m) return null;
  const guess = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
  const first = guess - zoneOffset(guess);
  return guess - zoneOffset(first);
}

/** "3 h", "1 h 30 min", "45 min", "18 s" */
export function fmtSpan(ms: number): string {
  if (ms < 60_000) return `${Math.max(1, Math.round(ms / 1000))} s`;
  const min = Math.round(ms / 60_000);
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h ? (m ? `${h} h ${m} min` : `${h} h`) : `${m} min`;
}
