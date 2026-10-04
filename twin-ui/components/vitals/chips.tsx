import { ChevronDown, ChevronUp, ChevronsDown, ChevronsUp, CircleCheck, ClockAlert, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/cn";
import { BAND_LABEL, statusLabel } from "@/lib/twin/format";
import { band as bandColor, isBand, tone as toneColor } from "@/lib/tokens";

const BAND_ICON: Record<string, LucideIcon> = {
  very_low: ChevronsDown,
  low: ChevronDown,
  in_range: CircleCheck,
  high: ChevronUp,
  very_high: ChevronsUp,
  stale: ClockAlert,
};

const tint = (color: string, pct: number) => `color-mix(in srgb, ${color} ${pct}%, white)`;

/** Glucose band: tinted background, band-coloured icon, ink label. Never colour alone. */
export function BandChip({ status, size = "md", className }: { status: string | null; size?: "sm" | "md"; className?: string }) {
  if (!status) return null;
  const color = isBand(status) ? bandColor[status] : "var(--ink-3)";
  const Icon = BAND_ICON[status] ?? ClockAlert;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-chip font-medium text-ink transition-colors duration-500 ease-standard",
        size === "sm" ? "px-1.5 py-0.5 text-[11px]" : "px-2 py-1 text-xs",
        status === "stale" && "hatch",
        className,
      )}
      style={{ background: status === "stale" ? "var(--surface-2)" : tint(color, 12) }}
    >
      <Icon aria-hidden size={size === "sm" ? 12 : 14} strokeWidth={2.4} style={{ color }} />
      {BAND_LABEL[status] ?? status}
    </span>
  );
}

/** Status of a non-glucose vital (heart-rate band, SpO₂ band, activity level, sleep stage). */
export function StatusChip({ status, tone = "neutral", className }: {
  status: string | null;
  tone?: keyof typeof toneColor;
  className?: string;
}) {
  if (!status) return null;
  if (status === "stale") return <BandChip status="stale" size="sm" className={className} />;
  const color = toneColor[tone];
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-chip px-1.5 py-0.5 text-[11px] font-medium text-ink", className)}
      style={{ background: tone === "neutral" ? "var(--surface-2)" : tint(color, 12) }}
    >
      <span aria-hidden className="size-1.5 rounded-full" style={{ background: color }} />
      {statusLabel(status)}
    </span>
  );
}
