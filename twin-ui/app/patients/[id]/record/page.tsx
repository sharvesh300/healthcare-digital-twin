import { CalendarDays, ClipboardList, Droplet, FlaskConical, History, Info, Pill, Stethoscope } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { DailyCgm } from "@/components/record/daily-cgm";
import { FilterLinks } from "@/components/record/filters";
import { Empty, FlagChip, SectionCard, StatTile, Synthetic } from "@/components/record/parts";
import { ConditionRow, MeasureRow, MedicationRow, RowList, VisitRow } from "@/components/record/rows";
import { api } from "@/lib/api/server";
import type { MeasureSummary, RecordOverview } from "@/lib/api/types";
import { fmtDay, resultValue, titleCaseStatus, visitClass } from "@/lib/record/format";
import { recordHref } from "@/lib/record/href";
import { fmtNumber } from "@/lib/twin/format";

export const metadata: Metadata = { title: "Record" };

const SECTIONS = [
  ["medications", "Medications"],
  ["conditions", "Conditions"],
  ["tests", "Tests and vitals"],
  ["visits", "Visits"],
  ["glucose", "Glucose"],
] as const;

export default async function RecordPage({ params, searchParams }: PageProps<"/patients/[id]/record">) {
  const { id } = await params;
  const query = await searchParams;
  const r = await api.record.overview(id);
  const href = recordHref(id);
  const outOfRange = query.tests === "out_of_range";
  const panels = outOfRange
    ? r.tests.panels
        .map((p) => ({ ...p, measures: p.measures.filter((m) => m.latest.flag === "high" || m.latest.flag === "low") }))
        .filter((p) => p.measures.length)
    : r.tests.panels;
  const { diagnoses, findings } = r.conditions;

  return (
    <div className="space-y-5">
      <p className="flex items-start gap-2 text-xs leading-relaxed text-ink-3">
        <Info aria-hidden size={14} className="mt-px shrink-0 text-primary" />
        {r.provenance.note}
      </p>

      <SummaryTiles r={r} href={href} />

      <nav aria-label="Record sections"
        className="z-10 -mx-1 flex gap-1.5 overflow-x-auto bg-canvas/85 px-1 py-1 backdrop-blur [scrollbar-width:none] lg:sticky lg:top-[133px]">
        {SECTIONS.map(([key, label]) => (
          <a key={key} href={`#${key}`}
            className="whitespace-nowrap rounded-full border border-line bg-surface px-3 py-1 text-xs font-medium text-ink-2 shadow-card transition-colors hover:border-line-strong hover:text-ink">
            {label}
          </a>
        ))}
      </nav>

      <SectionCard id="medications" icon={<Pill aria-hidden size={14} className="text-ink-3" />} title="Medications"
        meta={`${r.medications.active} active · ${r.medications.total} in the record`}
        action={{ href: href.medications, label: "View all" }}>
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
      </SectionCard>

      <div id="conditions" className="grid scroll-mt-48 grid-cols-12 gap-5">
        <SectionCard className="col-span-12 lg:col-span-7" icon={<Stethoscope aria-hidden size={14} className="text-ink-3" />}
          title="Diagnoses" meta={`${diagnoses.active} active · ${diagnoses.total} in the record`}
          action={{ href: `${href.conditions}?kind=diagnosis`, label: "View all" }}>
          {diagnoses.items.length ? (
            <RowList>{diagnoses.items.map((c) => <ConditionRow key={c.concept_id} c={c} href={href.condition(c.concept_id)} />)}</RowList>
          ) : (
            <Empty>No diagnoses recorded.</Empty>
          )}
        </SectionCard>
        <SectionCard className="col-span-12 lg:col-span-5" icon={<ClipboardList aria-hidden size={14} className="text-ink-3" />}
          title="Social history and findings" meta={`${findings.total}`}
          action={{ href: `${href.conditions}?kind=finding`, label: "View all" }}>
          {findings.items.length ? (
            <RowList>{findings.items.map((c) => <ConditionRow key={c.concept_id} c={c} href={href.condition(c.concept_id)} />)}</RowList>
          ) : (
            <Empty>No findings recorded.</Empty>
          )}
        </SectionCard>
      </div>

      <SectionCard id="tests" icon={<FlaskConical aria-hidden size={14} className="text-ink-3" />} title="Tests and vitals"
        meta={`${r.tests.total} tests · ${r.tests.out_of_range} out of range`}
        action={{ href: href.tests, label: "View all" }}
        right={<FilterLinks label="Show" name="tests" path={href.overview} params={query}
          options={[{ value: null, label: "All", count: r.tests.total }, { value: "out_of_range", label: "Out of range", count: r.tests.out_of_range }]} />}>
        {panels.length ? (
          <div className="space-y-4">
            {panels.map((p) => (
              <section key={p.panel} aria-label={p.display}>
                <h3 className="label mb-1 flex items-center justify-between">
                  {p.display}
                  <Link href={`${href.tests}?panel=${p.panel}`} className="normal-case tracking-normal text-ink-3 hover:text-ink-2">
                    {p.measures.length} test{p.measures.length === 1 ? "" : "s"}
                  </Link>
                </h3>
                <RowList>{p.measures.map((m) => <MeasureRow key={m.measure} m={m} href={href.test(m.measure)} />)}</RowList>
              </section>
            ))}
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
      </SectionCard>

      <div className="grid grid-cols-12 gap-5">
        <SectionCard id="visits" className="col-span-12 lg:col-span-5" icon={<CalendarDays aria-hidden size={14} className="text-ink-3" />}
          title="Visits" meta={`${r.visits.total}`} action={{ href: href.visits, label: "View all" }}>
          {r.visits.recent.length ? (
            <RowList>{r.visits.recent.map((v) => <VisitRow key={v.encounter_id} v={v} href={href.visit(v.encounter_id)} />)}</RowList>
          ) : (
            <Empty>No visits recorded.</Empty>
          )}
        </SectionCard>
        <SectionCard id="glucose" className="col-span-12 lg:col-span-7" icon={<Droplet aria-hidden size={14} className="text-vital-glucose" />}
          title="Glucose (CGM)" meta="fused CGM, consensus ranges">
          <Glucose id={id} cgm={r.cgm} />
        </SectionCard>
      </div>
    </div>
  );
}

function SummaryTiles({ r, href }: { r: RecordOverview; href: ReturnType<typeof recordHref> }) {
  const v = r.summary.last_visit;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
      <StatTile label="Medications" value={r.summary.medications_active} href={`${href.medications}?active=true`}
        hint={r.summary.glucose_lowering_active ? `${r.summary.glucose_lowering_active} glucose-lowering` : "none glucose-lowering"}>
        <span className="text-xs text-ink-3">active</span>
      </StatTile>
      <StatTile label="Diagnoses" value={r.summary.diagnoses_active} href={`${href.conditions}?kind=diagnosis&active=true`}
        hint={`${r.conditions.diagnoses.total} in the record`}>
        <span className="text-xs text-ink-3">active</span>
      </StatTile>
      {r.summary.headline.slice(0, 3).map((m) => <HeadlineTile key={m.measure} m={m} href={href.test(m.measure)} />)}
      {v && (
        <StatTile label="Last visit" value={<span className="text-base">{fmtDay(v.start)}</span>} href={href.visit(v.encounter_id)}
          hint={v.type ?? visitClass(v.class)} />
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
