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

/** Links to related entries, in a side card. With none, it renders nothing: no card that
 *  only says "none". When no related card renders, the main column widens (see `DetailGrid`). */
export function RelatedCard({ title, children }: { title: string; children?: ReactNode }) {
  const has = Array.isArray(children) ? children.some(Boolean) : Boolean(children);
  if (!has) return null;
  return (
    <Card className="p-5" data-related>
      <h3 className="label">{title}</h3>
      <div className="mt-2">{children}</div>
    </Card>
  );
}

/** The table of every occurrence beside its related cards; full width when there are none. */
export function DetailGrid({ main, related }: { main: ReactNode; related: ReactNode }) {
  return (
    <div className="group/rel grid grid-cols-12 gap-5">
      <div className="col-span-12 group-has-[[data-related]]/rel:lg:col-span-8">{main}</div>
      <div className="col-span-12 space-y-5 empty:hidden lg:col-span-4">{related}</div>
    </div>
  );
}

const STUDIES = new Set(["cgmacros", "bigideas"]);

/** Where an entry was recorded: a link to its visit; otherwise plain text (a research study's
 *  visit, or no visit on record), never a link to a page that doesn't exist. */
export function VisitCell({ visit, href, source }: { visit: VisitBrief | null; href: (id: string) => string; source?: string }) {
  if (!visit) return <span className="text-ink-3">{source && STUDIES.has(source) ? "Study visit" : "No visit on record"}</span>;
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
  /** no row has a value for it: the column is left out rather than filled with "—" */
  hide?: boolean;
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
  const shown = columns.map((c, i) => [c, i] as const).filter(([c]) => !c.hide);
  const template = shown.map(([c]) => c.width).join(" ");
  return (
    <div role="table" aria-label={caption} className="text-sm">
      <div role="row" className="hidden gap-3 border-b border-line px-2 pb-2 sm:grid" style={{ gridTemplateColumns: template }}>
        {shown.map(([c]) => (
          <span key={c.label} role="columnheader" className={cn("label", c.align === "right" && "text-right")}>{c.label}</span>
        ))}
      </div>
      <div role="rowgroup" className="divide-y divide-line">
        <ShowMore limit={limit} noun={noun} items={rows.map((r) => (
          <div key={r.key} role="row" className={cn("grid grid-cols-2 gap-x-3 gap-y-1 px-2 py-2.5 sm:[grid-template-columns:var(--cols)] sm:items-center",
            r.strong && "bg-[color-mix(in_srgb,var(--status-warn)_4%,transparent)]")}
            style={{ ["--cols" as string]: template }}>
            {shown.map(([c, i]) => (
              <span key={i} role="cell" className={cn("min-w-0", c.align === "right" && "sm:text-right")}>
                <span className="mr-1 text-[11px] text-ink-3 sm:hidden">{c.label}</span>
                {r.cells[i]}
              </span>
            ))}
          </div>
        ))} />
      </div>
    </div>
  );
}

export const day = (iso: string | null | undefined) => <span className="tabular-nums text-ink-2">{fmtDay(iso)}</span>;
