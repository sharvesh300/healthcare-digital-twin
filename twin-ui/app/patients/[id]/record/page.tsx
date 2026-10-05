import { CalendarDays, ChevronRight, ClipboardList, Droplet, FlaskConical, History, Info, Pill, Stethoscope } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { CollapsibleGroup, CollapsibleSection, PreviewChips, SectionNav } from "@/components/record/collapsible";
import { DailyCgm } from "@/components/record/daily-cgm";
import { FilterLinks } from "@/components/record/filters";
import { Empty, FlagChip, StatTile, Synthetic } from "@/components/record/parts";
import { ConditionRow, MeasureRow, MedicationRow, RowList, VisitRow } from "@/components/record/rows";
import { api } from "@/lib/api/server";
import type { ConditionSummary, MeasureSummary, RecordOverview } from "@/lib/api/types";
import { capitalise, fmtDay, resultValue, titleCaseStatus, visitClass } from "@/lib/record/format";
import { recordHref } from "@/lib/record/href";
import { fmtNumber } from "@/lib/twin/format";

export const metadata: Metadata = { title: "Record" };

const SECTIONS = [
  ["medications", "Medications"],
  ["diagnoses", "Diagnoses"],
  ["findings", "Social history"],
  ["tests", "Tests and vitals"],
  ["visits", "Visits"],
  ["glucose", "Glucose"],
] as const;

const isFlagged = (m: MeasureSummary) => m.latest.flag === "high" || m.latest.flag === "low";

export default async function RecordPage({ params, searchParams }: PageProps<"/patients/[id]/record">) {
  const { id } = await params;
  const query = await searchParams;
  const r = await api.record.overview(id);
  const href = recordHref(id);
  const outOfRange = query.tests === "out_of_range";
  const panels = outOfRange
    ? r.tests.panels
        .map((p) => ({ ...p, measures: p.measures.filter(isFlagged) }))
        .filter((p) => p.measures.length)
    : r.tests.panels;
  const { diagnoses, findings } = r.conditions;
  const activeMeds = r.medications.items.filter((m) => m.active);
  const visitsWithRecords = r.visits.recent.filter((v) => v.has_records);
  // a section with nothing in the record is a quiet bar: it doesn't open and offers no "View all"
  const empty: Record<(typeof SECTIONS)[number][0], boolean> = {
    medications: r.medications.total === 0,
    diagnoses: diagnoses.total === 0,
    findings: findings.total === 0,
    tests: r.tests.total === 0,
    visits: r.visits.total === 0,
    glucose: !r.cgm?.window,
  };
  const none = "None in the record";
  const flagged = r.tests.panels.flatMap((p) => p.measures).filter(isFlagged);

  return (
    <div className="space-y-5">
      <p className="flex items-start gap-2 text-xs leading-relaxed text-ink-3">
        <Info aria-hidden size={14} className="mt-px shrink-0 text-primary" />
        {r.provenance.note}
      </p>

      <SummaryTiles r={r} href={href} />

      <SectionNav sections={SECTIONS.filter(([sid]) => !empty[sid])
        .map(([sid, label]) => ({ id: sid, label, defaultOpen: sid === "tests" && outOfRange }))} />

      <div className="space-y-3">
        <CollapsibleSection id="medications" icon={<Pill aria-hidden size={14} className="text-ink-3" />} title="Medications"
          meta={`${r.medications.active} active · ${r.medications.total} in the record`}
          action={{ href: href.medications, label: "View all" }} empty={empty.medications}
          preview={empty.medications ? none : <PreviewChips empty="No active medications."
            items={activeMeds.slice(0, 4).map((m) => ({ key: String(m.rxcui), href: href.medication(m.rxcui),
              label: <>{capitalise(m.medication)}{m.dosage.text && <span className="text-ink-3">· {m.dosage.text}</span>}</> }))}
            more={activeMeds.length - 4} />}>
          {r.medications.items.length ? (
            <RowList>{r.medications.items.map((m) => <MedicationRow key={m.rxcui} m={m} href={href.medication(m.rxcui)} />)}</RowList>
          ) : (
            <Empty>No medications in the record.</Empty>
          )}
          {r.medications.single_day > 0 && (
            <Link href={`${href.medications}#single-day`} className="mt-2 inline-flex items-center gap-1 text-xs text-ink-3 hover:text-ink-2">
              <History aria-hidden size={12} /> {r.medications.single_day} more given during a visit only (anaesthesia, one-off doses)
            </Link>
          )}
        </CollapsibleSection>

        <CollapsibleSection id="diagnoses" icon={<Stethoscope aria-hidden size={14} className="text-ink-3" />}
          title="Diagnoses" meta={`${diagnoses.active} active · ${diagnoses.total} in the record`}
          action={{ href: `${href.conditions}?kind=diagnosis`, label: "View all" }} empty={empty.diagnoses}
          preview={empty.diagnoses ? none : <ConditionChips items={diagnoses.items} href={href} empty={`No active diagnoses · ${diagnoses.total} resolved`} />}>
          {diagnoses.items.length ? (
            <RowList>{diagnoses.items.map((c) => <ConditionRow key={c.concept_id} c={c} href={href.condition(c.concept_id)} />)}</RowList>
          ) : (
            <Empty>No diagnoses recorded.</Empty>
          )}
        </CollapsibleSection>

        <CollapsibleSection id="findings" icon={<ClipboardList aria-hidden size={14} className="text-ink-3" />}
          title="Social history and findings" meta={`${findings.active} current · ${findings.total} in the record`}
          action={{ href: `${href.conditions}?kind=finding`, label: "View all" }} empty={empty.findings}
          preview={empty.findings ? none : <ConditionChips items={findings.items} href={href} empty="No current findings." />}>
          {findings.items.length ? (
            <RowList>{findings.items.map((c) => <ConditionRow key={c.concept_id} c={c} href={href.condition(c.concept_id)} />)}</RowList>
          ) : (
            <Empty>No findings recorded.</Empty>
          )}
        </CollapsibleSection>

        <CollapsibleSection id="tests" icon={<FlaskConical aria-hidden size={14} className="text-ink-3" />} title="Tests and vitals"
          meta={`${r.tests.total} tests · ${r.tests.out_of_range} out of range`} defaultOpen={outOfRange}
          action={{ href: href.tests, label: "View all" }} empty={empty.tests}
          controls={<FilterLinks label="Show" name="tests" path={href.overview} params={query}
            options={[{ value: null, label: "All", count: r.tests.total }, { value: "out_of_range", label: "Out of range", count: r.tests.out_of_range }]} />}
          preview={empty.tests ? none : <PreviewChips empty="Every latest result is within its reference range."
            items={flagged.slice(0, 5).map((m) => ({ key: m.measure, href: href.test(m.measure), tone: "warn" as const,
              label: <>{m.display} <span className="font-semibold tabular-nums">{resultValue(m, m.latest)}</span>{m.latest.flag === "high" ? " ↑" : " ↓"}</> }))}
            more={flagged.length - 5} />}>
          {panels.length ? (
            <div>
              {panels.map((p) => {
                const out = p.measures.filter(isFlagged);
                return (
                  <CollapsibleGroup key={p.panel} id={`panel:${p.panel}`} title={p.display} defaultOpen={out.length > 0}
                    meta={`${p.measures.length} test${p.measures.length === 1 ? "" : "s"}${out.length ? ` · ${out.length} out of range` : ""}`}
                    preview={out.slice(0, 3).map((m) => (
                      <span key={m.measure} className="whitespace-nowrap rounded-full bg-[color-mix(in_srgb,var(--status-warn)_10%,white)] px-2 py-0.5 text-[11px] text-ink">
                        {m.display} {m.latest.flag === "high" ? "↑" : "↓"}
                      </span>
                    ))}>
                    <RowList>{p.measures.map((m) => <MeasureRow key={m.measure} m={m} href={href.test(m.measure)} />)}</RowList>
                    <Link href={`${href.tests}?panel=${p.panel}`} className="mt-1 inline-flex items-center gap-0.5 text-xs text-ink-3 hover:text-ink-2">
                      Open the {p.display.toLowerCase()} panel <ChevronRight aria-hidden size={12} />
                    </Link>
                  </CollapsibleGroup>
                );
              })}
            </div>
          ) : (
            <Empty>{outOfRange ? "Every latest result is within its reference range." : "No tests or vitals recorded."}</Empty>
          )}
          {Object.keys(r.derived).length > 0 && (
            <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line pt-3 text-xs">
              <span className="label">Derived</span>
              {Object.entries(r.derived).map(([k, d]) => (
                <span key={k} className="inline-flex items-center gap-1.5 text-ink-2">
                  {d.display}
                  <span className="font-semibold tabular-nums text-ink">{fmtNumber(d.value, d.value < 10 ? 2 : 0)}</span>
                  {d.unit && <span className="text-ink-3">{d.unit}</span>}
                  {d.is_synthetic && <Synthetic />}
                </span>
              ))}
            </div>
          )}
        </CollapsibleSection>

        <CollapsibleSection id="visits" icon={<CalendarDays aria-hidden size={14} className="text-ink-3" />}
          title="Visits" meta={`${r.visits.total} in the record · ${r.visits.with_records} with records`}
          action={{ href: href.visits, label: "View all" }} empty={empty.visits}
          preview={empty.visits ? none : <PreviewChips empty="Nothing was recorded at the latest visits."
            items={visitsWithRecords.slice(0, 3).map((v) => ({ key: v.encounter_id, href: href.visit(v.encounter_id),
              label: <><span className="tabular-nums text-ink-3">{fmtDay(v.start)}</span> {v.type ?? visitClass(v.class)}</> }))}
            more={r.visits.with_records - Math.min(3, visitsWithRecords.length)} />}>
          {r.visits.recent.length ? (
            <RowList>{r.visits.recent.map((v) => <VisitRow key={v.encounter_id} v={v} href={href.visit(v.encounter_id)} />)}</RowList>
          ) : (
            <Empty>No visits recorded.</Empty>
          )}
        </CollapsibleSection>

        <CollapsibleSection id="glucose" icon={<Droplet aria-hidden size={14} className="text-vital-glucose" />}
          title="Glucose (CGM)" meta={empty.glucose ? undefined : "fused CGM, consensus ranges"} empty={empty.glucose}
          preview={empty.glucose ? "No CGM recording for this patient" : <GlucosePreview cgm={r.cgm} />}>
          <Glucose id={id} cgm={r.cgm} />
        </CollapsibleSection>
      </div>
    </div>
  );
}

function SummaryTiles({ r, href }: { r: RecordOverview; href: ReturnType<typeof recordHref> }) {
  const v = r.summary.last_visit;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
      <StatTile label="Medications" value={r.summary.medications_active}
        href={r.summary.medications_active ? `${href.medications}?active=true` : undefined}
        hint={r.summary.glucose_lowering_active ? `${r.summary.glucose_lowering_active} glucose-lowering` : "none glucose-lowering"}>
        <span className="text-xs text-ink-3">active</span>
      </StatTile>
      <StatTile label="Diagnoses" value={r.summary.diagnoses_active}
        href={r.summary.diagnoses_active ? `${href.conditions}?kind=diagnosis&active=true` : r.conditions.diagnoses.total ? `${href.conditions}?kind=diagnosis` : undefined}
        hint={`${r.conditions.diagnoses.total} in the record`}>
        <span className="text-xs text-ink-3">active</span>
      </StatTile>
      {r.summary.headline.slice(0, 3).map((m) => <HeadlineTile key={m.measure} m={m} href={href.test(m.measure)} />)}
      {v && (
        <StatTile label="Last visit" value={<span className="text-base">{fmtDay(v.start)}</span>}
          href={v.has_records ? href.visit(v.encounter_id) : undefined}
          hint={v.has_records ? (v.type ?? visitClass(v.class)) : `${v.type ?? visitClass(v.class)} · nothing recorded`} />
      )}
    </div>
  );
}

function HeadlineTile({ m, href }: { m: MeasureSummary; href: string }) {
  return (
    <StatTile label={m.display} value={resultValue(m, m.latest)} unit={m.unit} href={href} synthetic={m.latest.is_synthetic}
      hint={fmtDay(m.latest.at)}>
      <FlagChip flag={m.latest.flag} />
    </StatTile>
  );
}

function Glucose({ id, cgm }: { id: string; cgm: RecordOverview["cgm"] }) {
  if (!cgm?.window) return <Empty>No CGM recording for this patient.</Empty>;
  const w = cgm.window;
  const c = cgm.consistency;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Fact label="Recording" value={`${fmtDay(w.period_start)} – ${fmtDay(w.period_end)}`} small />
        <Fact label="Mean" value={fmtNumber(w.mean_mg_dl)} unit="mg/dL" />
        <Fact label="GMI" value={fmtNumber(w.gmi, 1)} unit="%" />
        <Fact label="HbA1c vs GMI" value={c ? titleCaseStatus(c.status) : "—"} small
          hint={c?.hba1c != null && c.abs_diff != null ? `HbA1c ${fmtNumber(c.hba1c, 1)} % · gap ${fmtNumber(c.abs_diff, 1)}` : undefined} />
      </div>
      <DailyCgm daily={cgm.daily} />
      <Link href={`/patients/${id}?at=${encodeURIComponent(w.period_end)}`}
        className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline">
        <History aria-hidden size={13} /> Replay these days in the live twin
      </Link>
    </div>
  );
}

function Fact({ label, value, unit, hint, small }: { label: string; value: string; unit?: string; hint?: string; small?: boolean }) {
  return (
    <div className="min-w-0 rounded-control bg-surface-2 px-3 py-2.5">
      <div className="label">{label}</div>
      <div className={small ? "mt-1 text-sm font-medium text-ink" : "mt-1 text-lg font-semibold tabular-nums text-ink"}>
        {value}{unit && <span className="ml-1 text-xs font-normal text-ink-3">{unit}</span>}
      </div>
      {hint && <div className="mt-0.5 truncate text-[11px] text-ink-3">{hint}</div>}
    </div>
  );
}

function ConditionChips({ items, href, empty }: { items: ConditionSummary[]; href: ReturnType<typeof recordHref>; empty: string }) {
  const active = items.filter((c) => c.active);
  return (
    <PreviewChips empty={empty} more={active.length - 4}
      items={active.slice(0, 4).map((c) => ({ key: String(c.concept_id), href: href.condition(c.concept_id),
        label: <>{c.display}{c.episodes > 1 && <span className="text-ink-3">×{c.episodes}</span>}</> }))} />
  );
}

function GlucosePreview({ cgm }: { cgm: RecordOverview["cgm"] }) {
  if (!cgm?.window) return <span className="text-xs text-ink-3">No CGM recording for this patient.</span>;
  const w = cgm.window;
  return (
    <span className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-2">
      <span className="tabular-nums">{fmtDay(w.period_start)} – {fmtDay(w.period_end)}</span>
      <span>Mean <span className="font-semibold tabular-nums text-ink">{fmtNumber(w.mean_mg_dl)}</span> mg/dL</span>
      <span>GMI <span className="font-semibold tabular-nums text-ink">{fmtNumber(w.gmi, 1)}</span> %</span>
      {cgm.consistency && <span>HbA1c vs GMI <span className="font-medium text-ink">{titleCaseStatus(cgm.consistency.status).toLowerCase()}</span></span>}
      <span className="text-ink-3">{cgm.daily.length} days</span>
    </span>
  );
}
