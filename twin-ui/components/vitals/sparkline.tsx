import type { Point } from "@/lib/twin/store";

/** A minimal trend line: last `hours` of points, 2 px stroke in the vital hue, end dot.
 *  Optional faint target band (e.g. glucose 70–180). Gaps longer than `gapMin` break the line. */
export function Sparkline({ points, color, hours = 3, band, height = 40, gapMin = 20, className }: {
  points: Point[];
  color: string;
  hours?: number;
  band?: [number, number];
  height?: number;
  gapMin?: number;
  className?: string;
}) {
  const W = 200;
  const H = height;
  const end = points.length ? points[points.length - 1].t : 0;
  const pts = points.filter((p) => p.t >= end - hours * 3600_000);
  if (pts.length < 2) return <div className={className} style={{ height: H }} aria-hidden />;
  const vs = pts.map((p) => p.v);
  let lo = Math.min(...vs, ...(band ?? []));
  let hi = Math.max(...vs, ...(band ?? []));
  const pad = (hi - lo) * 0.12 || 5;
  lo -= pad;
  hi += pad;
  const x = (t: number) => ((t - (end - hours * 3600_000)) / (hours * 3600_000)) * W;
  const y = (v: number) => H - ((v - lo) / (hi - lo)) * H;
  let d = "";
  pts.forEach((p, i) => {
    const jump = i === 0 || p.t - pts[i - 1].t > gapMin * 60_000;
    d += `${jump ? "M" : "L"}${x(p.t).toFixed(1)} ${y(p.v).toFixed(1)}`;
  });
  const last = pts[pts.length - 1];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className={className} style={{ height: H, width: "100%" }} aria-hidden>
      {band && <rect x={0} width={W} y={y(band[1])} height={y(band[0]) - y(band[1])} fill="var(--band-in-range)" opacity={0.07} />}
      <path d={d} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      <circle cx={x(last.t)} cy={y(last.v)} r={3} fill={color} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
