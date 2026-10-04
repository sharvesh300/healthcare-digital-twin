"use client";

import { Activity, Droplet, HeartPulse, Wind } from "lucide-react";

import { ChartCard } from "@/components/charts/time-series-chart";
import type { Timeline } from "@/lib/api/types";
import type { Point } from "@/lib/twin/store";
import { GLUCOSE_LIMITS, vital } from "@/lib/tokens";

const series = (t: Timeline, key: string): Point[] =>
  t.series
    .map((r) => ({ t: Date.parse(String(r.time)), v: r[key] == null ? NaN : Number(r[key]) }))
    .filter((p) => Number.isFinite(p.v));

/** The recorded 5-minute series (fused CGM + wearables), last 24 h of the recording. */
export function HistoryCharts({ timeline }: { timeline: Timeline }) {
  const glucose = series(timeline, "glucose_mg_dl");
  const hr = series(timeline, "heart_rate");
  const mets = series(timeline, "met_minutes").map((p) => ({ ...p, v: p.v / 5 }));
  const spo2 = series(timeline, "spo2");
  return (
    <div className="grid grid-cols-12 gap-5">
      <div className="col-span-12">
        <ChartCard title="Glucose" icon={<Droplet size={14} strokeWidth={2.4} style={{ color: vital.glucose }} />}
          meta="fused CGM · 5-min" live={false} defaultHours={24} height={240}
          spec={{ points: glucose, color: vital.glucose, unit: "mg/dL", target: [GLUCOSE_LIMITS.low, GLUCOSE_LIMITS.high],
            thresholds: [GLUCOSE_LIMITS.veryLow, GLUCOSE_LIMITS.low, GLUCOSE_LIMITS.high, GLUCOSE_LIMITS.veryHigh], floor: [60, 200], glucose: true }} />
      </div>
      <div className="col-span-12 lg:col-span-6">
        <ChartCard title="Heart rate" icon={<HeartPulse size={14} strokeWidth={2.4} style={{ color: vital.heart }} />}
          meta="5-min mean" live={false} defaultHours={24} height={180}
          spec={{ points: hr, color: vital.heart, unit: "bpm", floor: [55, 100] }} />
      </div>
      <div className="col-span-12 lg:col-span-6">
        <ChartCard title="Activity" icon={<Activity size={14} strokeWidth={2.4} style={{ color: vital.activity }} />}
          meta="mean METs" live={false} defaultHours={24} height={180}
          spec={{ points: mets, color: vital.activity, unit: "MET", digits: 1, floor: [1, 3] }} />
      </div>
      {spo2.length > 1 && (
        <div className="col-span-12 lg:col-span-6">
          <ChartCard title="SpO₂" icon={<Wind size={14} strokeWidth={2.4} style={{ color: vital.oxygen }} />}
            meta="synthetic · overnight" live={false} defaultHours={24} height={160}
            spec={{ points: spo2, color: vital.oxygen, unit: "%", floor: [90, 100], gapMin: 30 }} />
        </div>
      )}
    </div>
  );
}
