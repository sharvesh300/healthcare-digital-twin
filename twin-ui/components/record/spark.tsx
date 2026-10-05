import type { Range } from "@/lib/api/types";

/** A small trend of a test's results (oldest to newest, evenly spaced), with the reference
 *  range as a faint band. Under two results it draws nothing. */
export function ResultSpark({ points, range, color = "var(--primary)", className }: {
  points: [string, number][];
  range?: Range | null;
  color?: string;
  className?: string;
}) {
  if (points.length < 2) return <span className={className} aria-hidden />;
  const W = 96;
  const H = 24;
  const vs = points.map(([, v]) => v);
  const bounds: number[] = [...vs];
  for (const b of range ?? []) if (b != null) bounds.push(b);
  let lo = Math.min(...bounds);
  let hi = Math.max(...bounds);
  const pad = (hi - lo) * 0.12 || 1;
  lo -= pad;
  hi += pad;
  const x = (i: number) => 2 + (i / (points.length - 1)) * (W - 4);
  const y = (v: number) => H - 2 - ((v - lo) / (hi - lo)) * (H - 4);
  const d = vs.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join("");
  const [rlo, rhi] = range ?? [null, null];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className={className} width={W} height={H} aria-hidden>
      {range && (rlo != null || rhi != null) && (
        <rect x={0} width={W} y={y(rhi ?? hi)} height={Math.max(0, y(rlo ?? lo) - y(rhi ?? hi))} fill="var(--band-in-range)" opacity={0.09} />
      )}
      <path d={d} fill="none" stroke={color} strokeWidth={1.6} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(vs.length - 1)} cy={y(vs[vs.length - 1])} r={2.4} fill={color} />
    </svg>
  );
}
