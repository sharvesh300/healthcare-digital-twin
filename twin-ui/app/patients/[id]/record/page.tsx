import { FlaskConical, Info, Pill, Stethoscope } from "lucide-react";
import type { Metadata } from "next";

import { Card, CardHeader } from "@/components/ui/card";
import { api } from "@/lib/api/server";
import type { TwinRecord } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { fmtDate, fmtNumber, titleCase } from "@/lib/twin/format";

export const metadata: Metadata = { title: "Record" };

const LABS: { key: string; label: string; unit: string; digits?: number; flag?: string }[] = [
  { key: "hba1c", label: "HbA1c", unit: "%", digits: 1 },
  { key: "fasting_glucose", label: "Fasting glucose", unit: "mg/dL" },
  { key: "bmi", label: "BMI", unit: "kg/m²", digits: 1, flag: "bmi_is_synthetic" },
  { key: "sbp", label: "Blood pressure", unit: "mmHg" },
  { key: "ldl", label: "LDL", unit: "mg/dL", flag: "ldl_is_synthetic" },
  { key: "hdl", label: "HDL", unit: "mg/dL" },
  { key: "triglycerides", label: "Triglycerides", unit: "mg/dL" },
  { key: "egfr", label: "eGFR", unit: "mL/min/1.73m²", flag: "egfr_is_synthetic" },
  { key: "homa_ir", label: "HOMA-IR", unit: "", digits: 1, flag: "homa_ir_is_synthetic" },
  { key: "creatinine", label: "Creatinine", unit: "mg/dL", digits: 2 },
];

// ref.condition_group display names (seeds/reference/condition_group.csv)
const CONDITION_LABEL: Record<string, string> = {
  t2d: "Type 2 diabetes",
  prediabetes: "Prediabetes",
  hypertension: "Hypertension",
  dyslipidemia: "Dyslipidaemia",
  obesity: "Obesity",
  metabolic_syndrome: "Metabolic syndrome",
  ckd: "Chronic kidney disease",
  retinopathy: "Diabetic retinopathy",
  neuropathy: "Diabetic neuropathy",
  cardiovascular: "Cardiovascular disease",
  masld: "Fatty liver disease (MASLD)",
  hypoglycemia: "Hypoglycaemia",
  anemia: "Anaemia",
  sleep_apnea: "Sleep apnoea",
  copd: "COPD",
};

function Synthetic() {
  return <span className="hatch rounded-chip border border-line px-1.5 py-0.5 text-[10px] font-medium text-ink-2">Synthetic</span>;
}

export default async function RecordPage({ params }: PageProps<"/patients/[id]/record">) {
  const { id } = await params;
  const r: TwinRecord = await api.record(id);
  const b = r.baseline ?? {};
  const synthetic = new Set((b.synthetic_analytes as string[] | undefined) ?? []);
  return (
    <div className="grid grid-cols-12 gap-5">
      <Card className="col-span-12 flex items-start gap-3 p-5">
        <Info size={16} className="mt-0.5 shrink-0 text-primary" />
        <p className="text-sm leading-relaxed text-ink-2">{r.provenance.note}</p>
      </Card>

      <Card className="col-span-12 p-5">
        <CardHeader icon={<FlaskConical size={14} className="text-ink-3" />} title="Baseline"
          meta={b.effective_at ? `as of ${fmtDate(String(b.effective_at))}` : undefined} />
        <dl className="mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-control border border-line bg-line sm:grid-cols-3 lg:grid-cols-5">
          {LABS.map(({ key, label, unit, digits, flag }) => {
            const v = b[key];
            const isSyn = (flag && b[flag] === true) || synthetic.has(key);
            const value = key === "sbp" && b.sbp != null ? `${fmtNumber(b.sbp as number)}/${fmtNumber(b.dbp as number)}` : fmtNumber(v as number, digits ?? 0);
            return (
              <div key={key} className={cn("bg-surface p-4", isSyn && "hatch")}>
                <dt className="label flex items-center justify-between gap-2">{label}{isSyn && <Synthetic />}</dt>
                <dd className="mt-2 text-xl font-semibold tabular-nums text-ink">
                  {v == null ? <span className="text-ink-3">—</span> : value}
                  {v != null && unit && <span className="ml-1 text-xs font-normal text-ink-3">{unit}</span>}
                </dd>
              </div>
            );
          })}
        </dl>
      </Card>

      <Card className="col-span-12 p-5 lg:col-span-5">
        <CardHeader icon={<Stethoscope size={14} className="text-ink-3" />} title="Conditions" meta={`${r.conditions.length} groups`} />
        <ul className="mt-3 divide-y divide-line">
          {r.conditions.map((c) => (
            <li key={c.condition_group} className="flex items-start justify-between gap-3 py-3">
              <div className="min-w-0">
                <p className="text-sm font-medium text-ink">{CONDITION_LABEL[c.condition_group] ?? titleCase(c.condition_group)}</p>
                <p className="mt-0.5 truncate text-xs text-ink-3" title={c.conditions.join(", ")}>{c.conditions.join(", ")}</p>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                {c.all_synthetic && <Synthetic />}
                <span className={cn("rounded-chip px-1.5 py-0.5 text-[11px] font-medium", c.active ? "bg-primary-soft text-primary-strong" : "bg-surface-2 text-ink-3")}>
                  {c.active ? "Active" : "Resolved"}
                </span>
              </div>
            </li>
          ))}
          {!r.conditions.length && <li className="py-6 text-center text-sm text-ink-3">No conditions recorded</li>}
        </ul>
      </Card>

      <Card className="col-span-12 p-5 lg:col-span-7">
        <CardHeader icon={<Pill size={14} className="text-ink-3" />} title="Medications" meta={`${r.medications.filter((m) => m.active).length} active`} />
        <ul className="mt-3 divide-y divide-line">
          {r.medications.slice(0, 14).map((m, i) => (
            <li key={`${m.medication}-${i}`} className="flex items-center justify-between gap-3 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium capitalize text-ink">{m.medication}</p>
                <p className="mt-0.5 text-xs text-ink-3">
                  {m.drug_class ? titleCase(m.drug_class) : "Unclassified"}
                  {m.dose_value != null && ` · ${fmtNumber(m.dose_value, 0)} ${m.dose_unit ?? ""}`} · since {fmtDate(m.started_at)}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                {m.glucose_lowering && <span className="rounded-chip bg-[color-mix(in_srgb,var(--vital-glucose)_11%,white)] px-1.5 py-0.5 text-[11px] font-medium text-ink">Glucose-lowering</span>}
                {m.is_synthetic && <Synthetic />}
                {!m.active && <span className="rounded-chip bg-surface-2 px-1.5 py-0.5 text-[11px] text-ink-3">Stopped</span>}
              </div>
            </li>
          ))}
          {!r.medications.length && <li className="py-6 text-center text-sm text-ink-3">No medications recorded</li>}
        </ul>
      </Card>
    </div>
  );
}
