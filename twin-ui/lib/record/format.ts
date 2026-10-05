// Display helpers for the patient record: dates with years, result values, visit classes.

import type { Flag, MeasureSummary, Range, ResultBrief } from "@/lib/api/types";
import { fmtNumber, TWIN_TZ } from "@/lib/twin/format";

const dayFmt = new Intl.DateTimeFormat("en-US", { timeZone: TWIN_TZ, month: "short", day: "numeric", year: "numeric" });
const monthFmt = new Intl.DateTimeFormat("en-US", { timeZone: TWIN_TZ, month: "short", year: "numeric" });
const yearFmt = new Intl.DateTimeFormat("en-US", { timeZone: TWIN_TZ, year: "numeric" });

/** "Aug 15, 2024" */
export const fmtDay = (iso: string | number | null | undefined) => (iso == null ? "—" : dayFmt.format(new Date(iso)));
/** "Aug 2024" */
export const fmtMonth = (iso: string | number | null | undefined) => (iso == null ? "—" : monthFmt.format(new Date(iso)));
export const fmtYear = (iso: string | number) => yearFmt.format(new Date(iso));

/** "3 d", "5 h", "45 min" */
export function fmtDuration(hours: number | null | undefined): string | null {
  if (hours == null) return null;
  if (hours >= 24) return `${Math.round(hours / 24)} d`;
  if (hours >= 1) return `${Math.round(hours)} h`;
  return `${Math.max(1, Math.round(hours * 60))} min`;
}

/** "2 years", "9 days" */
export function fmtDays(days: number | null | undefined): string | null {
  if (days == null) return null;
  if (days >= 365) return `${Math.round(days / 365)} year${Math.round(days / 365) === 1 ? "" : "s"}`;
  if (days >= 60) return `${Math.round(days / 30)} months`;
  return `${days} day${days === 1 ? "" : "s"}`;
}

type Measured = Pick<MeasureSummary, "analytes" | "digits">;

/** A result as it reads: "131", "128/82" (blood pressure), or the coded answer. */
export function resultValue(m: Measured, r: Pick<ResultBrief, "values" | "text"> | null | undefined): string {
  if (!r) return "—";
  if (r.text) return r.text;
  const parts = m.analytes.map((a) => r.values[a]).filter((v) => v != null);
  return parts.length ? parts.map((v) => fmtNumber(v, m.digits)).join("/") : "—";
}

/** Change from the previous result in the first component ("+0.4", "−6"), or null. */
export function resultDelta(m: MeasureSummary): string | null {
  const a = m.analytes[0];
  const now = m.latest.values[a];
  const before = m.previous?.values[a];
  if (now == null || before == null) return null;
  const d = now - before;
  if (Math.abs(d) < 10 ** -m.digits / 2) return "no change";
  return `${d > 0 ? "+" : "−"}${fmtNumber(Math.abs(d), m.digits)}`;
}

/** "70–99", "< 100", "≥ 40", per analyte joined with "/" for blood pressure. */
export function rangeText(m: Pick<MeasureSummary, "ranges" | "analytes" | "digits">): string | null {
  const one = (r: Range | null) => {
    if (!r) return null;
    const [lo, hi] = r;
    if (lo != null && hi != null) return `${fmtNumber(lo, m.digits)}–${fmtNumber(hi, m.digits)}`;
    if (hi != null) return `≤ ${fmtNumber(hi, m.digits)}`;
    if (lo != null) return `≥ ${fmtNumber(lo, m.digits)}`;
    return null;
  };
  const parts = m.analytes.map((a) => one(m.ranges[a] ?? null));
  return parts.every((p) => p == null) ? null : parts.map((p) => p ?? "—").join(" / ");
}

export const FLAG_LABEL: Record<Flag, string> = { high: "High", low: "Low", normal: "Normal" };

export const VISIT_CLASS: Record<string, string> = {
  ambulatory: "Clinic visit",
  emergency: "Emergency",
  inpatient: "Inpatient stay",
  virtual: "Virtual visit",
  home: "Home visit",
};
export const visitClass = (c: string) => VISIT_CLASS[c] ?? c;

/** "warfarin" → "Warfarin" (RxNorm ingredient names are lower case). */
export const capitalise = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** "gmi_inconsistent" → "Gmi inconsistent"; "consistent" → "Consistent". */
export const titleCaseStatus = (s: string | null | undefined) => (s ? capitalise(s.replace(/_/g, " ")) : "—");
