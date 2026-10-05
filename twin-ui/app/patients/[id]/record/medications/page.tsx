import { History, Pill } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { FilterLinks } from "@/components/record/filters";
import { Breadcrumbs, Empty, PageTitle, SectionCard, Synthetic } from "@/components/record/parts";
import { MedicationRow, RowList } from "@/components/record/rows";
import { api } from "@/lib/api/server";
import { capitalise, fmtDay } from "@/lib/record/format";
import { recordHref } from "@/lib/record/href";
import { param } from "@/lib/record/load";

export const metadata: Metadata = { title: "Medications" };

export default async function MedicationsPage({ params, searchParams }: PageProps<"/patients/[id]/record/medications">) {
  const { id } = await params;
  const query = await searchParams;
  const href = recordHref(id);
  const all = await api.record.medications(id);
  const active = param(query, "active");
  const lowering = param(query, "glucose_lowering") === "true";
  const keep = (m: (typeof all.items)[number]) => (active == null || String(m.active) === active) && (!lowering || m.glucose_lowering);
  const items = all.items.filter(keep);
  const singleDay = all.single_day.filter(keep);

  return (
    <div className="space-y-5">
      <Breadcrumbs items={[{ label: "Record", href: href.overview }, { label: "Medications" }]} />
      <PageTitle title="Medications">
        {all.items.length} prescribed · {all.active} active · {all.single_day.length} given during a visit only
      </PageTitle>
      <div className="flex flex-wrap items-center gap-2">
        <FilterLinks label="Status" name="active" path={href.medications} params={query}
          options={[{ value: null, label: "All" }, { value: "true", label: "Active", count: all.active }, { value: "false", label: "Stopped" }]} />
        <FilterLinks label="Class" name="glucose_lowering" path={href.medications} params={query}
          options={[{ value: null, label: "Any class" },
            { value: "true", label: "Glucose-lowering", count: all.items.filter((m) => m.glucose_lowering).length }]} />
      </div>

      <SectionCard icon={<Pill aria-hidden size={14} className="text-ink-3" />} title="Prescriptions"
        meta={`${items.length} · active first, glucose-lowering first`}>
        {items.length ? (
          <RowList>{items.map((m) => <MedicationRow key={m.rxcui} m={m} href={href.medication(m.rxcui)} />)}</RowList>
        ) : (
          <Empty>No prescriptions match these filters.</Empty>
        )}
      </SectionCard>

      {singleDay.length > 0 && (
        <SectionCard id="single-day" icon={<History aria-hidden size={14} className="text-ink-3" />} title="Given during a visit"
          meta={`${singleDay.length} · anaesthesia, one-off doses`}>
          <ul className="-mx-2 divide-y divide-line">
            {singleDay.map((m) => (
              <li key={m.rxcui}>
                <Link href={href.medication(m.rxcui)}
                  className="flex flex-wrap items-center justify-between gap-x-4 gap-y-0.5 rounded-control px-2 py-2.5 hover:bg-surface-2">
                  <span className="min-w-0">
                    <span className="text-sm font-medium text-ink">{capitalise(m.medication)}</span>
                    <span className="ml-2 truncate text-xs text-ink-3">{m.product}</span>
                  </span>
                  <span className="flex items-center gap-2 text-xs tabular-nums text-ink-3">
                    {fmtDay(m.started_at)}{m.is_synthetic && <Synthetic />}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </SectionCard>
      )}
    </div>
  );
}
