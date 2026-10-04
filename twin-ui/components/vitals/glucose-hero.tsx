"use client";

import { Droplet } from "lucide-react";
import { motion } from "motion/react";

import { AnimatedNumber } from "@/components/ui/animated-number";
import { Card, CardHeader } from "@/components/ui/card";
import type { GlucoseSignal } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { deviceName, fmtAge, fmtNumber, TREND_LABEL } from "@/lib/twin/format";
import type { Point } from "@/lib/twin/store";
import { band, GLUCOSE_LIMITS, isBand, vital } from "@/lib/tokens";

import { BandChip } from "./chips";
import { Sparkline } from "./sparkline";
import { TirBar } from "./tir-bar";
import { TrendArrow } from "./trend-arrow";

export function GlucoseHero({ glucose, points, now, pulse }: {
  glucose: GlucoseSignal;
  points: Point[];
  now: number | null;
  pulse: number;
}) {
  const value = typeof glucose.value === "number" ? glucose.value : null;
  const stale = glucose.status === "stale";
  const color = isBand(glucose.status) ? band[glucose.status] : "var(--ink-3)";
  return (
    <Card className="relative overflow-hidden p-5">
      {/* a one-shot wash in the new band colour when the band changes */}
      <motion.div
        key={pulse}
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{ background: `radial-gradient(120% 90% at 0% 0%, ${color}, transparent 60%)` }}
        initial={{ opacity: pulse ? 0.16 : 0 }}
        animate={{ opacity: 0 }}
        transition={{ duration: 1.6, ease: "easeOut" }}
      />
      <CardHeader
        icon={<Droplet aria-hidden size={14} strokeWidth={2.4} style={{ color: vital.glucose }} />}
        title="Glucose"
        meta={<>{deviceName(glucose.source) ?? "no CGM"} · {now ? fmtAge(glucose.time, now) : "—"}</>}
      />
      <div className="mt-3 flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <div className={cn("min-w-0", stale && "opacity-60")}>
          <div className="flex items-baseline gap-2">
            <AnimatedNumber value={value} className="text-display font-semibold text-ink" />
            <span className="text-base font-medium text-ink-3">mg/dL</span>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2.5">
            <BandChip status={glucose.status} />
            {glucose.trend && !stale && (
              <span className="inline-flex items-center gap-1.5 text-sm text-ink-2">
                <TrendArrow trend={glucose.trend} size={18} className="text-ink" />
                {TREND_LABEL[glucose.trend]}
                {glucose.rate_mg_dl_min != null && (
                  <span className="tabular-nums text-ink-3">
                    {glucose.rate_mg_dl_min > 0 ? "+" : ""}
                    {fmtNumber(glucose.rate_mg_dl_min, 1)} mg/dL/min
                  </span>
                )}
              </span>
            )}
          </div>
        </div>
        <div className="w-full max-w-[260px] flex-1 basis-40">
          <div className="mb-1 flex justify-between text-[11px] text-ink-3">
            <span>Last 3 h</span>
            <span>{GLUCOSE_LIMITS.low}–{GLUCOSE_LIMITS.high} target</span>
          </div>
          <Sparkline points={points} color={vital.glucose} band={[GLUCOSE_LIMITS.low, GLUCOSE_LIMITS.high]} height={56} />
        </div>
      </div>
      <TirBar points={points} className="mt-5 border-t border-line pt-4" />
    </Card>
  );
}
