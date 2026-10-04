import { CalendarDays } from "lucide-react";

import { Card, CardHeader } from "@/components/ui/card";
import type { TwinRecord } from "@/lib/api/types";
import { fmtNumber } from "@/lib/twin/format";
import { band, type BandKey } from "@/lib/tokens";

const SEG: [BandKey, keyof TwinRecord["cgm"]["daily"][number]][] = [
  ["very_low", "pct_very_low"], ["low", "pct_low"], ["in_range", "pct_target"], ["high", "pct_high"], ["very_high", "pct_very_high"],
];

/** Daily CGM metrics from the fused stream: TIR bar, mean, CV, GMI, coverage. */
export function DailyCgm({ daily }: { daily: TwinRecord["cgm"]["daily"] }) {
  if (!daily.length) return null;
  return (
    <Card className="p-5">
      <CardHeader icon={<CalendarDays size={14} className="text-ink-3" />} title="Daily glucose" meta="fused CGM, consensus ranges" />
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="text-left">
              <th className="label pb-2 font-medium">Day</th>
              <th className="label w-[38%] pb-2 font-medium">Time in ranges</th>
              <th className="label pb-2 text-right font-medium">In range</th>
              <th className="label pb-2 text-right font-medium">Mean</th>
              <th className="label pb-2 text-right font-medium">CV</th>
              <th className="label pb-2 text-right font-medium">GMI</th>
              <th className="label pb-2 text-right font-medium">Coverage</th>
            </tr>
          </thead>
          <tbody>
            {daily.map((d) => (
              <tr key={d.day} className="border-t border-line">
                <td className="py-2.5 tabular-nums text-ink-2">{new Date(`${d.day}T12:00:00`).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}</td>
                <td className="py-2.5 pr-4">
                  <div className="flex h-2 gap-px overflow-hidden rounded-full bg-surface-2">
                    {SEG.map(([b, k]) => <div key={b} style={{ flexGrow: Number(d[k]) || 0, flexBasis: 0, background: band[b] }} />)}
                  </div>
                </td>
                <td className="py-2.5 text-right font-medium tabular-nums text-ink">{fmtNumber(d.pct_target)}%</td>
                <td className="py-2.5 text-right tabular-nums text-ink-2">{fmtNumber(d.mean_mg_dl)}<span className="ml-0.5 text-xs text-ink-3">mg/dL</span></td>
                <td className="py-2.5 text-right tabular-nums text-ink-2">{fmtNumber(d.cv_pct, 1)}%</td>
                <td className="py-2.5 text-right tabular-nums text-ink-2">{fmtNumber(d.gmi, 1)}%</td>
                <td className="py-2.5 text-right tabular-nums text-ink-3">{fmtNumber(d.coverage_pct)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
