import type { Metadata } from "next";

import { LiveTwin } from "@/components/live/live-twin";
import { api } from "@/lib/api/server";
import type { Readings } from "@/lib/api/types";
import type { Point } from "@/lib/twin/store";

export const metadata: Metadata = { title: "Live twin" };

const toPoints = (r: Readings, metric: string): Point[] =>
  (r.series[metric] ?? []).map(([t, v]) => ({ t: Date.parse(t), v }));

export default async function LiveTwinPage({ params }: PageProps<"/patients/[id]">) {
  const { id } = await params;
  const { patient, state } = await api.patient(id);
  // Charts end at the twin's latest reading (a fast replay's device clock runs ahead of now).
  const anchor = [state.glucose.time, state.heart_rate.time].filter(Boolean).sort().at(-1) ?? null;
  const [transitions, readings] = await Promise.all([
    api.transitions(id, 40).catch(() => []),
    api.readings(id, ["glucose", "heart_rate"], anchor, 24).catch(() => null),
  ]);
  return (
    <LiveTwin
      patientId={id}
      recording={patient.window ?? null}
      init={{
        state,
        transitions,
        series: readings ? { glucose: toPoints(readings, "glucose"), heart_rate: toPoints(readings, "heart_rate") } : {},
      }}
    />
  );
}
