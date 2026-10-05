import { ArrowDown, ArrowUp, Check, ChevronRight } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Card, CardHeader } from "@/components/ui/card";
import type { Flag } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { FLAG_LABEL } from "@/lib/record/format";
import { tone } from "@/lib/tokens";

const tint = (color: string, pct: number) => `color-mix(in srgb, ${color} ${pct}%, white)`;

/** Hatched badge for values that came from a generator (Synthea), not a real source. */
export function Synthetic({ className }: { className?: string }) {
  return (
    <span className={cn("hatch inline-flex shrink-0 rounded-chip border border-line px-1.5 py-0.5 text-[10px] font-medium text-ink-2", className)}
      title="From the synthetic EHR (Synthea), not a real record">
      Synthetic
    </span>
  );
}

const FLAG_ICON = { high: ArrowUp, low: ArrowDown, normal: Check } as const;

/** High / Low / Normal against the adult reference range: colour, icon and word. */
export function FlagChip({ flag, className }: { flag: Flag | null | undefined; className?: string }) {
  if (!flag) return null;
  const color = flag === "normal" ? tone.ok : tone.warn;
  const Icon = FLAG_ICON[flag];
  return (
    <span className={cn("inline-flex shrink-0 items-center gap-1 rounded-chip px-1.5 py-0.5 text-[11px] font-medium text-ink", className)}
      style={{ background: tint(color, 13) }}>
      <Icon aria-hidden size={11} strokeWidth={2.6} style={{ color }} />
      {FLAG_LABEL[flag]}
    </span>
  );
}

/** Active / Resolved (or Stopped) with a dot. */
export function StatusPill({ active, inactive = "Resolved", activeLabel = "Active" }: { active: boolean; inactive?: string; activeLabel?: string }) {
  return (
    <span className={cn("inline-flex shrink-0 items-center gap-1 rounded-chip px-1.5 py-0.5 text-[11px] font-medium",
      active ? "bg-primary-soft text-primary-strong" : "bg-surface-2 text-ink-3")}>
      <span aria-hidden className={cn("size-1.5 rounded-full", active ? "bg-primary" : "bg-ink-3/50")} />
      {active ? activeLabel : inactive}
    </span>
  );
}

/** A neutral tag (drug class, condition group, panel). */
export function Tag({ children, tinted, className }: { children: ReactNode; tinted?: string; className?: string }) {
  return (
    <span className={cn("inline-flex shrink-0 items-center rounded-chip px-1.5 py-0.5 text-[11px] font-medium text-ink-2", !tinted && "bg-surface-2", className)}
      style={tinted ? { background: tint(tinted, 11), color: "var(--ink)" } : undefined}>
      {children}
    </span>
  );
}

export function Breadcrumbs({ items }: { items: { label: string; href?: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="flex min-w-0 flex-wrap items-center gap-1 text-xs text-ink-3">
      {items.map((item, i) => (
        <span key={i} className="inline-flex min-w-0 items-center gap-1">
          {i > 0 && <ChevronRight aria-hidden size={12} className="shrink-0" />}
          {item.href ? (
            <Link href={item.href} className="rounded px-0.5 transition-colors hover:text-ink">{item.label}</Link>
          ) : (
            <span aria-current="page" className="truncate font-medium text-ink-2">{item.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}

/** A record section: header with icon, title, count and a "View all" link. */
export function SectionCard({ id, icon, title, meta, action, right, children, className }: {
  id?: string;
  icon: ReactNode;
  title: string;
  meta?: ReactNode;
  action?: { href: string; label: string };
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card id={id} aria-labelledby={id ? `${id}-title` : undefined} className={cn("scroll-mt-48 p-5", className)}>
      <CardHeader
        icon={icon}
        title={<span id={id ? `${id}-title` : undefined}>{title}</span>}
        meta={meta}
        right={
          (right || action) && (
            <div className="flex shrink-0 items-center gap-2">
              {right}
              {action && (
                <Link href={action.href} className="inline-flex items-center gap-0.5 whitespace-nowrap rounded-md px-1.5 py-1 text-xs font-medium text-primary hover:bg-primary-soft">
                  {action.label} <ChevronRight aria-hidden size={13} />
                </Link>
              )}
            </div>
          )
        }
      />
      <div className="mt-3">{children}</div>
    </Card>
  );
}

/** A labelled figure in a detail header or the summary strip. */
export function StatTile({ label, value, unit, hint, href, synthetic, children }: {
  label: string;
  value: ReactNode;
  unit?: string | null;
  hint?: ReactNode;
  href?: string;
  synthetic?: boolean;
  children?: ReactNode;
}) {
  const body = (
    <>
      <div className="label flex items-center justify-between gap-2">{label}{synthetic && <Synthetic />}</div>
      <div className="mt-1.5 flex flex-wrap items-baseline gap-x-1.5 gap-y-1">
        <span className="text-xl font-semibold tabular-nums tracking-tight text-ink">{value}</span>
        {unit && <span className="text-xs text-ink-3">{unit}</span>}
        {children}
      </div>
      {hint && <div className="mt-1 truncate text-xs text-ink-3">{hint}</div>}
    </>
  );
  const cls = cn("block min-w-0 rounded-card border border-line bg-surface p-4 shadow-card", synthetic && "hatch",
    href && "transition-shadow hover:shadow-lift focus-visible:shadow-lift");
  return href ? <Link href={href} className={cls}>{body}</Link> : <div className={cls}>{body}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-control bg-surface-2 px-4 py-6 text-center text-sm text-ink-3">{children}</p>;
}

/** The page title row of a list or detail page. */
export function PageTitle({ title, children, aside }: { title: ReactNode; children?: ReactNode; aside?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-xl font-semibold tracking-tight text-ink">{title}</h2>
        {children && <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-sm text-ink-3">{children}</div>}
      </div>
      {aside}
    </div>
  );
}
