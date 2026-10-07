"use client";

import { ArrowUpRight, Crosshair, Table2, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { niceTicks, useWidth } from "@/components/charts/scale";
import { BandChip } from "@/components/vitals/chips";
import { Card, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { fmtDate, fmtNumber, fmtTime } from "@/lib/twin/format";
import type { Point } from "@/lib/twin/store";
import { glucoseBand } from "@/lib/tokens";

const RANGES = [3, 6, 24] as const;
type Range = (typeof RANGES)[number];

export interface SeriesSpec {
  points: Point[];
  color: string;
  unit: string;
  digits?: number;
  /** faint target band, e.g. glucose 70–180 */
  target?: [number, number];
  /** hairline dashed thresholds; also used as the y ticks when given */
  thresholds?: number[];
  /** the y axis always includes this range */
  floor?: [number, number];
  /** gaps longer than this break the line (minutes) */
  gapMin?: number;
  glucose?: boolean;
  /** colour of an out-of-range value (null when in range); runs of them are shaded as episodes */
  flag?: (v: number) => string | null;
  /** what to call a flagged value (default "Out of range") */
  flagLabel?: (v: number) => string;
}

/** Clicking a chart pins a moment: a popover with what else was going on, and a way to open
 *  the whole twin as it was then. */
export interface MomentInspect {
  /** the button's label, e.g. "See the full twin" */
  action: string;
  onOpen: (t: number) => void;
  /** other signals and status changes around t */
  render?: (t: number) => ReactNode;
}

type Episode = { a: number; b: number; color: string };

/** Runs of flagged points (same colour, no gap): the chart's out-of-range episodes. */
function episodesOf(pts: Point[], flag: SeriesSpec["flag"], gapMs: number): Episode[] {
  if (!flag) return [];
  const out: Episode[] = [];
  let cur: Episode | null = null;
  pts.forEach((p, i) => {
    const color = flag(p.v);
    if (cur && (color !== cur.color || p.t - pts[i - 1].t > gapMs)) {
      out.push(cur);
      cur = null;
    }
    if (color) {
      if (cur) cur.b = p.t;
      else cur = { a: p.t, b: p.t, color };
    }
  });
  if (cur) out.push(cur);
  return out;
}

/** A card with one time series: range control (3/6/24 h), table toggle, live tail. */
export function ChartCard({ title, icon, meta, spec, live, defaultHours = 6, height = 200, inspect }: {
  title: string;
  icon: ReactNode;
  meta?: ReactNode;
  spec: SeriesSpec;
  live: boolean;
  defaultHours?: Range;
  height?: number;
  inspect?: MomentInspect;
}) {
  const [hours, setHours] = useState<Range>(defaultHours);
  const [table, setTable] = useState(false);
  const end = spec.points.length ? spec.points[spec.points.length - 1].t : 0;
  const visible = spec.points.filter((p) => p.t >= end - hours * 3600_000);
  return (
    <Card className="p-5">
      <CardHeader
        icon={icon}
        title={title}
        meta={meta}
        right={
          <div className="flex items-center gap-1.5">
            <div role="radiogroup" aria-label="Time range" className="flex rounded-control border border-line bg-surface-2 p-0.5">
              {RANGES.map((h) => (
                <button
                  key={h}
                  role="radio"
                  aria-checked={hours === h}
                  onClick={() => setHours(h)}
                  className={cn(
                    "relative rounded-[8px] px-2.5 py-1 text-xs font-medium tabular-nums transition-colors",
                    hours === h ? "text-ink" : "text-ink-3 hover:text-ink-2",
                  )}
                >
                  {hours === h && (
                    <motion.span layoutId={`range-${title}`} className="absolute inset-0 rounded-[8px] bg-surface shadow-card" transition={{ type: "spring", stiffness: 400, damping: 32 }} />
                  )}
                  <span className="relative">{h} h</span>
                </button>
              ))}
            </div>
            <button
              onClick={() => setTable((t) => !t)}
              aria-pressed={table}
              aria-label="Show as table"
              className={cn("grid size-8 place-items-center rounded-control border border-line transition-colors",
                table ? "bg-primary-soft text-primary" : "bg-surface text-ink-3 hover:text-ink-2")}
            >
              <Table2 size={15} />
            </button>
          </div>
        }
      />
      <div className="mt-4">
        {table ? (
          <PointsTable points={visible} spec={spec} inspect={inspect} />
        ) : (
          <TimeSeriesChart spec={{ ...spec, points: visible }} hours={hours} end={end} live={live} height={height} inspect={inspect} />
        )}
      </div>
      {(inspect || spec.flag) && !table && (
        <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-3">
          {spec.flag && (spec.glucose ? [["var(--band-low)", "Low"], ["var(--band-high)", "High"]] : [["var(--status-warn)", "Out of range"]]).map(([c, label]) => (
            <span key={label} className="inline-flex items-center gap-1.5">
              <span aria-hidden className="h-[3px] w-3 rounded-full" style={{ background: c }} />
              {label}
            </span>
          ))}
          {inspect && (
            <span className="inline-flex items-center gap-1">
              <Crosshair aria-hidden size={11} /> Click any moment to inspect it
            </span>
          )}
        </p>
      )}
    </Card>
  );
}

function TimeSeriesChart({ spec, hours, end, live, height, inspect }: {
  spec: SeriesSpec;
  hours: number;
  end: number;
  live: boolean;
  height: number;
  inspect?: MomentInspect;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<Point | null>(null);
  const [pinned, setPinned] = useState<Point | null>(null);
  const M = { l: 40, r: 14, t: 10, b: 26 };
  const W = Math.max(width, 10);
  const H = height;
  const iw = W - M.l - M.r;
  const ih = H - M.t - M.b;
  const start = end - hours * 3600_000;
  const pts = spec.points;

  const [lo, hi] = useMemo(() => {
    const vs = pts.map((p) => p.v);
    let a = Math.min(...vs, ...(spec.floor ?? []), ...(spec.target ?? []));
    let b = Math.max(...vs, ...(spec.floor ?? []), ...(spec.target ?? []));
    if (!Number.isFinite(a)) [a, b] = [0, 1];
    const pad = (b - a) * 0.08 || 5;
    return [a - pad, b + pad];
  }, [pts, spec.floor, spec.target]);

  const x = (t: number) => M.l + ((t - start) / (end - start || 1)) * iw;
  const y = (v: number) => M.t + ih - ((v - lo) / (hi - lo)) * ih;

  const path = useMemo(() => {
    let d = "";
    pts.forEach((p, i) => {
      const jump = i === 0 || p.t - pts[i - 1].t > (spec.gapMin ?? 20) * 60_000;
      d += `${jump ? "M" : "L"}${x(p.t).toFixed(1)} ${y(p.v).toFixed(1)}`;
    });
    return d;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pts, W, lo, hi, start, end]);

  const yTicks = (spec.thresholds ?? niceTicks(lo, hi)).filter((v) => v >= lo && v <= hi);
  const stepH = hours <= 6 ? 1 : 4;
  const xTicks: number[] = [];
  const firstHour = Math.ceil(start / 3600_000) * 3600_000;
  for (let t = firstHour; t <= end; t += stepH * 3600_000) xTicks.push(t);
  const last = pts[pts.length - 1];

  const episodes = episodesOf(pts, spec.flag, (spec.gapMin ?? 20) * 60_000);
  const shown = pinned && pinned.t >= start && pinned.t <= end ? pinned : null;

  const nearest = (e: React.PointerEvent<SVGRectElement> | React.MouseEvent<SVGRectElement>): Point | null => {
    if (!pts.length) return null;
    const rect = e.currentTarget.getBoundingClientRect();
    const t = start + ((e.clientX - rect.left) / rect.width) * (end - start);
    let lo2 = 0;
    let hi2 = pts.length - 1;
    while (hi2 - lo2 > 1) {
      const mid = (lo2 + hi2) >> 1;
      if (pts[mid].t < t) lo2 = mid;
      else hi2 = mid;
    }
    return Math.abs(pts[lo2].t - t) < Math.abs(pts[hi2].t - t) ? pts[lo2] : pts[hi2];
  };
  const onMove = (e: React.PointerEvent<SVGRectElement>) => setHover(nearest(e));

  // a pinned moment closes on Escape or a click elsewhere
  useEffect(() => {
    if (!pinned) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setPinned(null);
    const onDown = (e: PointerEvent) => !ref.current?.contains(e.target as Node) && setPinned(null);
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onDown);
    };
  }, [pinned, ref]);

  return (
    <div ref={ref} className="relative w-full" style={{ height: H }}>
      {width > 0 && pts.length > 1 ? (
        <svg width={W} height={H} className="block overflow-visible" role="img"
          aria-label={`${pts.length} readings from ${fmtTime(pts[0].t)} to ${fmtTime(last.t)}, latest ${fmtNumber(last.v, spec.digits)} ${spec.unit}`}>
          <defs>
            <linearGradient id={`area-${spec.unit}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" style={{ stopColor: spec.color, stopOpacity: 0.12 }} />
              <stop offset="100%" style={{ stopColor: spec.color, stopOpacity: 0 }} />
            </linearGradient>
          </defs>
          {spec.target && (
            <rect x={M.l} width={iw} y={y(spec.target[1])} height={y(spec.target[0]) - y(spec.target[1])} fill="var(--band-in-range)" opacity={0.06} />
          )}
          {episodes.map((ep) => (
            <g key={ep.a} pointerEvents="none">
              <rect x={x(ep.a) - 1} width={Math.max(2, x(ep.b) - x(ep.a) + 2)} y={M.t} height={ih} fill={ep.color} opacity={0.07} />
              <rect x={x(ep.a) - 1} width={Math.max(3, x(ep.b) - x(ep.a) + 2)} y={M.t + ih - 3} height={3} rx={1.5} fill={ep.color} opacity={0.85} />
            </g>
          ))}
          {yTicks.map((v, i) => {
            // labels need ~13 px; a threshold too close to the previous one keeps its line only
            const crowded = i > 0 && Math.abs(y(v) - y(yTicks[i - 1])) < 13;
            return (
              <g key={v}>
                <line x1={M.l} x2={W - M.r} y1={y(v)} y2={y(v)} stroke="var(--line-strong)" strokeWidth={1}
                  strokeDasharray={spec.thresholds ? "3 4" : undefined} opacity={spec.thresholds ? 0.9 : 0.5} />
                {!crowded && <text x={M.l - 8} y={y(v)} dy="0.32em" textAnchor="end" className="fill-ink-3 text-[11px] tabular-nums">{fmtNumber(v)}</text>}
              </g>
            );
          })}
          {xTicks.map((t) => (
            <text key={t} x={x(t)} y={H - 6} textAnchor="middle" className="fill-ink-3 text-[11px] tabular-nums">{fmtTime(t)}</text>
          ))}
          <path d={`${path}L${x(last.t)} ${M.t + ih}L${x(pts[0].t)} ${M.t + ih}Z`} fill={`url(#area-${spec.unit})`} />
          <motion.path
            d={path}
            fill="none"
            stroke={spec.color}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 0.9, ease: [0.2, 0.8, 0.2, 1] }}
          />
          <g transform={`translate(${x(last.t)} ${y(last.v)})`}>
            {live && <circle r={4} fill={spec.color} className="live-ping" style={{ transformBox: "fill-box", transformOrigin: "center" }} />}
            <circle r={4} fill={spec.color} stroke="var(--surface)" strokeWidth={2} />
          </g>
          {shown && (
            <g pointerEvents="none">
              <line x1={x(shown.t)} x2={x(shown.t)} y1={M.t} y2={M.t + ih} stroke="var(--ink-2)" strokeWidth={1.5} />
              <circle cx={x(shown.t)} cy={y(shown.v)} r={9} fill={spec.color} opacity={0.18} />
              <circle cx={x(shown.t)} cy={y(shown.v)} r={5} fill={spec.color} stroke="var(--surface)" strokeWidth={2} />
            </g>
          )}
          {hover && hover !== shown && (
            <g pointerEvents="none">
              <line x1={x(hover.t)} x2={x(hover.t)} y1={M.t} y2={M.t + ih} stroke="var(--ink-3)" strokeWidth={1} strokeDasharray="2 3" />
              <circle cx={x(hover.t)} cy={y(hover.v)} r={5} fill={spec.color} stroke="var(--surface)" strokeWidth={2} />
            </g>
          )}
          <rect x={M.l} y={M.t} width={iw} height={ih} fill="transparent" onPointerMove={onMove} onPointerLeave={() => setHover(null)}
            className={inspect ? "cursor-pointer" : undefined}
            onClick={inspect ? (e) => setPinned(nearest(e)) : undefined} />
        </svg>
      ) : (
        <div className="grid h-full place-items-center rounded-control bg-surface-2 text-sm text-ink-3">
          {width > 0 ? "No readings in this window yet" : null}
        </div>
      )}
      <AnimatePresence>
        {hover && !shown && (
          <motion.div
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.12 }}
            className="pointer-events-none absolute z-10 min-w-36 rounded-control border border-line bg-surface px-3 py-2 shadow-pop"
            style={{
              left: Math.min(Math.max(x(hover.t) - 72, 0), W - 150),
              top: Math.max(y(hover.v) - 76, 0),
            }}
          >
            <div className="text-[11px] text-ink-3">{fmtDate(hover.t)} · {fmtTime(hover.t)}</div>
            <div className="mt-0.5 flex items-center justify-between gap-3">
              <span className="text-sm font-semibold tabular-nums text-ink">
                {fmtNumber(hover.v, spec.digits)} <span className="text-xs font-normal text-ink-3">{spec.unit}</span>
              </span>
              {spec.glucose && <BandChip status={glucoseBand(hover.v)} size="sm" />}
            </div>
            {inspect && <div className="mt-1 text-[10px] text-ink-3">Click to inspect</div>}
          </motion.div>
        )}
      </AnimatePresence>
      <AnimatePresence>
        {shown && inspect && (
          <MomentPopover key={shown.t} point={shown} spec={spec} inspect={inspect} onClose={() => setPinned(null)}
            style={x(shown.t) > W / 2
              ? { right: Math.max(W - x(shown.t) + 12, 0), top: 0 }
              : { left: Math.min(x(shown.t) + 12, Math.max(W - 268, 0)), top: 0 }} />
        )}
      </AnimatePresence>
    </div>
  );
}

function MomentPopover({ point, spec, inspect, onClose, style }: {
  point: Point;
  spec: SeriesSpec;
  inspect: MomentInspect;
  onClose: () => void;
  style: React.CSSProperties;
}) {
  const flagged = spec.flag?.(point.v);
  return (
    <motion.div
      role="dialog"
      aria-label={`Moment at ${fmtTime(point.t)}`}
      initial={{ opacity: 0, scale: 0.96, y: 4 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.98 }}
      transition={{ duration: 0.16, ease: [0.2, 0.8, 0.2, 1] }}
      className="absolute z-20 w-64 rounded-card border border-line bg-surface p-3 shadow-pop"
      style={style}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[11px] text-ink-3">{fmtDate(point.t)} · {fmtTime(point.t)}</div>
          <div className="mt-0.5 flex items-center gap-2">
            <span className="text-lg font-semibold tabular-nums text-ink">
              {fmtNumber(point.v, spec.digits)} <span className="text-xs font-normal text-ink-3">{spec.unit}</span>
            </span>
            {spec.glucose ? <BandChip status={glucoseBand(point.v)} size="sm" /> : flagged && (
              <span className="inline-flex items-center gap-1 rounded-chip px-1.5 py-0.5 text-[11px] font-medium text-ink"
                style={{ background: `color-mix(in srgb, ${flagged} 12%, white)` }}>
                <span aria-hidden className="size-1.5 rounded-full" style={{ background: flagged }} />
                {spec.flagLabel?.(point.v) ?? "Out of range"}
              </span>
            )}
          </div>
        </div>
        <button onClick={onClose} aria-label="Close" className="grid size-6 place-items-center rounded-md text-ink-3 hover:bg-surface-2 hover:text-ink">
          <X size={14} />
        </button>
      </div>
      {inspect.render && <div className="mt-2 border-t border-line pt-2">{inspect.render(point.t)}</div>}
      <button
        onClick={() => {
          inspect.onOpen(point.t);
          onClose();
        }}
        className="mt-3 inline-flex w-full items-center justify-center gap-1.5 rounded-control bg-primary px-3 py-2 text-xs font-medium text-white shadow-card transition-colors hover:bg-primary-strong"
      >
        {inspect.action}
        <ArrowUpRight aria-hidden size={14} />
      </button>
    </motion.div>
  );
}

function PointsTable({ points, spec, inspect }: { points: Point[]; spec: SeriesSpec; inspect?: MomentInspect }) {
  const rows = points.slice(-14).reverse();
  return (
    <div className="max-h-[200px] overflow-auto rounded-control border border-line">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-surface-2 text-left">
          <tr>
            <th className="label px-3 py-2">Time</th>
            <th className="label px-3 py-2 text-right">Value ({spec.unit})</th>
            {spec.glucose && <th className="label px-3 py-2">Band</th>}
            {inspect && <th className="px-3 py-2"><span className="sr-only">Inspect</span></th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.t} className="border-t border-line">
              <td className="px-3 py-1.5 tabular-nums text-ink-2">{fmtTime(p.t)}</td>
              <td className="px-3 py-1.5 text-right font-medium tabular-nums text-ink">{fmtNumber(p.v, spec.digits)}</td>
              {spec.glucose && (
                <td className="px-3 py-1.5"><BandChip status={glucoseBand(p.v)} size="sm" /></td>
              )}
              {inspect && (
                <td className="px-2 py-1 text-right">
                  <button onClick={() => inspect.onOpen(p.t)} title={`${inspect.action} at ${fmtTime(p.t)}`}
                    className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium text-primary hover:bg-primary-soft">
                    Inspect <ArrowUpRight aria-hidden size={12} />
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
