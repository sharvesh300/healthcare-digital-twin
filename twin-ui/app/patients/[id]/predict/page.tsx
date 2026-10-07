import { Sparkles, Terminal } from "lucide-react";
import type { Metadata } from "next";

import { GlucoseForecastView } from "@/components/predict/glucose-forecast";
import { api, ApiError } from "@/lib/api/server";
import { param } from "@/lib/record/load";

export const metadata: Metadata = { title: "Predict" };

export default async function PredictPage({ params, searchParams }: PageProps<"/patients/[id]/predict">) {
  const { id } = await params;
  const at = param(await searchParams, "at");
  const data = await api.predictions.glucose(id, at).catch((e) => {
    // The API answered but its model can't run (not exported, failed its checks, ml extra missing).
    if (e instanceof ApiError && e.status === 503 && e.detail) return e.detail;
    throw e;
  });
  if (typeof data === "string") return <ModelMissing detail={data} />;
  return <GlucoseForecastView key={at ?? "latest"} data={data} latest={!at} />;
}

function ModelMissing({ detail }: { detail: string }) {
  return (
    <div className="hatch rounded-card border border-dashed border-line-strong bg-surface p-8">
      <span className="inline-flex items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-[11px] font-medium text-ink-2">
        <Sparkles aria-hidden size={12} /> Model estimate
      </span>
      <h2 className="mt-4 text-xl font-semibold tracking-tight text-ink">The glucose forecaster isn&apos;t available</h2>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-3">{detail}.</p>
      <p className="mt-4 inline-flex items-center gap-2 rounded-control bg-surface-2 px-3 py-2 font-mono text-xs text-ink-2">
        <Terminal aria-hidden size={13} /> uv sync --extra ml &amp;&amp; uv run twin train-glucose-forecaster
      </p>
    </div>
  );
}
