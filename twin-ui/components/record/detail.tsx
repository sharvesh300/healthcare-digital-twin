import { ChevronRight } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import type { VisitBrief } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { fmtDay, visitClass } from "@/lib/record/format";

import { ShowMore } from "./collapsible";
import { Breadcrumbs } from "./parts";

/** The top of every detail page: breadcrumbs, title with badges, and stat tiles. */
export function DetailHeader({ crumbs, title, badges, tiles, aside }: {
  crumbs: { label: string; href?: string }[];
  title: ReactNode;
  badges?: ReactNode;
  tiles?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <header className="space-y-4">
      <Breadcrumbs items={crumbs} />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-2xl font-semibold tracking-tight text-ink">{title}</h2>
          {badges && <div className="mt-2 flex flex-wrap items-center gap-1.5">{badges}</div>}
        </div>
        {aside}
      </div>
      {tiles && <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{tiles}</div>}
    </header>
  );
}

/** Links to related entries, in a side card; says so when there are none. */
export function RelatedCard({ title, empty, children }: { title: string; empty: string; children?: ReactNode }) {
  const has = Array.isArray(children) ? children.some(Boolean) : Boolean(children);
  return (
    <Card className="p-5">
      <h3 className="label">{title}</h3>
      <div className="mt-2">{has ? children : <p className="py-2 text-sm text-ink-3">{empty}</p>}</div>
    </Card>
  );
}

/** Where an entry was recorded: a link to its visit, or "Study visit" for research data. */
export function VisitCell({ visit, href }: { visit: VisitBrief | null; href: (id: string) => string }) {
  if (!visit) return <span className="text-ink-3">Study visit</span>;
  return (
    <Link href={href(visit.encounter_id)} className="group inline-flex min-w-0 items-center gap-1 text-primary hover:underline">
      <span className="truncate">{visit.type ?? visitClass(visit.class)}</span>
      <ChevronRight aria-hidden size={13} className="shrink-0" />
    </Link>
  );
}

export interface Column {
  label: string;
  /** grid track for sm+ (e.g. "120px", "minmax(0,1fr)") */
  width: string;
  align?: "right";
}

/** Every occurrence of an entry (results, episodes, prescriptions). A table from sm up;
 *  on phones each row stacks, its cells labelled. */
export function EntryTable({ columns, rows, caption, limit = 10, noun }: {
  columns: Column[];
  rows: { key: string; cells: ReactNode[]; strong?: boolean }[];
  caption: string;
  /** rows shown before "Show all" */
  limit?: number;
  noun?: string;
}) {
  const template = columns.map((c) => c.width).join(" ");
  return (
    <div role="table" aria-label={caption} className="text-sm">
      <div role="row" className="hidden gap-3 border-b border-line px-2 pb-2 sm:grid" style={{ gridTemplateColumns: template }}>
        {columns.map((c) => (
          <span key={c.label} role="columnheader" className={cn("label", c.align === "right" && "text-right")}>{c.label}</span>
        ))}
      </div>
      <div role="rowgroup" className="divide-y divide-line">
        <ShowMore limit={limit} noun={noun} items={rows.map((r) => (
          <div key={r.key} role="row" className={cn("grid grid-cols-2 gap-x-3 gap-y-1 px-2 py-2.5 sm:[grid-template-columns:var(--cols)] sm:items-center",
            r.strong && "bg-[color-mix(in_srgb,var(--status-warn)_4%,transparent)]")}
            style={{ ["--cols" as string]: template }}>
            {r.cells.map((cell, i) => (
              <span key={i} role="cell" className={cn("min-w-0", columns[i].align === "right" && "sm:text-right")}>
                <span className="mr-1 text-[11px] text-ink-3 sm:hidden">{columns[i].label}</span>
                {cell}
              </span>
            ))}
          </div>
        ))} />
      </div>
    </div>
  );
}

export const day = (iso: string | null | undefined) => <span className="tabular-nums text-ink-2">{fmtDay(iso)}</span>;
