// Display helpers for the glucose forecast (Predict tab). Pure, so they're unit-tested.

import type { ForecastModel, ForecastSeverity, ForecastWarning, ForecastWarningKind } from "@/lib/api/types";
import { tone } from "@/lib/tokens";

/** Severity of each warning kind, as in src/twin/prediction/rules.py. */
export const KIND_SEVERITY: Record<ForecastWarningKind, ForecastSeverity> = {
  very_high: "danger",
  very_low: "danger",
  high: "warning",
  low: "warning",
  spike: "warning",
  possible_high: "info",
  possible_low: "info",
};

export const WARNING_TITLE: Record<ForecastWarningKind, string> = {
  spike: "Spike likely",
  very_high: "Very high",
  high: "Above range",
  low: "Below range",
  very_low: "Very low",
  possible_high: "Could go above 180",
  possible_low: "Could go below 70",
};

export const SEVERITY_COLOR: Record<ForecastSeverity, string> = {
  danger: tone.danger,
  warning: tone.warn,
  info: "var(--ink-3)",
};

const RANK: Record<ForecastSeverity, number> = { danger: 0, warning: 1, info: 2 };

/** Most severe first, then soonest (the API already sends them this way; the UI doesn't rely on it). */
export const sortWarnings = (ws: ForecastWarning[]) =>
  [...ws].sort((a, b) => RANK[a.severity] - RANK[b.severity] || a.horizon_min - b.horizon_min);

/** The warning to headline: the most severe, soonest. Info-only forecasts get no banner. */
export function headline(ws: ForecastWarning[]): ForecastWarning | null {
  const top = sortWarnings(ws)[0];
  return top && top.severity !== "info" ? top : null;
}

/** The most severe kind among a horizon's warnings, or null. */
export function worstKind(kinds: ForecastWarningKind[]): ForecastWarningKind | null {
  return [...kinds].sort((a, b) => RANK[KIND_SEVERITY[a]] - RANK[KIND_SEVERITY[b]])[0] ?? null;
}

/** "+12", "−8", "±0" (mg/dL change from now; true minus sign). */
export function fmtChange(n: number): string {
  const r = Math.round(n);
  return r > 0 ? `+${r}` : r < 0 ? `−${Math.abs(r)}` : "±0";
}

/** The model's held-out test RMSE at a horizon, as "±22 mg/dL typical error", or null. */
export function typicalError(model: ForecastModel | null, horizon: number): string | null {
  const v = model?.test_rmse[String(horizon)];
  return v == null ? null : `±${Math.round(v)} mg/dL typical error`;
}
