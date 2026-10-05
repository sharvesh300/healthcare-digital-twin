"use client";

import { Activity, ArrowRight, ArrowUpRight, Droplet, HeartPulse, Moon, TrendingUp, Wind, type LucideIcon } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";

import { BandChip, StatusChip } from "@/components/vitals/chips";
import { Card, CardHeader } from "@/components/ui/card";
import type { Transition } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { fmtNumber, fmtTime, isAbnormal, SIGNAL_LABEL, statusLabel, statusTone } from "@/lib/twin/format";
import type { FeedItem } from "@/lib/twin/store";
import { band, isBand, tone, vital } from "@/lib/tokens";

const ICON: Record<Transition["signal"], [LucideIcon, string]> = {
  glucose: [Droplet, vital.glucose],
  glucose_trend: [TrendingUp, vital.glucose],
  heart_rate: [HeartPulse, vital.heart],
  activity: [Activity, vital.activity],
  sleep: [Moon, vital.sleep],
  spo2: [Wind, vital.oxygen],
};

function Status({ signal, status }: { signal: Transition["signal"]; status: string | null }) {
  if (!status) return <span className="text-xs text-ink-3">—</span>;
  if (signal === "glucose" || status === "stale") return <BandChip status={status} size="sm" />;
  if (signal === "heart_rate" || signal === "spo2") return <StatusChip status={status} tone={statusTone(signal, status)} />;
  return <span className="rounded-chip bg-surface-2 px-1.5 py-0.5 text-[11px] font-medium text-ink">{statusLabel(status)}</span>;
}

/** What changed: status transitions, newest first; live ones slide in. With `onInspect`, each
 *  change opens the whole twin as it was at that moment. */
export function TransitionFeed({ items, className, onInspect, activeId }: {
  items: FeedItem[];
  className?: string;
  onInspect?: (item: FeedItem) => void;
  /** the change currently being inspected */
  activeId?: string | null;
}) {
  const [alertsOnly, setAlertsOnly] = useState(false);
  const alerts = items.filter((t) => isAbnormal(t.signal, t.to));
  const shown = alertsOnly ? alerts : items;
  return (
    <Card className={className}>
      <div className="px-5 pt-5">
        <CardHeader
          icon={<ArrowRight aria-hidden size={14} className="text-ink-3" />}
          title="What changed"
          meta={`${shown.length} events`}
          right={
            <div role="radiogroup" aria-label="Show" className="flex shrink-0 rounded-control border border-line bg-surface-2 p-0.5">
              {([[false, "All"], [true, `Alerts${alerts.length ? ` ${alerts.length}` : ""}`]] as const).map(([v, label]) => (
                <button key={String(v)} role="radio" aria-checked={alertsOnly === v} onClick={() => setAlertsOnly(v)}
                  className={cn("relative rounded-[8px] px-2.5 py-1 text-xs font-medium tabular-nums transition-colors",
                    alertsOnly === v ? "text-ink" : "text-ink-3 hover:text-ink-2")}>
                  {alertsOnly === v && <motion.span layoutId="feed-filter" className="absolute inset-0 rounded-[8px] bg-surface shadow-card" transition={{ type: "spring", stiffness: 400, damping: 32 }} />}
                  <span className="relative">{label}</span>
                </button>
              ))}
            </div>
          }
        />
      </div>
      {shown.length === 0 ? (
        <p className="px-5 pb-6 pt-8 text-center text-sm text-ink-3">
          {alertsOnly ? "No out-of-range changes in this list." : "No changes yet. Status changes appear here as the twin updates."}
        </p>
      ) : (
        <ol className="mt-3 max-h-[436px] overflow-y-auto px-2 pb-2" aria-live="polite" aria-relevant="additions">
          <AnimatePresence initial={false}>
            {shown.map((t) => {
              const [Icon, hue] = ICON[t.signal];
              const abnormal = isAbnormal(t.signal, t.to);
              const accent = t.signal === "glucose" && isBand(t.to) ? band[t.to] : tone.warn;
              const body = (
                <>
                  {abnormal && <span aria-hidden className="absolute inset-y-2.5 left-0.5 w-[3px] rounded-full" style={{ background: accent }} />}
                  <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg" style={{ background: `color-mix(in srgb, ${hue} 11%, white)` }}>
                    <Icon aria-hidden size={14} strokeWidth={2.3} style={{ color: hue }} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="truncate text-sm font-medium text-ink">{SIGNAL_LABEL[t.signal]}</span>
                      <time className="shrink-0 text-[11px] tabular-nums text-ink-3" dateTime={t.time}>{fmtTime(t.time)}</time>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <Status signal={t.signal} status={t.from} />
                      <ArrowRight aria-hidden size={12} className="text-ink-3" />
                      <Status signal={t.signal} status={t.to} />
                      {t.value != null && t.signal !== "glucose_trend" && (
                        <span className="text-[11px] tabular-nums text-ink-3">at {fmtNumber(t.value, t.signal === "activity" ? 1 : 0)}</span>
                      )}
                      {onInspect && (
                        <span className="ml-auto inline-flex items-center gap-0.5 text-[11px] font-medium text-primary opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
                          Inspect <ArrowUpRight aria-hidden size={12} />
                        </span>
                      )}
                    </div>
                  </div>
                </>
              );
              return (
                <motion.li
                  key={t.id}
                  layout
                  initial={{ opacity: 0, y: -10, backgroundColor: "var(--primary-soft)" }}
                  animate={{ opacity: 1, y: 0, backgroundColor: "rgba(255,255,255,0)" }}
                  transition={{ duration: 0.5, ease: [0.2, 0.8, 0.2, 1], backgroundColor: { duration: 2 } }}
                  className="rounded-control"
                >
                  {onInspect ? (
                    <button
                      onClick={() => onInspect(t)}
                      aria-current={activeId === t.id ? "true" : undefined}
                      title={`See the full twin at ${fmtTime(t.time)}`}
                      className={cn("group relative flex w-full items-start gap-3 rounded-control px-3 py-2.5 text-left transition-colors hover:bg-surface-2",
                        activeId === t.id && "bg-primary-soft hover:bg-primary-soft")}
                    >
                      {body}
                    </button>
                  ) : (
                    <div className="relative flex items-start gap-3 px-3 py-2.5">{body}</div>
                  )}
                </motion.li>
              );
            })}
          </AnimatePresence>
        </ol>
      )}
    </Card>
  );
}
