import { CalendarDays } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { FilterLinks, withParam } from "@/components/record/filters";
import { Breadcrumbs, Empty, PageTitle, SectionCard } from "@/components/record/parts";
import { RowList, VisitRow } from "@/components/record/rows";
import { api } from "@/lib/api/server";
import type { VisitSummary } from "@/lib/api/types";
import { fmtYear, visitClass } from "@/lib/record/format";
import { recordHref } from "@/lib/record/href";
import { param } from "@/lib/record/load";

export const metadata: Metadata = { title: "Visits" };

const PAGE = 20;

export default async function VisitsPage({ params, searchParams }: PageProps<"/patients/[id]/record/visits">) {
  const { id } = await params;
  const query = await searchParams;
  const href = recordHref(id);
  const year = param(query, "year");
  const cls = param(query, "class");
  const limit = Math.min(200, Math.max(PAGE, Number(param(query, "limit")) || PAGE));
  const page = await api.record.visits(id, { year: year ? Number(year) : undefined, class: cls ?? undefined, limit });
  const byYear = new Map<string, VisitSummary[]>();
  for (const v of page.items) byYear.set(fmtYear(v.start), [...(byYear.get(fmtYear(v.start)) ?? []), v]);
  const all = page.years.reduce((n, y) => n + y.count, 0);

  return (
    <div className="space-y-5">
      <Breadcrumbs items={[{ label: "Record", href: href.overview }, { label: "Visits" }]} />
      <PageTitle title="Visits">
        {all} visits · each shows the tests, diagnoses and medications recorded at it
      </PageTitle>
      <div className="flex flex-wrap items-center gap-2">
        <FilterLinks label="Kind of visit" name="class" path={href.visits} params={query}
          options={[{ value: null, label: "All", count: all }, ...page.classes.map((c) => ({ value: c.class, label: visitClass(c.class), count: c.count }))]} />
        <FilterLinks label="Year" name="year" path={href.visits} params={query}
          options={[{ value: null, label: "Any year" }, ...page.years.map((y) => ({ value: String(y.year), label: String(y.year), count: y.count }))]} />
      </div>
      <SectionCard icon={<CalendarDays aria-hidden size={14} className="text-ink-3" />} title="Visits"
        meta={`showing ${page.items.length} of ${page.total}, newest first`}>
        {page.items.length ? (
          <div className="space-y-3">
            {[...byYear].map(([y, visits]) => (
              <section key={y} aria-label={y}>
                <h3 className="label mb-1">{y}</h3>
                <RowList>{visits.map((v) => <VisitRow key={v.encounter_id} v={v} href={href.visit(v.encounter_id)} />)}</RowList>
              </section>
            ))}
          </div>
        ) : (
          <Empty>No visits match these filters.</Empty>
        )}
        {page.next_cursor && (
          <Link href={withParam(href.visits, query, "limit", String(limit + PAGE))} scroll={false}
            className="mt-3 inline-flex w-full justify-center rounded-control border border-line bg-surface-2 px-3 py-2 text-xs font-medium text-ink-2 hover:text-ink">
            Show {Math.min(PAGE, page.total - page.items.length)} more
          </Link>
        )}
      </SectionCard>
    </div>
  );
}
