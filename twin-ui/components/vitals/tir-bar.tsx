"use client";

import { motion } from "motion/react";

import { cn } from "@/lib/cn";
import { BAND_LABEL, dayKey } from "@/lib/twin/format";
import type { Point } from "@/lib/twin/store";
import { band, glucoseBand, type BandKey } from "@/lib/tokens";

const ORDER: BandKey[] = ["very_low", "low", "in_range", "high", "very_high"];

/** Time in ranges for the twin's current local day: five segments with 2 px gaps, labelled. */
export function TirBar({ points, className }: { points: Point[]; className?: string }) {
  if (!points.length) return null;
  const today = dayKey(points[points.length - 1].t);
  const day = points.filter((p) => dayKey(p.t) === today);
  const counts = Object.fromEntries(ORDER.map((b) => [b, 0])) as Record<BandKey, number>;
  day.forEach((p) => (counts[glucoseBand(p.v)] += 1));
  const pct = (b: BandKey) => (day.length ? (100 * counts[b]) / day.length : 0);
  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-baseline justify-between">
        <span className="label">Today in range</span>
        <span className="text-sm font-semibold tabular-nums text-ink">
          {Math.round(pct("in_range"))}%<span className="ml-1 text-xs font-normal text-ink-3">of {day.length} readings</span>
        </span>
      </div>
      <div className="flex h-2.5 gap-0.5 overflow-hidden rounded-full" role="img"
        aria-label={ORDER.map((b) => `${BAND_LABEL[b]} ${Math.round(pct(b))}%`).join(", ")}>
        {ORDER.map((b) => (
          <motion.div
            key={b}
            className="h-full first:rounded-l-full last:rounded-r-full"
            style={{ background: band[b] }}
            initial={false}
            animate={{ flexGrow: pct(b), flexBasis: 0 }}
            transition={{ duration: 0.6, ease: [0.2, 0.8, 0.2, 1] }}
          />
        ))}
      </div>
      <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink-2">
        {ORDER.map((b) => (
          <li key={b} className="inline-flex items-center gap-1 tabular-nums">
            <span aria-hidden className="size-2 rounded-[3px]" style={{ background: band[b] }} />
            {BAND_LABEL[b]} {Math.round(pct(b))}%
          </li>
        ))}
      </ul>
    </div>
  );
}
