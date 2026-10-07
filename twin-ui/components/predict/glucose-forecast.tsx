"use client";

import { ArrowRight, CalendarClock, LineChart, RefreshCw, RotateCcw, Sparkles } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState, useTransition } from "react";

import { Card, CardHeader } from "@/components/ui/card";
import { BandChip } from "@/components/vitals/chips";
import { TrendArrow } from "@/components/vitals/trend-arrow";
import type { GlucoseForecast } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { fmtDateTime, fmtNumber, fromZonedInput, toZonedInput, TREND_LABEL } from "@/lib/twin/format";

import { ForecastChart, ForecastLegend } from "./forecast-chart";
import { ForecastWarningBanner } from "./forecast-warning";
import { HorizonCards } from "./horizon-cards";
import { ModelInputs } from "./model-inputs";

const REFRESH_MS = 5 * 60_000; // the CGM reading interval

/** The Predict tab's glucose forecast: origin controls, warning banner, chart, horizon cards,
 *  inputs and accuracy. `latest`: the forecast starts from the newest reading and refreshes
 *  every 5 minutes; otherwise it starts from `?at=` and shows what happened next. */
export function GlucoseForecastView({ data, latest }: { data: GlucoseForecast; latest: boolean }) {
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();
  const originT = data.origin ? Date.parse(data.origin.time) : Date.parse(data.at);
  const shown = toZonedInput(latest ? originT : Date.parse(data.at));
  // null: the picker follows the forecast shown (also across the 5-minute refreshes)
  const [draft, setDraft] = useState<string | null>(null);
  const picked = draft != null && draft !== shown;

  useEffect(() => {
    if (!latest) return;
    const timer = setInterval(() => startTransition(() => router.refresh()), REFRESH_MS);
    return () => clearInterval(timer);
  }, [latest, router]);

  const go = (at: number | null) =>
    startTransition(() => router.push(at == null ? pathname : `${pathname}?at=${encodeURIComponent(new Date(at).toISOString())}`, { scroll: false }));

  const history = useMemo(() => data.history.map((p) => ({ t: Date.parse(p.t), v: p.v })), [data.history]);
  const actual = useMemo(() => data.actual.map((p) => ({ t: Date.parse(p.t), v: p.v })), [data.actual]);

  return (
    <div className={cn("space-y-4 transition-opacity", pending && "opacity-70")} aria-busy={pending}>
      <Card className="p-5">
        <CardHeader
          icon={<LineChart aria-hidden size={14} className="text-vital-glucose" />}
          title="Glucose forecast"
          meta={data.model ? data.model.label : undefined}
          right={
            <span className="hatch inline-flex items-center gap-1.5 rounded-full border border-dashed border-line-strong px-2.5 py-1 text-[11px] font-medium text-ink-2">
              <Sparkles aria-hidden size={12} /> Model estimate
            </span>
          }
        />
        <div className="mt-4 flex flex-wrap items-end justify-between gap-4">
          {data.origin ? (
            <div>
              <div className="text-xs text-ink-3">{latest ? "Latest reading" : "Forecast from"} · {fmtDateTime(data.origin.time)}</div>
              <div className="mt-1 flex flex-wrap items-center gap-2.5">
                <span className="text-metric font-semibold tabular-nums text-ink">{fmtNumber(data.origin.glucose)}</span>
                <span className="text-sm text-ink-3">mg/dL</span>
                <BandChip status={data.origin.band} />
                {data.origin.trend && (
                  <span className="inline-flex items-center gap-1 text-sm text-ink-2">
                    <TrendArrow trend={data.origin.trend} size={16} className="text-ink" />
                    {TREND_LABEL[data.origin.trend]}
                  </span>
                )}
              </div>
            </div>
          ) : <div className="text-sm text-ink-3">No CGM reading to forecast from.</div>}
          {/* One button, whatever applies: show the picked time, refresh the latest, or go back to it. */}
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              const t = picked ? fromZonedInput(draft) : null;
              if (picked && t != null) go(t);
              else if (latest) startTransition(() => router.refresh());
              else go(null);
            }}
          >
            <label className="flex items-center gap-2 text-xs text-ink-3">
              <CalendarClock aria-hidden size={14} />
              <span className="sr-only sm:not-sr-only">Forecast from</span>
              <input type="datetime-local" value={draft ?? shown} onChange={(e) => setDraft(e.target.value)}
                className="rounded-control border border-line bg-surface px-2 py-1.5 text-sm tabular-nums text-ink" />
            </label>
            <button type="submit"
              className="inline-flex items-center gap-1.5 rounded-control bg-primary px-3 py-1.5 text-sm font-medium text-white shadow-card hover:bg-primary-strong">
              {picked ? <ArrowRight aria-hidden size={14} />
                : latest ? <RefreshCw aria-hidden size={14} className={pending ? "animate-spin" : undefined} />
                : <RotateCcw aria-hidden size={14} />}
              {picked ? "Show forecast" : latest ? "Refresh" : "Back to latest"}
            </button>
          </form>
        </div>

        <div className="mt-4">
          {data.unavailable ? (
            <p className="hatch mb-3 rounded-control border border-dashed border-line-strong px-3 py-2 text-sm text-ink-2">
              No forecast here: {data.unavailable.reason}.
            </p>
          ) : null}
          {data.origin && (
            <ForecastChart history={history} origin={{ t: originT, v: data.origin.glucose }} forecast={data.forecast} actual={actual} />
          )}
          <div className="mt-2">
            <ForecastLegend withActual={actual.length > 0} />
          </div>
        </div>
      </Card>

      <ForecastWarningBanner warnings={data.warnings} />
      {data.forecast.length > 0 && <HorizonCards forecast={data.forecast} model={data.model} />}
      <ModelInputs data={data} />
      <p className="text-xs leading-relaxed text-ink-3">{data.caveat}</p>
    </div>
  );
}
