"use client";

import { ChevronDown, ChevronRight, ChevronsDownUp, ChevronsUpDown } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useId, useState, type ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { setManyOpen, setOpen, useAllOpen, useOpen } from "@/lib/record/open-sections";

const EASE = [0.2, 0.8, 0.2, 1] as const;

function Reveal({ open, id, children }: { open: boolean; id: string; children: ReactNode }) {
  return (
    <AnimatePresence initial={false}>
      {open && (
        <motion.div id={id} key="body" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.28, ease: EASE }} className="overflow-hidden">
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** A record section that opens and closes. Closed, it shows its title, count and a one-line
 *  `preview`; open, its full content and `controls` (filters). The viewer's choice is remembered. */
export function CollapsibleSection({ id, icon, title, meta, preview, action, controls, defaultOpen = false, empty = false, children, className }: {
  id: string;
  icon: ReactNode;
  title: string;
  meta?: ReactNode;
  /** shown while closed: what's inside at a glance */
  preview?: ReactNode;
  action?: { href: string; label: string };
  /** shown while open, beside the title (filters) */
  controls?: ReactNode;
  defaultOpen?: boolean;
  /** nothing recorded: the bar shows `preview` and doesn't open (no "View all" either) */
  empty?: boolean;
  children?: ReactNode;
  className?: string;
}) {
  const stored = useOpen(id, defaultOpen);
  const open = stored && !empty;
  const bodyId = useId();
  if (empty) {
    return (
      <Card id={id} aria-labelledby={`${id}-title`} className={cn("scroll-mt-48 px-5 py-4", className)}>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span aria-hidden className="w-[15px] shrink-0" />
          {icon}
          <h2 id={`${id}-title`} className="label shrink-0">{title}</h2>
          {preview && <span className="text-xs text-ink-3">· {preview}</span>}
        </div>
      </Card>
    );
  }
  return (
    <Card id={id} aria-labelledby={`${id}-title`} className={cn("scroll-mt-48 p-0", className)}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-5 pt-4" style={{ paddingBottom: open ? 0 : undefined }}>
        <button type="button" onClick={() => setOpen(id, !open)} aria-expanded={open} aria-controls={bodyId}
          className="group -mx-2 flex min-w-0 flex-1 items-center gap-2 rounded-control px-2 py-1 text-left hover:bg-surface-2">
          <ChevronRight aria-hidden size={15} className={cn("shrink-0 text-ink-3 transition-transform duration-200", open && "rotate-90")} />
          {icon}
          <h2 id={`${id}-title`} className="label shrink-0">{title}</h2>
          {meta && <span className="min-w-0 truncate text-xs text-ink-3">· {meta}</span>}
          <span className="ml-auto hidden shrink-0 text-[11px] text-ink-3 group-hover:inline">{open ? "Hide" : "Show"}</span>
        </button>
        {open && controls && <div className="order-last w-full sm:order-none sm:w-auto">{controls}</div>}
        {action && (
          <Link href={action.href} className="inline-flex shrink-0 items-center gap-0.5 whitespace-nowrap rounded-md px-1.5 py-1 text-xs font-medium text-primary hover:bg-primary-soft">
            {action.label} <ChevronRight aria-hidden size={13} />
          </Link>
        )}
      </div>
      {!open && preview && <div className="px-5 pb-4 pl-[46px] pt-1.5">{preview}</div>}
      {!open && !preview && <div className="pb-3" />}
      <Reveal open={open} id={bodyId}>
        <div className="px-5 pb-5 pt-3">{children}</div>
      </Reveal>
    </Card>
  );
}

/** A group inside a section (a test panel, a year of visits) that opens and closes. */
export function CollapsibleGroup({ id, title, meta, preview, defaultOpen = false, children }: {
  id: string;
  title: string;
  meta?: ReactNode;
  preview?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const open = useOpen(id, defaultOpen);
  const bodyId = useId();
  return (
    <section aria-label={title} className="border-t border-line first:border-t-0">
      <button type="button" onClick={() => setOpen(id, !open)} aria-expanded={open} aria-controls={bodyId}
        className="-mx-2 flex w-[calc(100%+1rem)] flex-wrap items-center gap-x-2 gap-y-1 rounded-control px-2 py-2.5 text-left hover:bg-surface-2">
        <ChevronDown aria-hidden size={14} className={cn("shrink-0 text-ink-3 transition-transform duration-200", !open && "-rotate-90")} />
        <h3 className="text-sm font-medium text-ink">{title}</h3>
        {meta && <span className="text-xs text-ink-3">{meta}</span>}
        {!open && preview && <span className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-1">{preview}</span>}
      </button>
      <Reveal open={open} id={bodyId}>
        <div className="pb-2">{children}</div>
      </Reveal>
    </section>
  );
}

/** Jump links to the sections (opening the one picked), and expand / collapse all. */
export function SectionNav({ sections }: { sections: { id: string; label: string; defaultOpen?: boolean }[] }) {
  const ids = sections.map((s) => ({ id: s.id, fallback: s.defaultOpen ?? false }));
  const allOpen = useAllOpen(ids);
  const go = (id: string) => {
    setOpen(id, true);
    window.history.replaceState(null, "", `#${id}`);
    // after the section starts to open, so the scroll lands on its header
    const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" }));
  };
  return (
    <nav aria-label="Record sections"
      className="z-10 -mx-1 flex items-center gap-1.5 overflow-x-auto bg-canvas/85 px-1 py-1 backdrop-blur [scrollbar-width:none] lg:sticky lg:top-[133px]">
      {sections.map((s) => (
        <button key={s.id} type="button" onClick={() => go(s.id)}
          className="whitespace-nowrap rounded-full border border-line bg-surface px-3 py-1 text-xs font-medium text-ink-2 shadow-card transition-colors hover:border-line-strong hover:text-ink">
          {s.label}
        </button>
      ))}
      <button type="button" onClick={() => setManyOpen(ids.map((x) => x.id), !allOpen)}
        className="ml-auto inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium text-ink-3 hover:bg-surface-2 hover:text-ink">
        {allOpen ? <ChevronsDownUp aria-hidden size={13} /> : <ChevronsUpDown aria-hidden size={13} />}
        {allOpen ? "Collapse all" : "Expand all"}
      </button>
    </nav>
  );
}

/** Preview chips: small links to entries, with "+N more". */
export function PreviewChips({ items, more, empty }: {
  items: { key: string; href: string; label: ReactNode; tone?: "warn" | "ok" }[];
  more?: number;
  empty?: string;
}) {
  if (!items.length) return <span className="text-xs text-ink-3">{empty}</span>;
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {items.map((i) => (
        <Link key={i.key} href={i.href}
          className={cn("inline-flex max-w-full items-center gap-1 truncate rounded-full border px-2.5 py-0.5 text-xs transition-colors",
            i.tone === "warn" ? "border-status-warn/25 bg-[color-mix(in_srgb,var(--status-warn)_8%,white)] text-ink hover:border-status-warn/50"
              : "border-line bg-surface-2 text-ink-2 hover:border-line-strong hover:text-ink")}>
          {i.label}
        </Link>
      ))}
      {more != null && more > 0 && <span className="text-xs text-ink-3">+{more} more</span>}
    </span>
  );
}

/** The first `limit` of a long list, then "Show all N" (and back). For tables of every
 *  result, episode or prescription: the newest stay in view, the rest on request. */
export function ShowMore({ items, limit = 10, noun = "rows" }: { items: ReactNode[]; limit?: number; noun?: string }) {
  const [all, setAll] = useState(false);
  const shown = all ? items : items.slice(0, limit);
  return (
    <>
      {shown}
      {items.length > limit && (
        <button type="button" onClick={() => setAll((a) => !a)} aria-expanded={all}
          className="flex w-full items-center justify-center gap-1 px-2 py-2.5 text-xs font-medium text-ink-3 hover:bg-surface-2 hover:text-ink">
          <ChevronDown aria-hidden size={13} className={cn("transition-transform", all && "rotate-180")} />
          {all ? `Show the latest ${limit}` : `Show all ${items.length} ${noun}`}
        </button>
      )}
    </>
  );
}
