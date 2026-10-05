import { ChevronLeft, ChevronRight, FlaskConical, Pill, Stethoscope } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { DetailHeader } from "@/components/record/detail";
import { Empty, FlagChip, SectionCard, StatTile, Synthetic, Tag } from "@/components/record/parts";
import { ConditionRow, MedicationRow, RowList, VISIT_ICON } from "@/components/record/rows";
import { api } from "@/lib/api/server";
import type { VisitSummary } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { fmtDay, fmtDuration, resultValue, visitClass } from "@/lib/record/format";
import { recordHref } from "@/lib/record/href";
import { orNotFound } from "@/lib/record/load";
import { fmtTime } from "@/lib/twin/format";

export const metadata: Metadata = { title: "Visit" };

export default async function VisitDetailPage({ params }: PageProps<"/patients/[id]/record/visits/[encounterId]">) {
  const { id, encounterId } = await params;
  const href = recordHref(id);
  const d = await orNotFound(api.record.visit(id, encounterId));
  const v = d.visit;
  const Icon = VISIT_ICON[v.class] ?? Stethoscope;
  const title = v.type ?? visitClass(v.class);
  const tests = d.tests.reduce((n, p) => n + p.items.length, 0);

  return (
    <div className="space-y-5">
      <DetailHeader
        crumbs={[{ label: "Record", href: href.overview }, { label: "Visits", href: href.visits }, { label: `${title}, ${fmtDay(v.start)}` }]}
        title={title}
        badges={<>
          <Tag><Icon aria-hidden size={12} className="mr-1" />{visitClass(v.class)}</Tag>
          {v.reason && <span className="text-sm text-ink-2">for {v.reason}</span>}
          {v.is_synthetic && <Synthetic />}
        </>}
        aside={<StepLinks previous={d.previous} next={d.next} href={href.visit} />}
        tiles={<>
          <StatTile label="Date" value={<span className="text-base">{fmtDay(v.start)}</span>} hint={`${fmtTime(v.start)}${v.end ? ` – ${fmtTime(v.end)}` : ""}`} />
          <StatTile label="Length" value={<span className="text-base">{fmtDuration(v.duration_h) ?? "—"}</span>}
            hint={v.end && v.duration_h != null && v.duration_h >= 24 ? `until ${fmtDay(v.end)}` : visitClass(v.class)} />
          <StatTile label="Tests and vitals" value={tests} hint={tests ? `in ${d.tests.length} panel${d.tests.length === 1 ? "" : "s"}` : "none recorded"} />
          <StatTile label="Diagnoses · medications" value={`${d.diagnoses.recorded.length} · ${d.medications.started.length}`}
            hint="recorded · prescribed" />
        </>}
      />

      <SectionCard icon={<FlaskConical aria-hidden size={14} className="text-ink-3" />} title="Tests and vitals at this visit" meta={`${tests}`}>
        {d.tests.length ? (
          <div className="grid gap-x-8 gap-y-4 md:grid-cols-2">
            {d.tests.map((p) => (
              <section key={p.panel} aria-label={p.display}>
                <h3 className="label mb-1">{p.display}</h3>
                <ul className="-mx-2 divide-y divide-line">
                  {p.items.map((t) => (
                    <li key={t.measure}>
                      <Link href={href.test(t.measure)} className="group flex items-center justify-between gap-3 rounded-control px-2 py-2 hover:bg-surface-2">
                        <span className="truncate text-sm text-ink">{t.display}</span>
                        <span className="flex shrink-0 items-center gap-2">
                          <span className="text-sm font-semibold tabular-nums text-ink">
                            {resultValue(t, t)}
                            {!t.text && t.unit && <span className="ml-1 text-xs font-normal text-ink-3">{t.unit}</span>}
                          </span>
                          <FlagChip flag={t.flag} />
                          <ChevronRight aria-hidden size={14} className="text-ink-3" />
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        ) : (
          <Empty>No tests or vitals were recorded at this visit.</Empty>
        )}
      </SectionCard>

      <div className="grid grid-cols-12 gap-5">
        <SectionCard className="col-span-12 lg:col-span-6" icon={<Stethoscope aria-hidden size={14} className="text-ink-3" />}
          title="Diagnoses" meta={`${d.diagnoses.recorded.length} recorded · ${d.diagnoses.resolved.length} resolved`}>
          <Group label="Recorded at this visit" items={d.diagnoses.recorded.map((c) => <ConditionRow key={c.concept_id} c={c} href={href.condition(c.concept_id)} />)} />
          <Group label="Resolved at this visit" items={d.diagnoses.resolved.map((c) => <ConditionRow key={c.concept_id} c={c} href={href.condition(c.concept_id)} />)} />
        </SectionCard>
        <SectionCard className="col-span-12 lg:col-span-6" icon={<Pill aria-hidden size={14} className="text-ink-3" />}
          title="Medications" meta={`${d.medications.started.length} started · ${d.medications.stopped.length} stopped`}>
          <Group label="Prescribed at this visit" items={d.medications.started.map((m) => <MedicationRow key={m.rxcui} m={m} href={href.medication(m.rxcui)} />)} />
          <Group label="Stopped at this visit" items={d.medications.stopped.map((m) => <MedicationRow key={m.rxcui} m={m} href={href.medication(m.rxcui)} />)} />
        </SectionCard>
      </div>
    </div>
  );
}

function Group({ label, items }: { label: string; items: React.ReactNode[] }) {
  return (
    <div className="mt-1 first:mt-0 [&+&]:mt-4">
      <h3 className="label mb-1">{label}</h3>
      {items.length ? <RowList>{items}</RowList> : <p className="py-1 text-sm text-ink-3">None.</p>}
    </div>
  );
}

function StepLinks({ previous, next, href }: { previous: VisitSummary | null; next: VisitSummary | null; href: (id: string) => string }) {
  const step = (v: VisitSummary | null, dir: "prev" | "next") => {
    const Icon = dir === "prev" ? ChevronLeft : ChevronRight;
    const label = dir === "prev" ? "Earlier visit" : "Later visit";
    const cls = "inline-flex items-center gap-1 rounded-control border border-line bg-surface px-3 py-1.5 text-xs font-medium shadow-card";
    if (!v) return <span className={cn(cls, "cursor-default text-ink-3 opacity-60")} aria-hidden>{dir === "prev" && <Icon size={14} />}{label}{dir === "next" && <Icon size={14} />}</span>;
    return (
      <Link href={href(v.encounter_id)} title={`${v.type ?? visitClass(v.class)}, ${fmtDay(v.start)}`} className={cn(cls, "text-ink-2 hover:text-ink")}>
        {dir === "prev" && <Icon aria-hidden size={14} />}{label}{dir === "next" && <Icon aria-hidden size={14} />}
      </Link>
    );
  };
  return <div className="flex gap-2">{step(previous, "prev")}{step(next, "next")}</div>;
}
