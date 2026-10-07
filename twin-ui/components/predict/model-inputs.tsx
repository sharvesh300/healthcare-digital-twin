import { Activity, Check, CircleSlash, HeartPulse, Info, Utensils } from "lucide-react";

import { Card, CardHeader } from "@/components/ui/card";
import type { GlucoseForecast } from "@/lib/api/types";
import { fmtNumber, fmtTime, titleCase } from "@/lib/twin/format";

/** The recent meals, heart rate and activity the forecast used, and its accuracy on held-out data. */
export function ModelInputs({ data }: { data: GlucoseForecast }) {
  const { inputs, model } = data;
  if (!inputs || !model) return null;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="p-5">
        <CardHeader icon={<Utensils aria-hidden size={14} className="text-ink-3" />} title="Meals & activity" meta="last 4 h" />
        {inputs.glucose_only ? (
          <p className="mt-3 text-sm leading-relaxed text-ink-2">
            Not recorded for this twin: its source has no meal log or activity tracker. The forecast
            uses its CGM history alone and can&apos;t anticipate a meal.
          </p>
        ) : (
          <>
            <ul className="mt-3 space-y-1.5">
              {inputs.meals.length ? inputs.meals.map((m) => (
                <li key={m.time} className="flex items-baseline justify-between gap-3 text-sm">
                  <span className="text-ink">
                    <span className="tabular-nums text-ink-3">{fmtTime(m.time)}</span> {titleCase(m.meal_type)}
                  </span>
                  <span className="tabular-nums text-ink-2">
                    {fmtNumber(m.carbs_g)} g carbs · {fmtNumber(m.energy_kcal)} kcal
                  </span>
                </li>
              )) : <li className="text-sm text-ink-3">No meals logged in the last 4 hours</li>}
            </ul>
            <div className="mt-3 flex flex-wrap gap-2 border-t border-line pt-3">
              <InputChip ok={inputs.heart_rate} icon={<HeartPulse aria-hidden size={13} />} label="Heart rate" />
              <InputChip ok={inputs.activity} icon={<Activity aria-hidden size={13} />} label="Activity" />
            </div>
          </>
        )}
      </Card>
      <Card className="p-5">
        <CardHeader icon={<Info aria-hidden size={14} className="text-ink-3" />} title="Accuracy" meta={model.label} />
        <table className="mt-3 w-full text-sm">
          <thead>
            <tr className="text-left">
              <th className="label pb-1 font-medium">Horizon</th>
              <th className="label pb-1 text-right font-medium">Typical error</th>
              {model.band_coverage && <th className="label pb-1 text-right font-medium">Range held</th>}
            </tr>
          </thead>
          <tbody>
            {model.horizons.map((h) => (
              <tr key={h} className="border-t border-line">
                <td className="py-1.5 text-ink">+{h} min</td>
                <td className="py-1.5 text-right tabular-nums text-ink-2">
                  {model.test_rmse[String(h)] != null ? `±${fmtNumber(model.test_rmse[String(h)])} mg/dL` : "—"}
                </td>
                {model.band_coverage && (
                  <td className="py-1.5 text-right tabular-nums text-ink-2">{fmtNumber(100 * (model.band_coverage[String(h)] ?? 0))} %</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-3 text-xs leading-relaxed text-ink-3">
          {model.name === "arima"
            ? "Typical error is the benchmark RMSE of per-participant ARIMA on held-out CGMacros data (the last quarter of each recording); +45 min wasn't benchmarked. "
            : <>Typical error is the RMSE on held-out data (the last quarter of each participant&apos;s recording), for a model trained on {model.trained_on}. </>}
          {model.band_coverage && "Range held: how often the real reading fell inside the 80 % range. "}
          <span className="font-mono text-[11px]">{model.version}</span>
        </p>
      </Card>
    </div>
  );
}

function InputChip({ ok, icon, label }: { ok: boolean; icon: React.ReactNode; label: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-chip border px-2 py-1 text-xs ${ok ? "border-line text-ink-2" : "hatch border-dashed border-line-strong text-ink-3"}`}>
      {icon}
      {label}
      {ok ? <Check aria-label="used" size={12} className="text-status-ok" /> : <CircleSlash aria-label="missing" size={12} />}
    </span>
  );
}
