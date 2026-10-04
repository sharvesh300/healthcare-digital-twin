"use client";

import type { LucideIcon } from "lucide-react";
import { motion } from "motion/react";
import type { ReactNode } from "react";

import { AnimatedNumber } from "@/components/ui/animated-number";
import type { Signal } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { fmtAge, statusLabel } from "@/lib/twin/format";

import { StatusChip } from "./chips";

/** One vital: hue-coded icon and label, the value in ink, status chip, age. Stale = hatched. */
export function VitalCard({ icon: Icon, label, hue, signal, digits = 0, unit, text, tone, now, pulse = 0, footer }: {
  icon: LucideIcon;
  label: string;
  hue: string;
  signal: Signal;
  digits?: number;
  unit?: string;
  /** show this text instead of the numeric value (e.g. activity level, sleep stage) */
  text?: string | null;
  tone?: "ok" | "warn" | "danger" | "neutral";
  now: number | null;
  pulse?: number;
  footer?: ReactNode;
}) {
  const stale = signal.status === "stale";
  const empty = signal.value == null;
  const numeric = typeof signal.value === "number" ? signal.value : null;
  return (
    <motion.article
      layout
      className={cn(
        "group relative flex min-h-[132px] flex-col justify-between overflow-hidden rounded-card border border-line bg-surface p-4 shadow-card",
        "transition-shadow duration-200 ease-standard hover:shadow-lift",
        stale && "hatch",
      )}
      whileHover={{ y: -1 }}
    >
      <motion.span
        key={pulse}
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-0.5"
        style={{ background: hue, transformOrigin: "left" }}
        initial={{ scaleX: pulse ? 0 : 1, opacity: pulse ? 1 : 0 }}
        animate={{ scaleX: 1, opacity: 0 }}
        transition={{ duration: 1.2, ease: [0.2, 0.8, 0.2, 1] }}
      />
      <header className="flex items-center gap-2">
        <span className="grid size-7 place-items-center rounded-lg" style={{ background: `color-mix(in srgb, ${hue} 11%, white)` }}>
          <Icon aria-hidden size={15} strokeWidth={2.3} style={{ color: hue }} />
        </span>
        <h3 className="label">{label}</h3>
      </header>
      <div className={cn("mt-3", (stale || empty) && "text-ink-3")}>
        {text !== undefined ? (
          <span className={cn("text-xl font-semibold tracking-tight", empty ? "text-ink-3" : "text-ink")}>{text ?? "—"}</span>
        ) : (
          <span className="flex items-baseline gap-1">
            <AnimatedNumber value={numeric} digits={digits} className={cn("text-metric font-semibold", empty || stale ? "text-ink-3" : "text-ink")} />
            {unit && <span className="text-xs font-medium text-ink-3">{unit}</span>}
          </span>
        )}
      </div>
      <footer className="mt-2 flex min-h-5 items-center justify-between gap-2">
        {footer ?? (signal.status && text === undefined ? <StatusChip status={signal.status} tone={tone} /> : <span />)}
        <span className="truncate text-[11px] text-ink-3" title={signal.source ?? undefined}>
          {stale ? "no recent data" : now ? fmtAge(signal.time, now) : ""}
        </span>
      </footer>
      <span className="sr-only">{`${label}: ${text ?? numeric ?? "no data"} ${unit ?? ""}, ${statusLabel(signal.status)}`}</span>
    </motion.article>
  );
}
