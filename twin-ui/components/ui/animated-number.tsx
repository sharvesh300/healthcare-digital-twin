"use client";

import { animate } from "motion/react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/cn";
import { fmtNumber } from "@/lib/twin/format";

/** A number that tweens to its new value (600 ms). React renders the first value only; the
 *  tween writes the text afterwards, so React never fights the animation. */
export function AnimatedNumber({ value, digits = 0, className }: { value: number | null; digits?: number; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const previous = useRef(value);
  const [initial] = useState(() => fmtNumber(value, digits));

  useEffect(() => {
    const node = ref.current;
    const from = previous.current;
    previous.current = value;
    if (!node) return;
    if (value == null || from == null || from === value) {
      node.textContent = fmtNumber(value, digits);
      return;
    }
    const controls = animate(from, value, {
      duration: 0.6,
      ease: [0.2, 0.8, 0.2, 1],
      onUpdate: (v) => {
        node.textContent = fmtNumber(v, digits);
      },
    });
    return () => controls.stop();
  }, [value, digits]);

  return (
    <span ref={ref} className={cn("tabular-nums", className)}>
      {initial}
    </span>
  );
}
