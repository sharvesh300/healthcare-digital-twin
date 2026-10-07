import { ArrowDownRight, ArrowRight, ArrowUpRight, Info, OctagonAlert, TriangleAlert } from "lucide-react";

import { BandChip } from "@/components/vitals/chips";
import type { ForecastModel, ForecastPoint } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { fmtChange, KIND_SEVERITY, SEVERITY_COLOR, typicalError, WARNING_TITLE, worstKind } from "@/lib/predict/format";
import { fmtNumber, fmtTime } from "@/lib/twin/format";

const SEVERITY_ICON = { danger: OctagonAlert, warning: TriangleAlert, info: Info } as const;

/** One card per horizon: what the model expects at +15, +30, +45 and +60 minutes. Dashed edges:
 *  these are model estimates, never styled like a measurement. */
export function HorizonCards({ forecast, model }: { forecast: ForecastPoint[]; model: ForecastModel | null }) {
  return (
    <ol className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Forecast by horizon">
      {forecast.map((f) => <HorizonCard key={f.horizon_min} f={f} error={typicalError(model, f.horizon_min)} />)}
    </ol>
  );
}

function HorizonCard({ f, error }: { f: ForecastPoint; error: string | null }) {
  const kind = worstKind(f.warnings);
  const severity = kind ? KIND_SEVERITY[kind] : null;
  const loud = severity === "danger" || severity === "warning";
  const color = severity ? SEVERITY_COLOR[severity] : undefined;
  const Change = f.change >= 5 ? ArrowUpRight : f.change <= -5 ? ArrowDownRight : ArrowRight;
  const Icon = severity ? SEVERITY_ICON[severity] : null;
  return (
    <li
      className={cn("relative flex flex-col rounded-card border border-dashed bg-surface p-4 shadow-card",
        loud ? "border-transparent" : "border-line-strong")}
      style={loud ? { boxShadow: `inset 0 0 0 1.5px ${color}`, background: `color-mix(in srgb, ${color} 5%, var(--surface))` } : undefined}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-semibold text-ink">+{f.horizon_min} min</span>
        <span className="text-xs tabular-nums text-ink-3">{fmtTime(f.time)}</span>
      </div>
      <div className="mt-2 flex items-baseline gap-1.5">
        <span className="text-metric font-semibold tabular-nums text-ink">{fmtNumber(f.glucose)}</span>
        <span className="text-xs font-medium text-ink-3">mg/dL</span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <BandChip status={f.band} size="sm" />
        <span className="inline-flex items-center gap-0.5 text-xs tabular-nums text-ink-2" title="Change from now">
          <Change aria-hidden size={13} strokeWidth={2.4} />
          {fmtChange(f.change)}
        </span>
      </div>
      <p className="mt-2 text-[11px] tabular-nums text-ink-3">
        80 % range {fmtNumber(f.low)}–{fmtNumber(f.high)}
        {error && <span className="block">{error}</span>}
      </p>
      {kind && Icon && (
        <p className="mt-auto flex items-center gap-1.5 pt-3 text-xs font-medium" style={{ color: loud ? color : "var(--ink-3)" }}>
          <Icon aria-hidden size={13} strokeWidth={2.4} />
          {WARNING_TITLE[kind]}
          {f.warnings.length > 1 && <span className="font-normal text-ink-3">+{f.warnings.length - 1}</span>}
        </p>
      )}
    </li>
  );
}
