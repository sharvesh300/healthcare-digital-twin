import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/cn";

export function Card({ className, ...props }: ComponentProps<"section">) {
  return <section className={cn("rounded-card border border-line bg-surface shadow-card", className)} {...props} />;
}

/** Card title row: small uppercase label, optional icon and right-hand slot. */
export function CardHeader({ icon, title, meta, right, className }: {
  icon?: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  right?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("flex items-center justify-between gap-3", className)}>
      <div className="flex min-w-0 items-center gap-2">
        {icon}
        <h2 className="label shrink-0">{title}</h2>
        {meta && <span className="min-w-0 truncate text-xs text-ink-3">· {meta}</span>}
      </div>
      {right}
    </header>
  );
}
