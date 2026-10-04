"use client";

import { RefreshCw, Unplug } from "lucide-react";

export default function PatientsError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="grid min-h-[70vh] place-items-center">
      <div className="max-w-md rounded-card border border-line bg-surface p-8 text-center shadow-card">
        <span className="mx-auto grid size-12 place-items-center rounded-full bg-surface-2 text-ink-2">
          <Unplug size={22} />
        </span>
        <h1 className="mt-4 text-lg font-semibold text-ink">The twin API isn&apos;t answering</h1>
        <p className="mt-2 text-sm leading-relaxed text-ink-3">
          {error.message.includes("reach") ? error.message : "Something went wrong loading this view."} Start it with{" "}
          <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-ink-2">uv run twin serve</code>, then retry.
        </p>
        <button onClick={reset} className="mt-6 inline-flex items-center gap-2 rounded-control bg-primary px-4 py-2 text-sm font-medium text-white shadow-card transition-colors hover:bg-primary-strong">
          <RefreshCw size={15} /> Try again
        </button>
      </div>
    </div>
  );
}
