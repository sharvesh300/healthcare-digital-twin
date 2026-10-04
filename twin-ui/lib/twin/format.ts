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

/** Device model for display: "Twin simulator Live CGM (simulated)" → "Live CGM (simulated)". */
export const deviceName = (source: string | null | undefined) => source?.replace(/^Twin (simulator|generator) /, "") ?? null;

export const isAsleep = (stage: string | null | undefined) => stage === "light" || stage === "deep" || stage === "rem";
