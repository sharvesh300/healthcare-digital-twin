import type { Metadata } from "next";

import { DailyCgm } from "@/components/history/daily-cgm";
import { HistoryCharts } from "@/components/history/history-charts";
import { api } from "@/lib/api/server";
import { fmtDateTime } from "@/lib/twin/format";

export const metadata: Metadata = { title: "History" };

export default async function HistoryPage({ params }: PageProps<"/patients/[id]/history">) {
  const { id } = await params;
  const [timeline, record] = await Promise.all([api.timeline(id), api.record(id)]);
  return (
    <div className="space-y-5">
      <p className="text-sm text-ink-3">
        The recorded twin: fused CGM and wearable series in 5-minute steps
        {timeline.start ? <> from {fmtDateTime(timeline.start)} to {fmtDateTime(timeline.end)}</> : null}. Live streamed readings are kept out of this view.
      </p>
      {timeline.series.length ? (
        <HistoryCharts timeline={timeline} />
      ) : (
        <div className="rounded-card border border-line bg-surface px-6 py-12 text-center text-sm text-ink-3 shadow-card">{timeline.note ?? "No recorded series for this patient."}</div>
      )}
      <DailyCgm daily={record.cgm.daily} />
    </div>
  );
}
