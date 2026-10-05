import { ArrowRight, CalendarRange, ListOrdered } from "lucide-react";
import type { Metadata } from "next";

import { Card, CardHeader } from "@/components/ui/card";
import { day, DetailHeader, EntryTable, RelatedCard, VisitCell } from "@/components/record/detail";
import { EpisodeTimeline } from "@/components/record/episode-timeline";
import { StatTile, StatusPill, Synthetic, Tag } from "@/components/record/parts";
import { ConditionRow, MeasureRow, RowList } from "@/components/record/rows";
import { api } from "@/lib/api/server";
import { capitalise, fmtDay, fmtMonth } from "@/lib/record/format";
import { recordHref } from "@/lib/record/href";
import { orNotFound } from "@/lib/record/load";
import { serverNow } from "@/lib/record/now";
import { vital } from "@/lib/tokens";

export const metadata: Metadata = { title: "Medication" };

export default async function MedicationDetailPage({ params }: PageProps<"/patients/[id]/record/medications/[rxcui]">) {
  const { id, rxcui } = await params;
  const href = recordHref(id);
  const d = await orNotFound(api.record.medication(id, rxcui));
  const m = d.medication;
  const name = capitalise(m.medication);

  return (
    <div className="space-y-5">
      <DetailHeader
        crumbs={[{ label: "Record", href: href.overview }, { label: "Medications", href: href.medications }, { label: name }]}
        title={name}
        badges={<>
          <StatusPill active={m.active} inactive="Stopped" />
          {m.glucose_lowering && <Tag tinted={vital.glucose}>Glucose-lowering</Tag>}
          {m.drug_class_display && <Tag>{m.drug_class_display}</Tag>}
          {m.single_day && <Tag>Given during a visit</Tag>}
          {m.is_synthetic && <Synthetic />}
        </>}
        tiles={<>
          <StatTile label="Dosage" value={<span className="text-base">{m.dosage.text ? capitalise(m.dosage.text) : "Not recorded"}</span>}
            hint={m.dosage.text ? "latest prescription" : "the source gave no dose or frequency"} />
          <StatTile label="Product" value={<span className="line-clamp-2 text-sm font-medium leading-snug">{m.product ?? "Not recorded"}</span>}
            hint={`RxNorm ingredient ${m.rxcui}`} />
          <StatTile label={m.active ? "Taking since" : "Taken"} value={<span className="text-base">{fmtMonth(m.started_at)}</span>}
            hint={m.active ? fmtDay(m.started_at) : `until ${fmtDay(m.ended_at)}`} />
          <StatTile label="Prescriptions" value={m.episodes} hint={`first ${fmtDay(m.first_started_at)}`} />
        </>}
      />

      <Card className="p-5">
        <CardHeader icon={<CalendarRange aria-hidden size={14} className="text-ink-3" />} title="Prescriptions over time"
          meta={d.dose_changes.length ? `${d.dose_changes.length} change${d.dose_changes.length === 1 ? "" : "s"} of product or dose` : undefined} />
        <div className="mt-4">
          <EpisodeTimeline now={serverNow()} color={m.glucose_lowering ? vital.glucose : "var(--primary)"}
            episodes={d.episodes.map((e) => ({ start: e.started_at, end: e.ended_at, label: e.product ?? name, strong: e.active,
              href: e.visit ? href.visit(e.visit.encounter_id) : undefined }))}
            markers={d.dose_changes.map((c) => ({ at: c.at, label: `Changed ${fmtDay(c.at)}: ${c.to}` }))} />
        </div>
        {d.dose_changes.length > 0 && (
          <ul className="mt-4 space-y-1.5 border-t border-line pt-3 text-xs">
            {d.dose_changes.map((c) => (
              <li key={c.at} className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-ink-2">
                <span className="tabular-nums text-ink-3">{fmtDay(c.at)}</span>
                <span>{c.from}</span>
                <ArrowRight aria-hidden size={12} className="text-ink-3" />
                <span className="font-medium text-ink">{c.to}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="grid grid-cols-12 gap-5">
        <Card className="col-span-12 p-5 lg:col-span-8">
          <CardHeader icon={<ListOrdered aria-hidden size={14} className="text-ink-3" />} title="Every prescription" meta={`${d.episodes.length}, newest first`} />
          <div className="mt-3">
            <EntryTable caption={`Every prescription of ${name}`} noun="prescriptions"
              columns={[{ label: "Product", width: "minmax(0,1.6fr)" }, { label: "Dosage", width: "minmax(0,1fr)" },
                { label: "Started", width: "120px" }, { label: "Ended", width: "120px" }, { label: "Prescribed at", width: "minmax(0,1fr)" }]}
              rows={[...d.episodes].reverse().map((e) => ({
                key: String(e.regimen_id),
                cells: [
                  <span key="p" className="line-clamp-2 text-ink">{e.product ?? "Not recorded"}</span>,
                  <span key="d" className={e.dosage.text ? "text-ink-2" : "text-ink-3"}>{e.dosage.text ? capitalise(e.dosage.text) : "Not recorded"}</span>,
                  day(e.started_at),
                  e.ended_at ? day(e.ended_at) : <StatusPill key="a" active />,
                  <VisitCell key="v" visit={e.visit} href={href.visit} />,
                ],
              }))} />
          </div>
        </Card>
        <div className="col-span-12 space-y-5 lg:col-span-4">
          <RelatedCard title="Diagnosed at the prescribing visits" empty="Nothing was diagnosed at these visits.">
            {d.related.diagnoses.length > 0 && (
              <RowList>{d.related.diagnoses.map((c) => <ConditionRow key={c.concept_id} c={c} href={href.condition(c.concept_id)} />)}</RowList>
            )}
          </RelatedCard>
          <RelatedCard title="Tests it affects" empty={m.drug_class ? "None recorded for this patient." : "No tracked tests for this medication."}>
            {d.related.measures.length > 0 && (
              <RowList>{d.related.measures.map((x) => <MeasureRow key={x.measure} m={x} href={href.test(x.measure)} />)}</RowList>
            )}
          </RelatedCard>
        </div>
      </div>
    </div>
  );
}
