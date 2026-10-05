import { Ambulance, BedDouble, ChevronRight, House, MonitorSmartphone, Stethoscope, type LucideIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import type { ConditionSummary, MeasureSummary, MedicationSummary, VisitSummary } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { capitalise, fmtDay, fmtDuration, fmtMonth, rangeText, resultDelta, resultValue, visitClass } from "@/lib/record/format";
import { vital } from "@/lib/tokens";

import { FlagChip, StatusPill, Synthetic, Tag } from "./parts";
import { ResultSpark } from "./spark";

/** A list of record rows: hairline dividers, rows are links. */
export function RowList({ children, className }: { children: ReactNode; className?: string }) {
  // a container: rows lay out by the list's width, so the same row fits a page or a side card
  return <ul className={cn("@container -mx-2 divide-y divide-line", className)}>{children}</ul>;
}

function RowLink({ href, children, className, label }: { href: string; children: ReactNode; className?: string; label?: string }) {
  return (
    <li>
      <Link href={href} aria-label={label}
        className={cn("group flex items-center gap-3 rounded-control px-2 py-3 transition-colors hover:bg-surface-2 focus-visible:bg-surface-2", className)}>
        <div className="min-w-0 flex-1">{children}</div>
        <ChevronRight aria-hidden size={16} className="shrink-0 text-ink-3 transition-transform group-hover:translate-x-0.5 group-hover:text-ink-2" />
      </Link>
    </li>
  );
}

// ── tests and vitals ──

export function MeasureRow({ m, href }: { m: MeasureSummary; href: string }) {
  const delta = resultDelta(m);
  const range = rangeText(m);
  return (
    <RowLink href={href} label={`${m.display}: ${resultValue(m, m.latest)} ${m.unit ?? ""}`}>
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 @xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_96px_minmax(170px,auto)]">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-ink">{m.display}</p>
          <p className="truncate text-xs text-ink-3">{range ? `Range ${range}` : m.panel_display}</p>
        </div>
        <div className="flex items-center justify-end gap-2 @xl:justify-start">
          <span className="text-sm font-semibold tabular-nums text-ink">
            {resultValue(m, m.latest)}
            {m.unit && !m.latest.text && <span className="ml-1 text-xs font-normal text-ink-3">{m.unit}</span>}
          </span>
          <FlagChip flag={m.latest.flag} />
          {delta && delta !== "no change" && <span className="text-xs tabular-nums text-ink-3" title="Change since the previous result">{delta}</span>}
        </div>
        <ResultSpark points={m.spark} range={m.ranges[m.analytes[0]]} className="hidden @xl:block" />
        <div className="col-span-2 flex items-center gap-2 whitespace-nowrap text-xs text-ink-3 @xl:col-span-1 @xl:justify-end">
          <span className="tabular-nums">{fmtDay(m.latest.at)}</span>
          <span className="tabular-nums">· {m.count} result{m.count === 1 ? "" : "s"}</span>
          {m.is_synthetic && <Synthetic />}
        </div>
      </div>
    </RowLink>
  );
}

// ── diagnoses and findings ──

export function ConditionRow({ c, href }: { c: ConditionSummary; href: string }) {
  const when = c.active
    ? `since ${fmtMonth(c.current.onset_at)}`
    : `resolved ${fmtMonth(c.current.abated_at ?? c.last_change)}`;
  return (
    <RowLink href={href}>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <div className="flex min-w-0 items-center gap-2">
          <p className="truncate text-sm font-medium text-ink">{c.display}</p>
          {c.episodes > 1 && <Tag className="tabular-nums">×{c.episodes} episodes</Tag>}
          {c.group_display && <Tag tinted={vital.glucose}>{c.group_display}</Tag>}
        </div>
        <div className="flex shrink-0 items-center gap-2 text-xs text-ink-3">
          <span className="tabular-nums">{when}</span>
          <StatusPill active={c.active} />
          {c.is_synthetic && <Synthetic />}
        </div>
      </div>
    </RowLink>
  );
}

// ── medications ──

export function MedicationRow({ m, href }: { m: MedicationSummary; href: string }) {
  return (
    <RowLink href={href}>
      <div className="grid grid-cols-1 gap-x-4 gap-y-1 @xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_auto] @xl:items-center">
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            <p className="truncate text-sm font-medium text-ink">{capitalise(m.medication)}</p>
            {m.episodes > 1 && <Tag className="tabular-nums">×{m.episodes}</Tag>}
          </div>
          <p className="truncate text-xs text-ink-3" title={m.product ?? undefined}>{m.product ?? "Product not recorded"}</p>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          {m.glucose_lowering ? <Tag tinted={vital.glucose}>Glucose-lowering</Tag> : null}
          {m.drug_class_display && <Tag className="max-w-full truncate">{m.drug_class_display}</Tag>}
          <span className={cn("text-xs", m.dosage.text ? "text-ink-2" : "text-ink-3")}
            title={m.dosage.text ? undefined : "The source recorded no dose or frequency; the product gives the strength"}>
            {m.dosage.text ? capitalise(m.dosage.text) : "Dose not recorded"}
          </span>
        </div>
        <div className="flex items-center gap-2 text-xs text-ink-3 @xl:justify-end">
          <span className="tabular-nums">{m.active ? `since ${fmtMonth(m.started_at)}` : `${fmtMonth(m.started_at)} – ${fmtMonth(m.ended_at)}`}</span>
          <StatusPill active={m.active} inactive="Stopped" />
          {m.is_synthetic && <Synthetic />}
        </div>
      </div>
    </RowLink>
  );
}

// ── visits ──

export const VISIT_ICON: Record<string, LucideIcon> = {
  ambulatory: Stethoscope,
  emergency: Ambulance,
  inpatient: BedDouble,
  virtual: MonitorSmartphone,
  home: House,
};

export function VisitCounts({ counts }: { counts: VisitSummary["counts"] }) {
  const parts = [
    counts.tests && `${counts.tests} test${counts.tests === 1 ? "" : "s"}`,
    counts.diagnoses && `${counts.diagnoses} diagnos${counts.diagnoses === 1 ? "is" : "es"}`,
    counts.medications && `${counts.medications} medication${counts.medications === 1 ? "" : "s"}`,
  ].filter(Boolean);
  return <span className="text-xs text-ink-3">{parts.length ? parts.join(" · ") : "Nothing recorded"}</span>;
}

export function VisitRow({ v, href }: { v: VisitSummary; href: string }) {
  const Icon = VISIT_ICON[v.class] ?? Stethoscope;
  const urgent = v.class === "inpatient" || v.class === "emergency";
  return (
    <RowLink href={href}>
      <div className="flex items-center gap-3">
        <span className={cn("grid size-8 shrink-0 place-items-center rounded-lg", urgent ? "bg-[color-mix(in_srgb,var(--status-warn)_12%,white)] text-status-warn" : "bg-surface-2 text-ink-2")}>
          <Icon aria-hidden size={15} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3">
            <p className="truncate text-sm font-medium text-ink">{v.type ?? visitClass(v.class)}</p>
            <span className="shrink-0 text-xs tabular-nums text-ink-3">{fmtDay(v.start)}</span>
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className={cn("text-xs", urgent ? "font-medium text-status-warn" : "text-ink-2")}>
              {visitClass(v.class)}{v.duration_h != null && v.duration_h >= 1 ? ` · ${fmtDuration(v.duration_h)}` : ""}
            </span>
            {v.reason && <span className="truncate text-xs text-ink-3">for {v.reason}</span>}
            <span className="ml-auto"><VisitCounts counts={v.counts} /></span>
          </div>
        </div>
      </div>
    </RowLink>
  );
}
