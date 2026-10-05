import { FlaskConical } from "lucide-react";
import type { Metadata } from "next";

import { FilterLinks } from "@/components/record/filters";
import { Breadcrumbs, Empty, PageTitle, SectionCard } from "@/components/record/parts";
import { MeasureRow, RowList } from "@/components/record/rows";
import { api } from "@/lib/api/server";
import { recordHref } from "@/lib/record/href";
import { param } from "@/lib/record/load";

export const metadata: Metadata = { title: "Tests and vitals" };

const out = (flag: string | null) => flag === "high" || flag === "low";

export default async function TestsPage({ params, searchParams }: PageProps<"/patients/[id]/record/tests">) {
  const { id } = await params;
  const query = await searchParams;
  const href = recordHref(id);
  const all = await api.record.tests(id);
  const panel = param(query, "panel");
  const flagged = param(query, "flag") === "out_of_range";
  const panels = all.panels
    .filter((p) => !panel || p.panel === panel)
    .map((p) => ({ ...p, measures: p.measures.filter((m) => !flagged || out(m.latest.flag)) }))
    .filter((p) => p.measures.length);
  const outCount = all.panels.flatMap((p) => p.measures).filter((m) => out(m.latest.flag)).length;

  return (
    <div className="space-y-5">
      <Breadcrumbs items={[{ label: "Record", href: href.overview }, { label: "Tests and vitals" }]} />
      <PageTitle title="Tests and vitals">
        {all.total} tests and vital signs · {outCount} out of range at the latest result
      </PageTitle>
      <div className="flex flex-wrap items-center gap-2">
        <FilterLinks label="Panel" name="panel" path={href.tests} params={query}
          options={[{ value: null, label: "All", count: all.total },
            ...all.panels.map((p) => ({ value: p.panel, label: p.display, count: p.measures.length }))]} />
        <FilterLinks label="Show" name="flag" path={href.tests} params={query}
          options={[{ value: null, label: "Any result" }, { value: "out_of_range", label: "Out of range", count: outCount }]} />
      </div>
      {panels.length ? (
        panels.map((p) => (
          <SectionCard key={p.panel} id={p.panel} icon={<FlaskConical aria-hidden size={14} className="text-ink-3" />}
            title={p.display} meta={`${p.measures.length} test${p.measures.length === 1 ? "" : "s"}`}>
            <RowList>{p.measures.map((m) => <MeasureRow key={m.measure} m={m} href={href.test(m.measure)} />)}</RowList>
          </SectionCard>
        ))
      ) : (
        <Empty>{flagged ? "No test is out of range at its latest result." : "No tests or vitals recorded."}</Empty>
      )}
    </div>
  );
}
