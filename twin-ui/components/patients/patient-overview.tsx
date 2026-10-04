"use client";

import { ArrowUpRight, Droplet, Radio, Search, Users } from "lucide-react";
import { motion, type Variants } from "motion/react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { useLivePatients } from "@/components/shell/app-shell";
import { usePrefs } from "@/components/shell/prefs";
import { BandChip } from "@/components/vitals/chips";
import { TrendArrow } from "@/components/vitals/trend-arrow";
import type { PatientListItem } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { fmtDate, fmtNumber } from "@/lib/twin/format";
import { cohortName, initials, patientName } from "@/lib/twin/patient-name";

const container: Variants = { hidden: {}, show: { transition: { staggerChildren: 0.035 } } };
const row: Variants = { hidden: { opacity: 0, y: 8 }, show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.2, 0.8, 0.2, 1] } } };

export function PatientOverview({ initial }: { initial: PatientListItem[] }) {
  const { anonymous } = usePrefs();
  const [query, setQuery] = useState("");
  const [cohort, setCohort] = useState<string>("all");
  const [liveOnly, setLiveOnly] = useState(false);
  const patients = useLivePatients(initial);

  const cohorts = useMemo(() => [...new Set(patients.map((p) => p.source))], [patients]);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return patients.filter(
      (p) =>
        (cohort === "all" || p.source === cohort) &&
        (!liveOnly || p.live?.streaming) &&
        (!q || `${patientName(p, false)} ${p.source_subject_id}`.toLowerCase().includes(q)),
    );
  }, [patients, query, cohort, liveOnly]);

  const streaming = patients.filter((p) => p.live?.streaming);
  const inRange = streaming.filter((p) => p.live?.glucose.status === "in_range").length;

  return (
    <div className="pt-8">
      <motion.header initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
        <h1 className="text-[26px] font-semibold tracking-tight text-ink">Patients</h1>
        <p className="mt-1 max-w-2xl text-sm leading-relaxed text-ink-3">
          Composite digital twins: each pairs a real participant&apos;s CGM and wearable recordings with a matched synthetic health record.
        </p>
      </motion.header>

      <motion.div variants={container} initial="hidden" animate="show" className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat icon={Users} label="Twins" value={patients.length} note={`${cohorts.length} cohorts`} />
        <Stat icon={Radio} label="Streaming now" value={streaming.length} note={streaming.length ? "devices sending" : "start the simulator"} accent />
        <Stat icon={Droplet} label="In range now" value={streaming.length ? inRange : null}
          note={streaming.length ? `of ${streaming.length} streaming` : "no live glucose yet"} />
      </motion.div>

      <div className="mt-8 flex flex-wrap items-center gap-3">
        <label className="relative min-w-[220px] flex-1 sm:max-w-xs">
          <Search aria-hidden size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by name or subject id"
            className="h-10 w-full rounded-control border border-line bg-surface pl-9 pr-3 text-sm text-ink shadow-card placeholder:text-ink-3 focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/15" />
        </label>
        <div role="radiogroup" aria-label="Cohort" className="flex rounded-control border border-line bg-surface-2 p-0.5">
          {["all", ...cohorts].map((c) => (
            <button key={c} role="radio" aria-checked={cohort === c} onClick={() => setCohort(c)}
              className={cn("relative rounded-[8px] px-3 py-1.5 text-xs font-medium transition-colors", cohort === c ? "text-ink" : "text-ink-3 hover:text-ink-2")}>
              {cohort === c && <motion.span layoutId="cohort-pill" className="absolute inset-0 rounded-[8px] bg-surface shadow-card" transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
              <span className="relative">{c === "all" ? "All cohorts" : cohortName(c)}</span>
            </button>
          ))}
        </div>
        <button role="switch" aria-checked={liveOnly} onClick={() => setLiveOnly(!liveOnly)}
          className={cn("inline-flex h-9 items-center gap-2 rounded-control border px-3 text-xs font-medium transition-colors",
            liveOnly ? "border-primary/25 bg-primary-soft text-primary-strong" : "border-line bg-surface text-ink-2 hover:text-ink")}>
          <Radio size={14} /> Streaming only
        </button>
      </div>

      <div className="mt-4 overflow-hidden rounded-card border border-line bg-surface shadow-card">
        <div className="hidden grid-cols-[minmax(0,2.2fr)_minmax(0,1.1fr)_minmax(0,1.4fr)_minmax(0,1.6fr)_40px] gap-4 border-b border-line bg-surface-2 px-5 py-2.5 md:grid">
          <span className="label">Patient</span>
          <span className="label">Cohort</span>
          <span className="label">Recording</span>
          <span className="label">Glucose now</span>
          <span />
        </div>
        <motion.ul variants={container} initial="hidden" animate="show" key={`${cohort}-${liveOnly}`}>
          {shown.map((p) => {
            const name = patientName(p, anonymous);
            const g = p.live?.glucose;
            return (
              <motion.li key={p.patient_id} variants={row} className="border-b border-line last:border-0">
                <Link href={`/patients/${p.patient_id}`}
                  className="group grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 px-5 py-3.5 transition-colors hover:bg-surface-2/60 md:grid-cols-[minmax(0,2.2fr)_minmax(0,1.1fr)_minmax(0,1.4fr)_minmax(0,1.6fr)_40px]">
                  <span className="flex min-w-0 items-center gap-3">
                    <span className="relative grid size-9 shrink-0 place-items-center rounded-full bg-primary-soft text-xs font-semibold text-primary-strong">
                      {initials(name)}
                      {p.live?.streaming && (
                        <span className="absolute -right-0.5 -top-0.5 grid size-3.5 place-items-center rounded-full bg-surface">
                          <span className="relative size-2 rounded-full bg-primary"><span className="live-ping absolute inset-0 rounded-full bg-primary" /></span>
                        </span>
                      )}
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium text-ink">{name}</span>
                      <span className="block truncate text-xs text-ink-3">{p.sex === "female" ? "Female" : "Male"} · {p.age}</span>
                    </span>
                  </span>
                  <span className="hidden text-sm text-ink-2 md:block">
                    {cohortName(p.source)} <span className="text-ink-3">{anonymous ? "" : p.source_subject_id}</span>
                  </span>
                  <span className="hidden text-sm tabular-nums text-ink-2 md:block">
                    {p.window_start ? `${fmtDate(p.window_start)} – ${fmtDate(p.window_end)}` : <span className="text-ink-3">no sensors</span>}
                  </span>
                  <span className="flex items-center gap-2.5">
                    {g?.value != null && g.status ? (
                      <>
                        <span className="text-sm font-semibold tabular-nums text-ink">{fmtNumber(g.value)}</span>
                        <TrendArrow trend={g.trend} size={14} className="text-ink-2" />
                        <BandChip status={g.status} size="sm" />
                      </>
                    ) : (
                      <span className="text-xs text-ink-3" title="The twin loads when you open the patient">—</span>
                    )}
                  </span>
                  <ArrowUpRight size={16} className="hidden justify-self-end text-ink-3 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-primary md:block" />
                </Link>
              </motion.li>
            );
          })}
        </motion.ul>
        {shown.length === 0 && (
          <div className="px-5 py-14 text-center">
            <p className="text-sm font-medium text-ink">{liveOnly ? "No patients are streaming" : "No patients match"}</p>
            <p className="mt-1 text-xs text-ink-3">
              {liveOnly ? (
                <>Start the simulator: <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono">scripts/stream.sh --from-now</code></>
              ) : "Try another name or cohort."}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ icon: Icon, label, value, note, accent }: {
  icon: typeof Users;
  label: string;
  value: number | null;
  note: string;
  accent?: boolean;
}) {
  return (
    <motion.div variants={row} className="rounded-card border border-line bg-surface p-5 shadow-card">
      <div className="flex items-center gap-2">
        <span className={cn("grid size-7 place-items-center rounded-lg", accent ? "bg-primary-soft text-primary" : "bg-surface-2 text-ink-2")}>
          <Icon size={15} />
        </span>
        <span className="label">{label}</span>
      </div>
      <div className="mt-3 text-metric font-semibold tabular-nums text-ink">{value ?? "—"}</div>
      <div className="mt-0.5 text-xs text-ink-3">{note}</div>
    </motion.div>
  );
}
