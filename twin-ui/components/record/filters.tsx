import Link from "next/link";

import { cn } from "@/lib/cn";

export interface FilterOption {
  /** the query value; null clears the parameter */
  value: string | null;
  label: string;
  count?: number;
}

type Params = Record<string, string | string[] | undefined>;

/** `path?query` with `key` set to `value` (or removed), keeping the other parameters. */
export function withParam(path: string, params: Params, key: string, value: string | null): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (typeof v === "string" && k !== key && k !== "cursor") q.set(k, v);
  if (value != null) q.set(key, value);
  const s = q.toString();
  return s ? `${path}?${s}` : path;
}

/** A segmented filter whose options are links: the filter lives in the URL, so a filtered
 *  view can be shared, survives a refresh and back navigation, and needs no client code. */
export function FilterLinks({ label, name, options, path, params }: {
  label: string;
  name: string;
  options: FilterOption[];
  path: string;
  params: Params;
}) {
  const current = typeof params[name] === "string" ? (params[name] as string) : null;
  return (
    <nav aria-label={label} className="flex max-w-full overflow-x-auto rounded-control border border-line bg-surface-2 p-0.5 [scrollbar-width:none]">
      {options.map((o) => {
        const active = o.value === current;
        if (o.count === 0 && !active) {
          return (
            <span key={o.label} aria-disabled="true" title="Nothing to show"
              className="cursor-default whitespace-nowrap rounded-[8px] px-2.5 py-1 text-xs font-medium tabular-nums text-ink-3/60">
              {o.label}<span className="ml-1">0</span>
            </span>
          );
        }
        return (
          <Link key={o.label} href={withParam(path, params, name, o.value)} aria-current={active ? "true" : undefined} scroll={false}
            className={cn("whitespace-nowrap rounded-[8px] px-2.5 py-1 text-xs font-medium tabular-nums transition-colors",
              active ? "bg-surface text-ink shadow-card" : "text-ink-3 hover:text-ink-2")}>
            {o.label}
            {o.count != null && <span className={cn("ml-1", active ? "text-ink-3" : "text-ink-3/80")}>{o.count}</span>}
          </Link>
        );
      })}
    </nav>
  );
}
