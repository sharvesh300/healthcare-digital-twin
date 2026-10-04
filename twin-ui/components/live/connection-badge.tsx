"use client";

import { RefreshCw, WifiOff } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";

import { cn } from "@/lib/cn";
import type { ConnStatus } from "@/lib/twin/store";

const LABEL: Record<ConnStatus, string> = {
  connecting: "Connecting",
  live: "Live",
  reconnecting: "Reconnecting…",
  offline: "Offline",
  not_found: "Unknown patient",
};

/** Socket status, kept apart from `streaming` (are devices sending?). */
export function ConnectionBadge({ status, streaming }: { status: ConnStatus; streaming: boolean }) {
  const live = status === "live";
  const label = live && !streaming ? "Connected · not streaming" : LABEL[status];
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.span
        key={label}
        initial={{ opacity: 0, y: -3 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: 3 }}
        transition={{ duration: 0.18 }}
        role="status"
        className={cn(
          "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium",
          live && streaming && "border-primary/20 bg-primary-soft text-primary-strong",
          live && !streaming && "border-line bg-surface text-ink-2",
          (status === "reconnecting" || status === "connecting") && "border-status-warn/25 bg-[color-mix(in_srgb,var(--status-warn)_9%,white)] text-status-warn",
          (status === "offline" || status === "not_found") && "border-line bg-surface-2 text-ink-2",
        )}
      >
        {live ? (
          <span className="relative grid size-2 place-items-center">
            {streaming && <span className="live-ping absolute inset-0 rounded-full bg-primary" />}
            <span className={cn("size-2 rounded-full", streaming ? "bg-primary" : "bg-ink-3")} />
          </span>
        ) : status === "offline" ? (
          <WifiOff size={13} />
        ) : (
          <RefreshCw size={13} className="animate-spin [animation-duration:1.6s]" />
        )}
        {label}
      </motion.span>
    </AnimatePresence>
  );
}
