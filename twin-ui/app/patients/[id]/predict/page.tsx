import { LineChart, SlidersHorizontal, Sparkles } from "lucide-react";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Predict" };

const MODULES = [
  { icon: LineChart, title: "Glucose forecast", body: "+30 and +60 minute forecast from the trained forecaster, drawn as a dashed line with a hatched uncertainty band on the live glucose chart." },
  { icon: SlidersHorizontal, title: "What-if sandbox", body: "Change activity, heart rate, insulin, steps, BMI or medication classes and compare the model's baseline with the scenario." },
];

export default function PredictPage() {
  return (
    <div className="rounded-card border border-line bg-surface p-8 shadow-card">
      <span className="inline-flex items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-[11px] font-medium text-ink-2">
        <Sparkles size={12} /> Model estimate · coming next
      </span>
      <h2 className="mt-4 text-xl font-semibold tracking-tight text-ink">Predictions</h2>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-3">
        The API already serves model-based scenarios (<code className="font-mono text-xs">/twin/&#123;id&#125;/simulate/glucose</code> and{" "}
        <code className="font-mono text-xs">/simulate/hba1c</code>). This tab will show them in the twin&apos;s own visual language: dashed and
        hatched, never styled like a measurement, with the model&apos;s caveat always visible.
      </p>
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        {MODULES.map(({ icon: Icon, title, body }) => (
          <div key={title} className="hatch rounded-card border border-dashed border-line-strong p-5">
            <Icon size={18} className="text-ink-2" />
            <h3 className="mt-3 text-sm font-semibold text-ink">{title}</h3>
            <p className="mt-1 text-sm leading-relaxed text-ink-3">{body}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
