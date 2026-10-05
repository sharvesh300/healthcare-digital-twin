import Link from "next/link";

import { cn } from "@/lib/cn";
import { fmtDay, fmtYear } from "@/lib/record/format";

export interface TimelineEpisode {
  start: string;
  /** null: still going */
  end: string | null;
  label: string;
  href?: string;
  /** emphasised (active, or out of range) */
  strong?: boolean;
}

const DAY = 86400_000;

/** Episodes as bars on one time axis: diagnosis episodes, prescription episodes. A bar
 *  that is still going runs to today; a same-day episode is a dot. Bars link to their visit. */
export function EpisodeTimeline({ episodes, markers = [], now, color = "var(--primary)" }: {
  episodes: TimelineEpisode[];
  markers?: { at: string; label: string }[];
  now: number;
  color?: string;
}) {
  if (!episodes.length) return null;
  const starts = episodes.map((e) => Date.parse(e.start));
  const ends = episodes.map((e) => (e.end ? Date.parse(e.end) : now));
  let lo = Math.min(...starts);
  let hi = Math.max(...ends, lo + 30 * DAY);
  const pad = (hi - lo) * 0.03;
  lo -= pad;
  hi += pad;
  const pct = (t: number) => ((t - lo) / (hi - lo)) * 100;
  const firstYear = new Date(lo).getUTCFullYear() + 1;
  const lastYear = new Date(hi).getUTCFullYear();
  const step = Math.max(1, Math.ceil((lastYear - firstYear + 1) / 8));
  const years = [];
  for (let y = firstYear; y <= lastYear; y += step) years.push(Date.UTC(y, 0, 1));

  return (
    <div className="relative" role="img" aria-label={`${episodes.length} episodes from ${fmtYear(Math.min(...starts))}`}>
      <div className="relative h-12 rounded-control bg-surface-2">
        {years.map((t) => (
          <span key={t} aria-hidden className="absolute inset-y-0 w-px bg-line" style={{ left: `${pct(t)}%` }} />
        ))}
        {episodes.map((e, i) => {
          const a = pct(starts[i]);
          const width = Math.max(pct(ends[i]) - a, 0);
          const point = ends[i] - starts[i] < 2 * DAY;
          const title = `${e.label}: ${fmtDay(e.start)}${point ? "" : ` – ${e.end ? fmtDay(e.end) : "ongoing"}`}`;
          const cls = cn("absolute top-1/2 -translate-y-1/2 rounded-full ring-2 ring-surface-2 transition-opacity hover:opacity-80",
            point ? "size-3 -translate-x-1/2" : "h-3", !e.end && "rounded-r-sm");
          const style = { left: `${a}%`, width: point ? undefined : `max(${width}%, 6px)`, background: color, opacity: e.strong ? 1 : 0.55 };
          return e.href
            ? <Link key={i} href={e.href} title={title} aria-label={title} className={cls} style={style} />
            : <span key={i} title={title} className={cls} style={style} />;
        })}
        {markers.map((m) => (
          <span key={m.at} title={m.label} aria-label={m.label} className="absolute -top-1 bottom-0 w-0.5 rounded-full bg-status-warn"
            style={{ left: `${pct(Date.parse(m.at))}%` }} />
        ))}
      </div>
      <div className="relative mt-1.5 h-4 text-[11px] tabular-nums text-ink-3">
        {years.map((t) => (
          <span key={t} className="absolute -translate-x-1/2" style={{ left: `${pct(t)}%` }}>{new Date(t).getUTCFullYear()}</span>
        ))}
      </div>
    </div>
  );
}
