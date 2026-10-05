// Role names for SVG and chart code, so components never carry raw hex. Values live in
// app/globals.css (:root).

import type { SignalKey } from "@/lib/api/types";

export const vital = {
  glucose: "var(--vital-glucose)",
  heart: "var(--vital-heart)",
  oxygen: "var(--vital-oxygen)",
  activity: "var(--vital-activity)",
  sleep: "var(--vital-sleep)",
} as const;

export const band = {
  very_low: "var(--band-very-low)",
  low: "var(--band-low)",
  in_range: "var(--band-in-range)",
  high: "var(--band-high)",
  very_high: "var(--band-very-high)",
} as const;

export type BandKey = keyof typeof band;
export const isBand = (s: string | null | undefined): s is BandKey => !!s && s in band;

export const tone = {
  ok: "var(--status-ok)",
  warn: "var(--status-warn)",
  danger: "var(--status-danger)",
  neutral: "var(--ink-3)",
} as const;

/** The vital hue that identifies each signal (ink for the hue-less ones). */
export const signalHue: Record<SignalKey, string> = {
  glucose: vital.glucose,
  heart_rate: vital.heart,
  hrv_rmssd: vital.heart,
  spo2: vital.oxygen,
  respiration_rate: vital.oxygen,
  activity: vital.activity,
  steps_today: vital.activity,
  active_kcal: vital.activity,
  sleep: vital.sleep,
  skin_temp: "var(--ink-2)",
  stress: "var(--ink-2)",
  eda: "var(--ink-2)",
};

/** CGM consensus thresholds (mg/dL), as in the backend rules. */
export const GLUCOSE_LIMITS = { veryLow: 54, low: 70, high: 180, veryHigh: 250 } as const;

export function glucoseBand(v: number): BandKey {
  if (v < 54) return "very_low";
  if (v < 70) return "low";
  if (v <= 180) return "in_range";
  if (v <= 250) return "high";
  return "very_high";
}

/** Heart-rate band, as in the backend rules: low below 50, normal up to 100, then elevated. */
export function heartRateBand(v: number): "low" | "normal" | "elevated" {
  return v < 50 ? "low" : v <= 100 ? "normal" : "elevated";
}
