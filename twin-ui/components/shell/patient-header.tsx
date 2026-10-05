"use client";

import { FileText, Radio, Sparkles } from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import type { PatientInfo } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { cohortName, initials, patientName } from "@/lib/twin/patient-name";

import { usePrefs } from "./prefs";

const TAG_LABEL: Record<string, string> = {
  "composite-patient": "Composite twin",
  "synthetic-sensors": "Synthetic sensors",
  "gmi-inconsistent": "HbA1c ≠ GMI",
  "gmi-warn": "HbA1c vs GMI gap",
  "undiagnosed-diabetes": "Undiagnosed diabetes",
};

export function PatientHeader({ patient }: { patient: PatientInfo }) {
  const pathname = usePathname();
  const { anonymous } = usePrefs();
  const base = `/patients/${patient.patient_id}`;
  const name = patientName(patient, anonymous);
  const tabs = [
    { href: base, label: "Live", icon: Radio },
    { href: `${base}/record`, label: "Record", icon: FileText },
    { href: `${base}/predict`, label: "Predict", icon: Sparkles, soon: true },
  ];

  return (
    <header className="z-20 -mx-4 lg:sticky border-b border-line bg-canvas/85 px-4 pt-6 backdrop-blur-md sm:-mx-6 sm:px-6 lg:top-0 lg:-mx-8 lg:px-8">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <span className="grid size-11 shrink-0 place-items-center rounded-full bg-primary-soft text-sm font-semibold text-primary-strong">
          {initials(name)}
        </span>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-[22px] font-semibold leading-7 tracking-tight text-ink">{name}</h1>
          <p className="mt-0.5 text-sm text-ink-3">
            {patient.sex === "female" ? "Female" : "Male"} · {patient.age} years
            {!anonymous && <> · {cohortName(patient.source)} {patient.source_subject_id}</>}
          </p>
        </div>
        <ul className="flex w-full flex-wrap gap-1.5 sm:w-auto">
          {patient.tags.map((t) => (
            <li key={t} className={cn("rounded-full border px-2.5 py-1 text-[11px] font-medium",
              t === "synthetic-sensors" ? "hatch border-line bg-surface text-ink-2" : "border-line bg-surface text-ink-2")}>
              {TAG_LABEL[t] ?? t}
            </li>
          ))}
        </ul>
      </div>

      <nav aria-label="Twin views" className="-mb-px mt-5 flex gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {tabs.map(({ href, label, icon: Icon, soon }) => {
          const active = href === base ? pathname === base : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "relative inline-flex items-center gap-2 whitespace-nowrap px-3 pb-3 pt-1 text-sm font-medium transition-colors",
                active ? "text-ink" : "text-ink-3 hover:text-ink-2",
              )}
            >
              <Icon size={15} className={active ? "text-primary" : undefined} />
              {label}
              {soon && <span className="rounded-full bg-surface-2 px-1.5 py-0.5 text-[10px] font-medium text-ink-3">soon</span>}
              {active && (
                <motion.span layoutId="patient-tab" className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-primary"
                  transition={{ type: "spring", stiffness: 480, damping: 38 }} />
              )}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}
