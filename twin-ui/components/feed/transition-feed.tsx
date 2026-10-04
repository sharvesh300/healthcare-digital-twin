"use client";

import { Activity, ArrowRight, Droplet, HeartPulse, Moon, TrendingUp, Wind, type LucideIcon } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";

import { BandChip, StatusChip } from "@/components/vitals/chips";
import { Card, CardHeader } from "@/components/ui/card";
import type { Transition } from "@/lib/api/types";
import { fmtNumber, fmtTime, SIGNAL_LABEL, statusLabel, statusTone } from "@/lib/twin/format";
import type { FeedItem } from "@/lib/twin/store";
import { vital } from "@/lib/tokens";

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

/** What changed: status transitions, newest first; live ones slide in. */
export function TransitionFeed({ items, className }: { items: FeedItem[]; className?: string }) {
  return (
    <Card className={className}>
      <div className="px-5 pt-5">
        <CardHeader icon={<ArrowRight aria-hidden size={14} className="text-ink-3" />} title="What changed" meta={`${items.length} events`} />
      </div>
      {items.length === 0 ? (
        <p className="px-5 pb-6 pt-8 text-center text-sm text-ink-3">
          No changes yet. Status changes appear here as the twin updates.
        </p>
      ) : (
        <ol className="mt-3 max-h-[436px] overflow-y-auto px-2 pb-2" aria-live="polite" aria-relevant="additions">
          <AnimatePresence initial={false}>
            {items.map((t) => {
              const [Icon, hue] = ICON[t.signal];
              return (
                <motion.li
                  key={t.id}
                  layout
                  initial={{ opacity: 0, y: -10, backgroundColor: "var(--primary-soft)" }}
                  animate={{ opacity: 1, y: 0, backgroundColor: "rgba(255,255,255,0)" }}
                  transition={{ duration: 0.5, ease: [0.2, 0.8, 0.2, 1], backgroundColor: { duration: 2 } }}
                  className="flex items-start gap-3 rounded-control px-3 py-2.5"
                >
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
                    </div>
                  </div>
                </motion.li>
              );
            })}
          </AnimatePresence>
        </ol>
      )}
    </Card>
  );
}
