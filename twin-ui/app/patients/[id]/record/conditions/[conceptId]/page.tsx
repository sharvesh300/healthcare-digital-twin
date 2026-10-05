import { CalendarRange, ListOrdered } from "lucide-react";
import type { Metadata } from "next";

import { Card, CardHeader } from "@/components/ui/card";
import { day, DetailHeader, EntryTable, RelatedCard, VisitCell } from "@/components/record/detail";
import { EpisodeTimeline } from "@/components/record/episode-timeline";
import { StatTile, StatusPill, Synthetic, Tag } from "@/components/record/parts";
import { MeasureRow, MedicationRow, RowList } from "@/components/record/rows";
import { api } from "@/lib/api/server";
import { fmtDay, fmtDays, fmtMonth } from "@/lib/record/format";
import { recordHref } from "@/lib/record/href";
import { orNotFound } from "@/lib/record/load";
import { serverNow } from "@/lib/record/now";
import { vital } from "@/lib/tokens";

export const metadata: Metadata = { title: "Condition" };

const SYSTEM: Record<string, string> = { "http://snomed.info/sct": "SNOMED CT", "http://hl7.org/fhir/sid/icd-10-cm": "ICD-10-CM" };

export default async function ConditionDetailPage({ params }: PageProps<"/patients/[id]/record/conditions/[conceptId]">) {
  const { id, conceptId } = await params;
  const href = recordHref(id);
  const d = await orNotFound(api.record.condition(id, conceptId));
  const c = d.condition;
  const now = serverNow();
  const kindLabel = c.kind === "diagnosis" ? "Diagnosis" : "Finding";

  return (
    <div className="space-y-5">
      <DetailHeader
        crumbs={[{ label: "Record", href: href.overview }, { label: "Conditions", href: `${href.conditions}?kind=${c.kind}` }, { label: c.display }]}
        title={c.display}
        badges={<>
          <StatusPill active={c.active} />
          <Tag>{kindLabel}</Tag>
          {c.group_display && <Tag tinted={vital.glucose}>{c.group_display}</Tag>}
          {c.is_synthetic && <Synthetic />}
        </>}
        tiles={<>
          <StatTile label="Status" value={<span className="text-base">{c.active ? "Active" : "Resolved"}</span>}
            hint={c.active ? `since ${fmtDay(c.current.onset_at)}` : `on ${fmtDay(c.current.abated_at)}`} />
          <StatTile label="Episodes" value={c.episodes} hint={c.episodes > 1 ? "it recurred" : "a single episode"} />
          <StatTile label="First recorded" value={<span className="text-base">{fmtMonth(c.first_onset)}</span>} hint={fmtDay(c.first_onset)} />
          <StatTile label="Code" value={<span className="font-mono text-base">{c.code}</span>} hint={SYSTEM[c.system] ?? c.system} />
        </>}
      />

      <Card className="p-5">
        <CardHeader icon={<CalendarRange aria-hidden size={14} className="text-ink-3" />} title="Episodes over time"
          right={<span className="hidden text-[11px] text-ink-3 sm:inline">Click an episode to open its visit</span>} />
        <div className="mt-4">
          <EpisodeTimeline now={now}
            episodes={d.episodes.map((e) => ({ start: e.onset_at, end: e.abated_at, label: c.display, strong: e.active,
              href: e.visit ? href.visit(e.visit.encounter_id) : undefined }))} />
        </div>
      </Card>

      <div className="grid grid-cols-12 gap-5">
        <Card className="col-span-12 p-5 lg:col-span-8">
          <CardHeader icon={<ListOrdered aria-hidden size={14} className="text-ink-3" />} title="Every episode" meta={`${d.episodes.length}, newest first`} />
          <div className="mt-3">
            <EntryTable caption={`Every episode of ${c.display}`}
              columns={[{ label: "Onset", width: "130px" }, { label: "Resolved", width: "130px" }, { label: "Lasted", width: "100px" },
                { label: "Recorded at", width: "minmax(0,1fr)" }]}
              rows={[...d.episodes].reverse().map((e, i) => ({
                key: `${e.onset_at}-${i}`,
                cells: [
                  day(e.onset_at),
                  e.abated_at ? day(e.abated_at) : <StatusPill key="a" active />,
                  <span key="l" className="tabular-nums text-ink-2">{fmtDays(e.duration_days) ?? "ongoing"}</span>,
                  <VisitCell key="v" visit={e.visit} href={href.visit} />,
                ],
              }))} />
          </div>
        </Card>
        <div className="col-span-12 space-y-5 lg:col-span-4">
          <RelatedCard title="Prescribed at these visits" empty="No medications were started at these visits.">
            {d.related.medications.length > 0 && (
              <RowList>{d.related.medications.map((m) => <MedicationRow key={m.rxcui} m={m} href={href.medication(m.rxcui)} />)}</RowList>
            )}
          </RelatedCard>
          <RelatedCard title="Tests that track it" empty={c.group ? "None recorded for this patient." : "No tracking tests for this condition."}>
            {d.related.measures.length > 0 && (
              <RowList>{d.related.measures.map((m) => <MeasureRow key={m.measure} m={m} href={href.test(m.measure)} />)}</RowList>
            )}
          </RelatedCard>
        </div>
      </div>
    </div>
  );
}
