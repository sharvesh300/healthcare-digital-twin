"use client";

import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";

import { niceTicks, useWidth } from "@/components/charts/scale";
import { BandChip } from "@/components/vitals/chips";
import type { ForecastPoint } from "@/lib/api/types";
import { fmtChange } from "@/lib/predict/format";
import { fmtNumber, fmtTime } from "@/lib/twin/format";
import type { Point } from "@/lib/twin/store";
import { band as bandColor, glucoseBand, GLUCOSE_LIMITS, isBand, vital } from "@/lib/tokens";

const HISTORY_MS = 3 * 3600_000;
const HISTORY_NARROW_MS = 90 * 60_000; // phones: give the future a readable share of the width
const NARROW_PX = 480;
const AFTER_MS = 65 * 60_000;
const GAP_MS = 20 * 60_000;

type Hover = { kind: "measured" | "actual"; p: Point } | { kind: "forecast"; f: ForecastPoint; t: number };

function linePath(pts: Point[], x: (t: number) => number, y: (v: number) => number): string {
  return pts.map((p, i) => `${i === 0 || p.t - pts[i - 1].t > GAP_MS ? "M" : "L"}${x(p.t).toFixed(1)} ${y(p.v).toFixed(1)}`).join("");
}

/** Measured glucose up to the origin, then the forecast: a tinted future region with the dashed
 *  forecast line, its hatched 80 % range, band-coloured horizon points and, for a past origin,
 *  the readings that actually followed (dotted). Model output never looks like a measurement. */
export function ForecastChart({ history, origin, forecast, actual, height = 280 }: {
  history: Point[];
  origin: Point;
  forecast: ForecastPoint[];
  actual: Point[];
  height?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<Hover | null>(null);
  const M = { l: 40, r: 16, t: 22, b: 28 };
  const W = Math.max(width, 10);
  const H = height;
  const iw = W - M.l - M.r;
  const ih = H - M.t - M.b;
  const start = origin.t - (W < NARROW_PX ? HISTORY_NARROW_MS : HISTORY_MS);
  const end = origin.t + AFTER_MS;
  const fc = useMemo(() => forecast.map((f) => ({ ...f, t: Date.parse(f.time) })), [forecast]);

  const [lo, hi] = useMemo(() => {
    const shown = history.filter((p) => p.t >= start);
    const vs = [...shown.map((p) => p.v), ...actual.map((p) => p.v), ...fc.flatMap((f) => [f.low, f.high]), origin.v,
      GLUCOSE_LIMITS.low, GLUCOSE_LIMITS.high];
    const a = Math.min(...vs);
    const b = Math.max(...vs);
    const pad = (b - a) * 0.08 || 5;
    return [a - pad, b + pad];
  }, [history, actual, fc, origin.v, start]);

  const x = (t: number) => M.l + ((t - start) / (end - start)) * iw;
  const y = (v: number) => M.t + ih - ((v - lo) / (hi - lo)) * ih;
  const ox = x(origin.t);

  const forecastLine = [origin, ...fc.map((f) => ({ t: f.t, v: f.glucose }))];
  const bandPath = fc.length
    ? `M${ox} ${y(origin.v)}${fc.map((f) => `L${x(f.t)} ${y(f.high)}`).join("")}` +
      `${[...fc].reverse().map((f) => `L${x(f.t)} ${y(f.low)}`).join("")}Z`
    : "";
  const limits: number[] = [GLUCOSE_LIMITS.low, GLUCOSE_LIMITS.high, GLUCOSE_LIMITS.veryHigh].filter((v) => v > lo && v < hi);
  const yTicks = [...new Set([...niceTicks(lo, hi), ...limits])].sort((a, b) => a - b).filter((v) => v >= lo && v <= hi);
  const visible = history.filter((p) => p.t >= start);
  const hourTicks: number[] = [];
  for (let t = Math.ceil(start / 3600_000) * 3600_000; t < origin.t - 15 * 60_000; t += 3600_000) hourTicks.push(t);
  // horizon labels need ~26 px each; on a narrow chart keep every other one
  const labelEvery = fc.length > 1 && x(fc[1].t) - x(fc[0].t) < 26 ? 2 : 1;

  const onMove = (e: React.PointerEvent<SVGRectElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - rect.left + M.l;
    const t = start + ((px - M.l) / iw) * (end - start);
    if (t > origin.t + 5 * 60_000 && fc.length) {
      const f = fc.reduce((a, b) => (Math.abs(b.t - t) < Math.abs(a.t - t) ? b : a));
      setHover({ kind: "forecast", f, t: f.t });
      return;
    }
    const pool = t > origin.t ? actual : visible;
    if (!pool.length) return setHover(null);
    const p = pool.reduce((a, b) => (Math.abs(b.t - t) < Math.abs(a.t - t) ? b : a));
    setHover({ kind: pool === actual ? "actual" : "measured", p });
  };

  const tip = hover && (hover.kind === "forecast" ? { t: hover.t, v: hover.f.glucose } : hover.p);

  return (
    <div ref={ref} className="relative w-full" style={{ height: H }}>
      {width > 0 && (
        <svg width={W} height={H} className="block overflow-visible" role="img"
          aria-label={`Measured glucose for the last 3 hours, ${fmtNumber(origin.v)} mg/dL now at ${fmtTime(origin.t)}; forecast ${
            fc.map((f) => `${fmtNumber(f.glucose)} at +${f.horizon_min} min`).join(", ")}`}>
          <defs>
            <pattern id="forecast-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="6" stroke={vital.glucose} strokeWidth="1.5" strokeOpacity="0.28" />
            </pattern>
            <linearGradient id="forecast-area" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" style={{ stopColor: vital.glucose, stopOpacity: 0.12 }} />
              <stop offset="100%" style={{ stopColor: vital.glucose, stopOpacity: 0 }} />
            </linearGradient>
          </defs>

          {/* target range 70–180 */}
          <rect x={M.l} width={iw} y={y(GLUCOSE_LIMITS.high)} height={y(GLUCOSE_LIMITS.low) - y(GLUCOSE_LIMITS.high)}
            fill="var(--band-in-range)" opacity={0.06} />
          {/* the future: tinted, labelled */}
          <rect x={ox} width={W - M.r - ox} y={M.t} height={ih} fill="var(--surface-2)" opacity={0.75} />
          <text x={ox + 8} y={M.t + 12} className="fill-ink-3 text-[10px] font-medium uppercase tracking-[0.06em]">Forecast</text>

          {yTicks.map((v) => {
            const limit = limits.includes(v);
            return (
              <g key={v}>
                <line x1={M.l} x2={W - M.r} y1={y(v)} y2={y(v)} stroke="var(--line-strong)" strokeWidth={1}
                  strokeDasharray={limit ? "3 4" : undefined} opacity={limit ? 0.9 : 0.4} />
                <text x={M.l - 8} y={y(v)} dy="0.32em" textAnchor="end" className="fill-ink-3 text-[11px] tabular-nums">{fmtNumber(v)}</text>
              </g>
            );
          })}
          {hourTicks.map((t) => (
            <text key={t} x={x(t)} y={H - 8} textAnchor="middle" className="fill-ink-3 text-[11px] tabular-nums">{fmtTime(t)}</text>
          ))}
          {fc.filter((_, i) => (fc.length - 1 - i) % labelEvery === 0).map((f) => (
            <text key={f.horizon_min} x={x(f.t)} y={H - 8} textAnchor="middle" className="fill-ink-2 text-[11px] font-medium tabular-nums">
              +{f.horizon_min}
            </text>
          ))}

          {/* measured history */}
          {visible.length > 1 && (
            <path d={`${linePath(visible, x, y)}L${x(visible[visible.length - 1].t)} ${M.t + ih}L${x(visible[0].t)} ${M.t + ih}Z`}
              fill="url(#forecast-area)" />
          )}
          <path d={linePath(visible, x, y)} fill="none" stroke={vital.glucose} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

          {/* what actually happened (past origins) */}
          {actual.length > 0 && (
            <g>
              <path d={linePath([origin, ...actual], x, y)} fill="none" stroke="var(--ink-2)" strokeWidth={1.75}
                strokeDasharray="1 4" strokeLinecap="round" />
              {actual.map((p) => <circle key={p.t} cx={x(p.t)} cy={y(p.v)} r={1.75} fill="var(--ink-2)" />)}
            </g>
          )}

          {/* forecast: hatched 80 % range, dashed line, band-coloured points */}
          {bandPath && (
            <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5, delay: 0.2 }}>
              <path d={bandPath} fill={vital.glucose} fillOpacity={0.07} />
              <path d={bandPath} fill="url(#forecast-hatch)" />
            </motion.g>
          )}
          {/* fades in rather than drawing in: a pathLength animation would replace the dash pattern */}
          <motion.path
            key={origin.t}
            d={linePath(forecastLine, x, y)}
            fill="none"
            stroke={vital.glucose}
            strokeWidth={2}
            strokeDasharray="6 5"
            strokeLinecap="round"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.5, delay: 0.15 }}
          />
          {fc.map((f, i) => {
            const c = isBand(f.band) ? bandColor[f.band] : vital.glucose;
            const active = hover?.kind === "forecast" && hover.f.horizon_min === f.horizon_min;
            return (
              <motion.g key={f.horizon_min} initial={{ opacity: 0, scale: 0.4 }} animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: 0.35 + i * 0.08, type: "spring", stiffness: 380, damping: 22 }}
                style={{ transformBox: "fill-box", transformOrigin: "center" }}>
                {active && <circle cx={x(f.t)} cy={y(f.glucose)} r={10} fill={c} opacity={0.18} />}
                <circle cx={x(f.t)} cy={y(f.glucose)} r={5} fill="var(--surface)" stroke={c} strokeWidth={2.5} />
              </motion.g>
            );
          })}

          {/* now */}
          <line x1={ox} x2={ox} y1={M.t - 6} y2={M.t + ih} stroke="var(--ink-2)" strokeWidth={1.25} />
          <text x={ox} y={M.t - 10} textAnchor="middle" className="fill-ink-2 text-[11px] font-medium tabular-nums">
            Now {fmtTime(origin.t)}
          </text>
          <circle cx={ox} cy={y(origin.v)} r={4.5} fill={vital.glucose} stroke="var(--surface)" strokeWidth={2} />

          {hover && tip && (
            <line x1={x(tip.t)} x2={x(tip.t)} y1={M.t} y2={M.t + ih} stroke="var(--ink-3)" strokeWidth={1} strokeDasharray="2 3" pointerEvents="none" />
          )}
          <rect x={M.l} y={M.t} width={iw} height={ih} fill="transparent" onPointerMove={onMove} onPointerLeave={() => setHover(null)} />
        </svg>
      )}
      <AnimatePresence>
        {hover && tip && (
          <motion.div
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.12 }}
            className="pointer-events-none absolute z-10 min-w-52 rounded-control border border-line bg-surface px-3 py-2 shadow-pop"
            style={{ left: Math.min(Math.max(x(tip.t) - 104, 0), W - 216), top: Math.max(y(tip.v) - 96, 0) }}
          >
            <div className="text-[11px] text-ink-3">
              {hover.kind === "forecast" ? `Forecast · +${hover.f.horizon_min} min · ${fmtTime(hover.t)}`
                : hover.kind === "actual" ? `What happened · ${fmtTime(hover.p.t)}` : `Measured · ${fmtTime(hover.p.t)}`}
            </div>
            <div className="mt-0.5 flex items-center justify-between gap-3">
              <span className="text-sm font-semibold tabular-nums text-ink">
                {fmtNumber(tip.v)} <span className="text-xs font-normal text-ink-3">mg/dL</span>
              </span>
              <BandChip status={hover.kind === "forecast" ? hover.f.band : glucoseBand(tip.v)} size="sm" />
            </div>
            {hover.kind === "forecast" && (
              <div className="mt-1 text-[11px] tabular-nums text-ink-3">
                80 % range {fmtNumber(hover.f.low)}–{fmtNumber(hover.f.high)} · {fmtChange(hover.f.change)} from now
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/** Line-style key for the chart. */
export function ForecastLegend({ withActual }: { withActual: boolean }) {
  const item = "inline-flex items-center gap-1.5";
  return (
    <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-ink-3">
      <span className={item}><svg width="18" height="6" aria-hidden><line x1="1" x2="17" y1="3" y2="3" stroke={vital.glucose} strokeWidth="2" strokeLinecap="round" /></svg>Measured</span>
      <span className={item}><svg width="18" height="6" aria-hidden><line x1="1" x2="17" y1="3" y2="3" stroke={vital.glucose} strokeWidth="2" strokeDasharray="4 3" /></svg>Forecast</span>
      <span className={item}><span aria-hidden className="h-2.5 w-4 rounded-[3px] border border-line" style={{ background: `repeating-linear-gradient(135deg, color-mix(in srgb, ${vital.glucose} 30%, transparent) 0 1.5px, transparent 1.5px 4px)` }} />80 % range</span>
      {withActual && (
        <span className={item}><svg width="18" height="6" aria-hidden><line x1="1" x2="17" y1="3" y2="3" stroke="var(--ink-2)" strokeWidth="2" strokeDasharray="1 3" strokeLinecap="round" /></svg>What happened</span>
      )}
      <span className={item}><span aria-hidden className="h-2.5 w-4 rounded-[3px]" style={{ background: "var(--band-in-range)", opacity: 0.25 }} />Target 70–180</span>
    </p>
  );
}
