"use client";

import { Activity, EyeOff, Menu, Search, Users, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { BandChip } from "@/components/vitals/chips";
import type { PatientListItem } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { fmtNumber } from "@/lib/twin/format";
import { cohortName, initials, patientName } from "@/lib/twin/patient-name";

import { PrefsProvider, usePrefs } from "./prefs";

const REFRESH_MS = 15_000;

/** Keeps the cohort list fresh (live dots, latest glucose) without one socket per patient. */
export function useLivePatients(initial: PatientListItem[]) {
  const [patients, setPatients] = useState(initial);
  useEffect(() => {
    const id = setInterval(async () => {
      try {
        const res = await fetch("/api/twin/patients?tag=composite-patient", { cache: "no-store" });
        if (res.ok) setPatients(await res.json());
      } catch {}
    }, REFRESH_MS);
    return () => clearInterval(id);
  }, []);
  return patients;
}

export function AppShell({ patients: initial, children }: { patients: PatientListItem[]; children: ReactNode }) {
  return (
    <PrefsProvider>
      <Shell initial={initial}>{children}</Shell>
    </PrefsProvider>
  );
}

function Shell({ initial, children }: { initial: PatientListItem[]; children: ReactNode }) {
  const patients = useLivePatients(initial);
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  // eslint-disable-next-line react-hooks/set-state-in-effect -- close the drawer on navigation
  useEffect(() => setOpen(false), [pathname]);

  return (
    <div className="min-h-dvh lg:pl-[264px]">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[264px] border-r border-line bg-surface-2 lg:block">
        <Sidebar patients={patients} />
      </aside>

      {/* mobile / tablet top bar + drawer */}
      <div className="sticky top-0 z-30 flex items-center justify-between border-b border-line bg-surface/90 px-4 py-3 backdrop-blur lg:hidden">
        <Brand />
        <button onClick={() => setOpen(true)} aria-label="Open patients" className="grid size-9 place-items-center rounded-control border border-line bg-surface text-ink-2">
          <Menu size={18} />
        </button>
      </div>
      <AnimatePresence>
        {open && (
          <>
            <motion.div className="fixed inset-0 z-40 bg-ink/20 backdrop-blur-[2px] lg:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setOpen(false)} />
            <motion.aside
              className="fixed inset-y-0 left-0 z-50 w-[288px] max-w-[85vw] border-r border-line bg-surface-2 shadow-pop lg:hidden"
              initial={{ x: "-100%" }}
              animate={{ x: 0 }}
              exit={{ x: "-100%" }}
              transition={{ type: "spring", stiffness: 380, damping: 36 }}
            >
              <button onClick={() => setOpen(false)} aria-label="Close patients" className="absolute right-3 top-4 grid size-8 place-items-center rounded-control text-ink-3 hover:text-ink">
                <X size={18} />
              </button>
              <Sidebar patients={patients} />
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      <main className="mx-auto w-full max-w-[1480px] px-4 pb-16 sm:px-6 lg:px-8">{children}</main>
    </div>
  );
}

function Brand() {
  return (
    <Link href="/patients" className="group inline-flex items-center gap-2.5">
      <span className="relative grid size-8 place-items-center rounded-[10px] bg-primary text-white shadow-card">
        <Activity size={17} strokeWidth={2.4} />
      </span>
      <span className="leading-tight">
        <span className="block text-[15px] font-semibold tracking-tight text-ink">Twin</span>
        <span className="block text-[11px] text-ink-3">Diabetes digital twin</span>
      </span>
    </Link>
  );
}

function Sidebar({ patients }: { patients: PatientListItem[] }) {
  const pathname = usePathname();
  const { anonymous, setAnonymous } = usePrefs();
  const [query, setQuery] = useState("");
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q
      ? patients.filter((p) => `${patientName(p, false)} ${p.source_subject_id} ${cohortName(p.source)}`.toLowerCase().includes(q))
      : patients;
    return [...list].sort((a, b) => Number(!!b.live?.streaming) - Number(!!a.live?.streaming));
  }, [patients, query]);
  const streaming = patients.filter((p) => p.live?.streaming).length;

  return (
    <div className="flex h-full flex-col">
      <div className="px-5 pb-4 pt-5">
        <Brand />
      </div>
      <div className="px-4">
        <label className="relative block">
          <Search aria-hidden size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search patients"
            className="h-9 w-full rounded-control border border-line bg-surface pl-9 pr-3 text-sm text-ink placeholder:text-ink-3 focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/15"
          />
        </label>
      </div>

      <div className="mt-5 flex items-center justify-between px-5">
        <Link href="/patients" className={cn("label inline-flex items-center gap-1.5 hover:text-ink-2", pathname === "/patients" && "text-primary")}>
          <Users size={12} /> Patients
        </Link>
        <span className="text-[11px] tabular-nums text-ink-3">
          {streaming > 0 && <span className="text-primary">{streaming} live · </span>}
          {patients.length}
        </span>
      </div>

      <nav aria-label="Patients" className="mt-2 flex-1 overflow-y-auto px-2.5 pb-4">
        <ul className="space-y-0.5">
          {shown.map((p) => {
            const href = `/patients/${p.patient_id}`;
            const active = pathname.startsWith(href);
            const name = patientName(p, anonymous);
            const g = p.live?.glucose;
            return (
              <li key={p.patient_id}>
                <Link
                  href={href}
                  className={cn(
                    "relative flex items-center gap-3 rounded-control px-2.5 py-2 transition-colors",
                    active ? "text-ink" : "text-ink-2 hover:bg-surface/70",
                  )}
                >
                  {active && (
                    <motion.span layoutId="sidebar-active" className="absolute inset-0 rounded-control border border-line bg-surface shadow-card"
                      transition={{ type: "spring", stiffness: 420, damping: 36 }} />
                  )}
                  <span className="relative grid size-8 shrink-0 place-items-center rounded-full bg-primary-soft text-[11px] font-semibold text-primary-strong">
                    {initials(name)}
                    {p.live?.streaming && (
                      <span className="absolute -right-0.5 -top-0.5 grid size-3 place-items-center rounded-full bg-surface">
                        <span className="size-2 rounded-full bg-primary" />
                      </span>
                    )}
                  </span>
                  <span className="relative min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-medium">{name}</span>
                    <span className="block truncate text-[11px] text-ink-3">
                      {anonymous ? `${p.sex === "female" ? "F" : "M"} · ${p.age}` : `${cohortName(p.source)} ${p.source_subject_id}`}
                    </span>
                  </span>
                  {g?.value != null && g.status && (
                    <span className="relative flex flex-col items-end gap-0.5">
                      <span className="text-[13px] font-semibold tabular-nums text-ink">{fmtNumber(g.value)}</span>
                      <BandChip status={g.status} size="sm" className="!px-1 !py-0 text-[10px]" />
                    </span>
                  )}
                </Link>
              </li>
            );
          })}
          {shown.length === 0 && <li className="px-3 py-6 text-center text-xs text-ink-3">No patients match “{query}”</li>}
        </ul>
      </nav>

      <div className="border-t border-line px-4 py-3">
        <label className="flex cursor-pointer items-center justify-between gap-3 rounded-control px-1 py-1 text-xs text-ink-2">
          <span className="inline-flex items-center gap-2">
            <EyeOff size={14} className="text-ink-3" /> Anonymise names
          </span>
          <button
            role="switch"
            aria-checked={anonymous}
            onClick={() => setAnonymous(!anonymous)}
            className={cn("relative h-5 w-9 rounded-full transition-colors duration-200", anonymous ? "bg-primary" : "bg-line-strong")}
          >
            <motion.span className="absolute top-0.5 size-4 rounded-full bg-white shadow" animate={{ left: anonymous ? 18 : 2 }} transition={{ type: "spring", stiffness: 500, damping: 34 }} />
          </button>
        </label>
        <p className="mt-2 px-1 text-[11px] leading-relaxed text-ink-3">
          Composite twins: real CGM and wearable data, synthetic EHR history.
        </p>
      </div>
    </div>
  );
}
