import { CalendarDays } from "lucide-react";
import type { Metadata } from "next";

import { CollapsibleGroup } from "@/components/record/collapsible";
import { FilterLinks } from "@/components/record/filters";
import { Breadcrumbs, Empty, PageTitle, SectionCard } from "@/components/record/parts";
import { RowList, VisitRow } from "@/components/record/rows";
import { api } from "@/lib/api/server";
import type { VisitSummary } from "@/lib/api/types";
import { fmtYear, visitClass } from "@/lib/record/format";
import { recordHref } from "@/lib/record/href";
import { param } from "@/lib/record/load";

export const metadata: Metadata = { title: "Visits" };

// Every visit at once (the API caps a page at 200; no twin has more than about 100): the
// years open and close, so the list stays short without paging.
const ALL = 200;

export default async function VisitsPage({ params, searchParams }: PageProps<"/patients/[id]/record/visits">) {
  const { id } = await params;
  const query = await searchParams;
  const href = recordHref(id);
  const year = param(query, "year");
  const cls = param(query, "class");
  const page = await api.record.visits(id, { year: year ? Number(year) : undefined, class: cls ?? undefined, limit: ALL });
  const byYear = new Map<string, VisitSummary[]>();
  for (const v of page.items) byYear.set(fmtYear(v.start), [...(byYear.get(fmtYear(v.start)) ?? []), v]);
  // facets count what each choice would show with the other filter applied
  const inYear = page.classes.reduce((n, c) => n + c.count, 0);
  const ofClass = page.years.reduce((n, y) => n + y.count, 0);

  return (
    <div className="space-y-5">
      <Breadcrumbs items={[{ label: "Record", href: href.overview }, { label: "Visits" }]} />
      <PageTitle title="Visits">
        {year || cls ? `${page.total} matching visits` : `${page.total} visits`} · each shows the tests, diagnoses and medications recorded at it
      </PageTitle>
      <div className="flex flex-wrap items-center gap-2">
        <FilterLinks label="Kind of visit" name="class" path={href.visits} params={query}
          options={[{ value: null, label: "All", count: inYear }, ...page.classes.map((c) => ({ value: c.class, label: visitClass(c.class), count: c.count }))]} />
        <FilterLinks label="Year" name="year" path={href.visits} params={query}
          options={[{ value: null, label: "Any year", count: ofClass }, ...page.years.map((y) => ({ value: String(y.year), label: String(y.year), count: y.count }))]} />
      </div>
      <SectionCard icon={<CalendarDays aria-hidden size={14} className="text-ink-3" />} title="Visits"
        meta={`${page.total}, newest first · visits with nothing recorded are greyed out`}>
        {page.items.length ? (
          <div>
            {[...byYear].map(([y, visits], i) => {
              const urgent = visits.filter((v) => v.class === "inpatient" || v.class === "emergency").length;
              const withRecords = visits.filter((v) => v.has_records).length;
              return (
                <CollapsibleGroup key={y} id={`visits-year:${y}`} title={y} defaultOpen={i === 0 || Boolean(year)}
                  meta={`${visits.length} visit${visits.length === 1 ? "" : "s"}${withRecords < visits.length ? ` · ${withRecords} with records` : ""}${urgent ? ` · ${urgent} inpatient or emergency` : ""}`}>
                  <RowList>{visits.map((v) => <VisitRow key={v.encounter_id} v={v} href={href.visit(v.encounter_id)} />)}</RowList>
                </CollapsibleGroup>
              );
            })}
          </div>
        ) : (
          <Empty>No visits match these filters.</Empty>
        )}
      </SectionCard>
    </div>
  );
}
