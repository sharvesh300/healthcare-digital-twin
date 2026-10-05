import { ClipboardList, Stethoscope } from "lucide-react";
import type { Metadata } from "next";

import { CollapsibleSection } from "@/components/record/collapsible";
import { FilterLinks } from "@/components/record/filters";
import { Breadcrumbs, Empty, PageTitle } from "@/components/record/parts";
import { ConditionRow, RowList } from "@/components/record/rows";
import { api } from "@/lib/api/server";
import { recordHref } from "@/lib/record/href";
import { param } from "@/lib/record/load";

export const metadata: Metadata = { title: "Conditions" };

export default async function ConditionsPage({ params, searchParams }: PageProps<"/patients/[id]/record/conditions">) {
  const { id } = await params;
  const query = await searchParams;
  const href = recordHref(id);
  const all = await api.record.conditions(id);
  const kind = param(query, "kind");
  const active = param(query, "active");
  const items = all.items.filter((c) => (!kind || c.kind === kind) && (active == null || String(c.active) === active));
  const count = (k: string) => all.items.filter((c) => c.kind === k).length;
  const ofKind = all.items.filter((c) => !kind || c.kind === kind);
  const sections = [
    { kind: "diagnosis", title: "Diagnoses", icon: Stethoscope },
    { kind: "finding", title: "Social history and findings", icon: ClipboardList },
  ].filter((s) => (!kind || s.kind === kind) && count(s.kind) > 0);

  return (
    <div className="space-y-5">
      <Breadcrumbs items={[{ label: "Record", href: href.overview }, { label: "Conditions" }]} />
      <PageTitle title="Conditions">
        {all.total} conditions · {all.active} active · recurring ones are listed once with their episodes
      </PageTitle>
      <div className="flex flex-wrap items-center gap-2">
        <FilterLinks label="Kind" name="kind" path={href.conditions} params={query}
          options={[{ value: null, label: "All", count: all.total }, { value: "diagnosis", label: "Diagnoses", count: count("diagnosis") },
            { value: "finding", label: "Findings", count: count("finding") }]} />
        <FilterLinks label="Status" name="active" path={href.conditions} params={query}
          options={[{ value: null, label: "Any status" }, { value: "true", label: "Active", count: ofKind.filter((c) => c.active).length },
            { value: "false", label: "Resolved", count: ofKind.filter((c) => !c.active).length }]} />
      </div>
      {sections.length === 0 && <Empty>No conditions in the record.</Empty>}
      {sections.map(({ kind: k, title, icon: Icon }) => {
        const list = items.filter((c) => c.kind === k);
        return (
          <CollapsibleSection key={k} id={`conditions:${k}`} icon={<Icon aria-hidden size={14} className="text-ink-3" />} title={title}
            meta={`${list.length} · ${list.filter((c) => c.active).length} active`} defaultOpen
            preview={<span className="text-xs text-ink-3">{list.slice(0, 6).map((c) => c.display).join(" · ")}{list.length > 6 ? ` · +${list.length - 6} more` : ""}</span>}>
            {list.length ? (
              <RowList>{list.map((c) => <ConditionRow key={c.concept_id} c={c} href={href.condition(c.concept_id)} />)}</RowList>
            ) : (
              <Empty>Nothing matches these filters.</Empty>
            )}
          </CollapsibleSection>
        );
      })}
    </div>
  );
}
