"use client";

import { ArrowRight } from "lucide-react";
import { motion } from "motion/react";

import type { GlucoseTrend } from "@/lib/api/types";
import { TREND_ANGLE, TREND_LABEL } from "@/lib/twin/format";

/** One arrow that turns between the five trend angles (Dexcom-style). */
export function TrendArrow({ trend, size = 22, className }: { trend: GlucoseTrend | null; size?: number; className?: string }) {
  if (!trend) return null;
  return (
    <motion.span
      role="img"
      aria-label={TREND_LABEL[trend]}
      className={className}
      style={{ display: "inline-flex" }}
      initial={false}
      animate={{ rotate: TREND_ANGLE[trend] }}
      transition={{ type: "spring", stiffness: 160, damping: 18 }}
    >
      <ArrowRight size={size} strokeWidth={2.5} />
    </motion.span>
  );
}
