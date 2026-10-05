import { ChartLine, ListOrdered } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { Card, CardHeader } from "@/components/ui/card";
import { day, DetailGrid, DetailHeader, EntryTable, RelatedCard, VisitCell } from "@/components/record/detail";
import { FlagChip, StatTile, Synthetic, Tag } from "@/components/record/parts";
import { ResultsChart } from "@/components/record/results-chart";
import { ConditionRow, MedicationRow, RowList } from "@/components/record/rows";
import { api } from "@/lib/api/server";
import { capitalise, fmtDay, rangeText, resultDelta, resultValue } from "@/lib/record/format";
import { recordHref } from "@/lib/record/href";
import { orNotFound } from "@/lib/record/load";
import { fmtNumber } from "@/lib/twin/format";

export const metadata: Metadata = { title: "Test" };

const ANALYTE: Record<string, string> = { sbp: "Systolic", dbp: "Diastolic" };

export default async function TestDetailPage({ params }: PageProps<"/patients/[id]/record/tests/[measure]">) {
  const { id, measure } = await params;
  const href = recordHref(id);
  const d = await orNotFound(api.record.test(id, measure));
  const m = d.measure;
  const delta = resultDelta(m);
  const range = rangeText(m);
  // a chart only when there is a trend to see: two or more numeric results
  const numeric = d.results.filter((r) => Object.keys(r.values).length > 0).length >= 2;

  return (
    <div className="space-y-5">
      <DetailHeader
        crumbs={[{ label: "Record", href: href.overview }, { label: "Tests and vitals", href: href.tests },
          { label: m.panel_display, href: `${href.tests}?panel=${m.panel}` }, { label: m.display }]}
        title={m.display}
        badges={<>
          <FlagChip flag={m.latest.flag} />
          <Tag>{m.panel_display}</Tag>
          {m.is_synthetic && <Synthetic />}
        </>}
        tiles={<>
          <StatTile label="Latest" value={resultValue(m, m.latest)} unit={m.latest.text ? null : m.unit} hint={fmtDay(m.latest.at)}
            synthetic={m.latest.is_synthetic}>
            <FlagChip flag={m.latest.flag} />
          </StatTile>
          <StatTile label="Change" value={delta ?? "—"} unit={delta && delta !== "no change" ? m.unit : null}
            hint={m.previous ? `since ${fmtDay(m.previous.at)} (${resultValue(m, m.previous)})` : "only one result"} />
          <StatTile label="Reference range" value={range ?? "—"} unit={range ? m.unit : null}
            hint={range ? "adult, for display only" : "no range for this measure"} />
          <StatTile label="Results" value={d.stats.count}
            hint={`${fmtDay(d.stats.first_at)} – ${fmtDay(d.stats.latest_at)}`}>
            {d.stats.out_of_range > 0 && <span className="text-xs text-status-warn">{d.stats.out_of_range} out of range</span>}
          </StatTile>
        </>}
      />

      {numeric && (
        <Card className="p-5">
          <CardHeader icon={<ChartLine aria-hidden size={14} className="text-ink-3" />} title="Over time"
            meta={m.unit ?? undefined}
            right={<span className="hidden text-[11px] text-ink-3 sm:inline">Click a result to open its visit</span>} />
          <div className="mt-4"><ResultsChart detail={d} visitBase={href.visits} /></div>
          <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 border-t border-line pt-3 text-xs text-ink-3">
            {Object.entries(d.stats.by_analyte).map(([a, s]) => (
              <div key={a} className="flex gap-3">
                {m.analytes.length > 1 && <dt className="font-medium text-ink-2">{ANALYTE[a] ?? a}</dt>}
                <dd>Lowest <span className="tabular-nums text-ink-2">{fmtNumber(s.min, m.digits)}</span></dd>
                <dd>Highest <span className="tabular-nums text-ink-2">{fmtNumber(s.max, m.digits)}</span></dd>
                <dd>Average <span className="tabular-nums text-ink-2">{fmtNumber(s.mean, m.digits)}</span></dd>
              </div>
            ))}
          </dl>
        </Card>
      )}

      <DetailGrid
        main={
        <Card className="p-5">
          <CardHeader icon={<ListOrdered aria-hidden size={14} className="text-ink-3" />} title="Every result" meta={`${d.results.length}, newest first`} />
          <div className="mt-3">
            <EntryTable caption={`Every ${m.display} result`} noun="results"
              columns={[{ label: "Date", width: "130px" }, { label: "Result", width: "minmax(0,1fr)" }, { label: "Flag", width: "90px", hide: !d.results.some((r) => r.flag) },
                { label: "Visit", width: "minmax(0,1.4fr)" }, { label: "Source", width: "90px", align: "right" }]}
              rows={[...d.results].reverse().map((r, i) => ({
                key: `${r.at}-${i}`,
                strong: r.flag === "high" || r.flag === "low",
                cells: [
                  day(r.at),
                  <span key="v" className="font-medium tabular-nums text-ink">
                    {resultValue(m, r)}{!r.text && m.unit && <span className="ml-1 text-xs font-normal text-ink-3">{m.unit}</span>}
                  </span>,
                  r.flag ? <FlagChip key="f" flag={r.flag} /> : <span key="f" className="text-ink-3">—</span>,
                  <VisitCell key="vi" visit={r.visit} href={href.visit} source={r.source} />,
                  <span key="s" className="inline-flex items-center gap-1.5 text-xs text-ink-3">
                    {r.is_synthetic ? <Synthetic /> : capitalise(r.source)}
                  </span>,
                ],
              }))} />
          </div>
        </Card>}
        related={<>
          <RelatedCard title={`Also in ${m.panel_display}`}>
            {d.related.panel.length > 0 && (
              <ul className="divide-y divide-line">
                {d.related.panel.map((s) => (
                  <li key={s.measure}>
                    <Link href={href.test(s.measure)} className="flex items-center justify-between gap-2 py-2 text-sm hover:text-primary">
                      <span className="truncate text-ink">{s.display}</span>
                      <span className="flex shrink-0 items-center gap-1.5 tabular-nums text-ink-2">
                        {resultValue(s, s.latest)} <FlagChip flag={s.latest.flag} />
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </RelatedCard>
          <RelatedCard title="Medications that affect it">
            {d.related.medications.length > 0 && (
              <RowList>{d.related.medications.map((x) => <MedicationRow key={x.rxcui} m={x} href={href.medication(x.rxcui)} />)}</RowList>
            )}
          </RelatedCard>
          <RelatedCard title="Diagnoses it tracks">
            {d.related.diagnoses.length > 0 && (
              <RowList>{d.related.diagnoses.map((c) => <ConditionRow key={c.concept_id} c={c} href={href.condition(c.concept_id)} />)}</RowList>
            )}
          </RelatedCard>
        </>} />
    </div>
  );
}
