"use client";

import { AnimatePresence, motion } from "motion/react";
import { useRouter } from "next/navigation";
import { useLayoutEffect, useRef, useState } from "react";

import type { MeasureDetail } from "@/lib/api/types";
import { fmtDay, FLAG_LABEL, resultValue } from "@/lib/record/format";
import { fmtNumber } from "@/lib/twin/format";
import { tone } from "@/lib/tokens";

const SERIES = ["var(--primary)", "var(--vital-oxygen)"];
const ANALYTE_LABEL: Record<string, string> = { sbp: "Systolic", dbp: "Diastolic" };

function niceTicks(lo: number, hi: number, count = 4): number[] {
  const raw = (hi - lo) / count;
  const mag = 10 ** Math.floor(Math.log10(raw || 1));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? mag * 10;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

/** Every result of one test over time: a line per component (two for blood pressure), the
 *  reference range shaded (or its limits dashed), out-of-range results ringed. Hover shows
 *  the result; a click opens the visit it was recorded at. */
export function ResultsChart({ detail, visitBase, height = 240 }: { detail: MeasureDetail; visitBase: string; height?: number }) {
  const router = useRouter();
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [hover, setHover] = useState<number | null>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const m = detail.measure;
  const results = detail.results.filter((r) => m.analytes.some((a) => r.values[a] != null));
  if (results.length === 0) return null;

  const M = { l: 44, r: 16, t: 12, b: 28 };
  const W = Math.max(width, 10);
  const iw = W - M.l - M.r;
  const ih = height - M.t - M.b;
  const times = results.map((r) => Date.parse(r.at));
  let t0 = Math.min(...times);
  let t1 = Math.max(...times);
  if (t1 - t0 < 30 * 86400_000) {
    t0 -= 15 * 86400_000;
    t1 += 15 * 86400_000;
  }
  const tpad = (t1 - t0) * 0.04;
  t0 -= tpad;
  t1 += tpad;
  const values = results.flatMap((r) => m.analytes.map((a) => r.values[a]).filter((v): v is number => v != null));
  const bounds: number[] = [];
  for (const a of m.analytes) for (const b of m.ranges[a] ?? []) if (b != null) bounds.push(b);
  let lo = Math.min(...values, ...bounds);
  let hi = Math.max(...values, ...bounds);
  const pad = (hi - lo) * 0.12 || Math.abs(hi) * 0.1 || 1;
  lo -= pad;
  hi += pad;
  const x = (t: number) => M.l + ((t - t0) / (t1 - t0)) * iw;
  const y = (v: number) => M.t + ih - ((v - lo) / (hi - lo)) * ih;
  const single = m.analytes.length === 1 ? m.ranges[m.analytes[0]] : null;
  const yTicks = niceTicks(lo, hi).filter((v) => v >= lo && v <= hi);
  // as many decimals as the tick step needs (0.5 → 1, 0.25 → 2)
  const tickStep = yTicks.length > 1 ? yTicks[1] - yTicks[0] : 1;
  const tickDigits = Math.min(2, Math.max(0, -Math.floor(Math.log10(tickStep) + 1e-9) + (tickStep % 1 && (tickStep * 10) % 1 ? 1 : 0)));

  const spanYears = (t1 - t0) / (365 * 86400_000);
  const xTicks: number[] = [];
  if (spanYears >= 2) {
    const step = Math.max(1, Math.ceil(spanYears / 7));
    for (let yr = new Date(t0).getUTCFullYear() + 1; Date.UTC(yr, 0, 1) <= t1; yr += step) xTicks.push(Date.UTC(yr, 0, 1));
  } else {
    const d = new Date(t0);
    const step = Math.max(1, Math.ceil((spanYears * 12) / 6));
    for (let mo = d.getUTCMonth() + 1, yr = d.getUTCFullYear(); ; mo += step) {
      const t = Date.UTC(yr, mo, 1);
      if (t > t1) break;
      xTicks.push(t);
    }
  }
  const tickLabel = (t: number) =>
    spanYears >= 2 ? String(new Date(t).getUTCFullYear()) : new Date(t).toLocaleDateString("en-US", { month: "short", year: "2-digit", timeZone: "UTC" });

  const nearest = (e: React.MouseEvent<SVGRectElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const t = t0 + ((e.clientX - rect.left) / rect.width) * (t1 - t0);
    let best = 0;
    times.forEach((tt, i) => Math.abs(tt - t) < Math.abs(times[best] - t) && (best = i));
    return best;
  };
  const open = (i: number) => {
    const v = results[i].visit;
    if (v) router.push(`${visitBase}/${v.encounter_id}`);
  };
  const h = hover != null ? results[hover] : null;

  return (
    <div ref={ref} className="relative w-full" style={{ height }}>
      {width > 0 && (
        <svg width={W} height={height} className="block overflow-visible" role="img"
          aria-label={`${m.display}: ${results.length} results from ${fmtDay(results[0].at)} to ${fmtDay(results[results.length - 1].at)}`}>
          {single && (single[0] != null || single[1] != null) && (
            <rect x={M.l} width={iw} y={y(single[1] ?? hi)} height={Math.max(0, y(single[0] ?? lo) - y(single[1] ?? hi))}
              fill="var(--band-in-range)" opacity={0.08} />
          )}
          {!single && m.analytes.map((a, i) => {
            const limit = m.ranges[a]?.[1];
            return limit == null ? null : (
              <line key={a} x1={M.l} x2={W - M.r} y1={y(limit)} y2={y(limit)} stroke={SERIES[i]} strokeDasharray="4 4" opacity={0.5} />
            );
          })}
          {yTicks.map((v) => (
            <g key={v}>
              <line x1={M.l} x2={W - M.r} y1={y(v)} y2={y(v)} stroke="var(--line)" />
              <text x={M.l - 8} y={y(v)} dy="0.32em" textAnchor="end" className="fill-ink-3 text-[11px] tabular-nums">{fmtNumber(v, tickDigits)}</text>
            </g>
          ))}
          {xTicks.map((t) => (
            <text key={t} x={x(t)} y={height - 8} textAnchor="middle" className="fill-ink-3 text-[11px] tabular-nums">{tickLabel(t)}</text>
          ))}
          {m.analytes.map((a, si) => {
            const pts = results.map((r, i) => [times[i], r.values[a]] as const).filter(([, v]) => v != null) as [number, number][];
            const d = pts.map(([t, v], i) => `${i ? "L" : "M"}${x(t).toFixed(1)} ${y(v).toFixed(1)}`).join("");
            return (
              <g key={a}>
                <motion.path d={d} fill="none" stroke={SERIES[si]} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round"
                  initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.8, ease: [0.2, 0.8, 0.2, 1] }} />
                {results.map((r, i) => {
                  const v = r.values[a];
                  if (v == null) return null;
                  const out = r.flag === "high" || r.flag === "low";
                  return (
                    <circle key={i} cx={x(times[i])} cy={y(v)} r={hover === i ? 6 : 4.5} fill={SERIES[si]}
                      stroke={out ? tone.warn : "var(--surface)"} strokeWidth={out ? 2.5 : 2} pointerEvents="none" />
                  );
                })}
              </g>
            );
          })}
          {h && (
            <line x1={x(times[hover!])} x2={x(times[hover!])} y1={M.t} y2={M.t + ih} stroke="var(--ink-3)" strokeDasharray="2 3" pointerEvents="none" />
          )}
          <rect x={M.l - 8} y={M.t} width={iw + 16} height={ih} fill="transparent" className={h?.visit ? "cursor-pointer" : undefined}
            onPointerMove={(e) => setHover(nearest(e))} onPointerLeave={() => setHover(null)} onClick={(e) => open(nearest(e))} />
        </svg>
      )}
      <AnimatePresence>
        {h && (
          <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.12 }}
            className="pointer-events-none absolute z-10 min-w-44 rounded-control border border-line bg-surface px-3 py-2 shadow-pop"
            style={{ left: Math.min(Math.max(x(times[hover!]) - 88, 0), W - 190), top: 0 }}>
            <div className="text-[11px] text-ink-3">{fmtDay(h.at)}</div>
            <div className="mt-0.5 text-sm font-semibold tabular-nums text-ink">
              {resultValue(m, h)} <span className="text-xs font-normal text-ink-3">{m.unit}</span>
              {h.flag && <span className="ml-1.5 text-[11px] font-medium" style={{ color: h.flag === "normal" ? tone.ok : tone.warn }}>{FLAG_LABEL[h.flag]}</span>}
            </div>
            {m.analytes.length > 1 && (
              <div className="text-[11px] text-ink-3">{m.analytes.map((a) => ANALYTE_LABEL[a] ?? a).join(" / ")}</div>
            )}
            <div className="mt-1 text-[11px] text-ink-2">{h.visit ? `${h.visit.type ?? "Visit"} · click to open` : "Study visit"}</div>
          </motion.div>
        )}
      </AnimatePresence>
      {m.analytes.length > 1 && (
        <div className="absolute right-0 top-0 flex gap-3 text-[11px] text-ink-3">
          {m.analytes.map((a, i) => (
            <span key={a} className="inline-flex items-center gap-1"><span className="h-0.5 w-3 rounded-full" style={{ background: SERIES[i] }} />{ANALYTE_LABEL[a] ?? a}</span>
          ))}
        </div>
      )}
    </div>
  );
}
