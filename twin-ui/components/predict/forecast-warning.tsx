import { OctagonAlert, TriangleAlert } from "lucide-react";

import type { ForecastWarning } from "@/lib/api/types";
import { headline, SEVERITY_COLOR, sortWarnings, WARNING_TITLE } from "@/lib/predict/format";

/** The most severe forecast warning as a banner, with the others listed under it. Nothing when
 *  the forecast has no warning above "info". */
export function ForecastWarningBanner({ warnings }: { warnings: ForecastWarning[] }) {
  const top = headline(warnings);
  if (!top) return null;
  const rest = sortWarnings(warnings).filter((w) => w !== top && w.severity !== "info");
  const color = SEVERITY_COLOR[top.severity];
  const Icon = top.severity === "danger" ? OctagonAlert : TriangleAlert;
  return (
    <div role="status" className="flex items-start gap-3 rounded-card border p-4"
      style={{ borderColor: `color-mix(in srgb, ${color} 35%, var(--line))`, background: `color-mix(in srgb, ${color} 7%, var(--surface))` }}>
      <span className="grid size-8 shrink-0 place-items-center rounded-full" style={{ background: `color-mix(in srgb, ${color} 14%, var(--surface))`, color }}>
        <Icon aria-hidden size={17} strokeWidth={2.4} />
      </span>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-ink">
          {WARNING_TITLE[top.kind]} <span className="font-normal text-ink-2">at +{top.horizon_min} min</span>
        </p>
        <p className="mt-0.5 text-sm text-ink-2">{top.message}.</p>
        {rest.length > 0 && (
          <ul className="mt-2 space-y-0.5 text-xs text-ink-3">
            {rest.map((w) => <li key={w.kind}>{WARNING_TITLE[w.kind]}: {w.message}.</li>)}
          </ul>
        )}
      </div>
    </div>
  );
}
