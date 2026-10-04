"use client";

import { Footprints, HeartPulse, Moon, Watch, Wind } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import type { CSSProperties, ReactNode } from "react";

import type { TwinState } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { fmtAge, fmtNumber, fmtTime, isAsleep, statusLabel, TREND_LABEL } from "@/lib/twin/format";
import { band, isBand, vital } from "@/lib/tokens";

// Stage: 420 × 440 view box. The figure is drawn in its own 240 × 420 space, centred at x = 120,
// and placed at (90, 10). Limbs are drawn from their joint (shoulder / hip) so a CSS rotation
// about "0 0" swings them naturally.
const VB_W = 420;
const VB_H = 440;
const at = (x: number, y: number): CSSProperties => ({ left: `${(x / VB_W) * 100}%`, top: `${(y / VB_H) * 100}%` });

const SPO2_FILL: Record<string, number> = { normal: 0.28, borderline: 0.17, low: 0.1 };
const STRIDE: Record<string, string> = { moderate: "1.15s", vigorous: "0.75s" };

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);

export function TwinFigure({ state, glucosePulse, now, pausedLabel, className }: {
  state: TwinState;
  glucosePulse: number;
  now: number | null;
  /** caption while not streaming, instead of "last seen" (e.g. "Replay paused") */
  pausedLabel?: string;
  className?: string;
}) {
  const hr = num(state.heart_rate.value);
  const rr = num(state.respiration_rate.value);
  const hrFresh = hr != null && state.heart_rate.status !== "stale";
  const asleep = isAsleep(state.sleep.status);
  const level = asleep ? "sleeping" : (state.activity.status ?? "sedentary");
  const walking = level === "moderate" || level === "vigorous";
  const gBand = state.glucose.status;
  const aura = isBand(gBand) ? band[gBand] : "rgb(102 117 111 / 0.35)";
  const spo2Fill = SPO2_FILL[state.spo2.status ?? "normal"] ?? 0.2;
  const live = state.streaming;

  const vars = {
    "--beat": `${hr ? 60 / clamp(hr, 30, 200) : 1}s`,
    "--breath": `${rr ? 60 / clamp(rr, 6, 40) : 4}s`,
    "--stride": STRIDE[level] ?? "1.2s",
    "--aura": aura,
  } as CSSProperties;

  const summary = [
    hr != null && `Heart rate ${fmtNumber(hr)}, ${statusLabel(state.heart_rate.status)}`,
    state.glucose.value != null &&
      `Glucose ${fmtNumber(state.glucose.value as number)}, ${statusLabel(gBand)}${state.glucose.trend ? `, ${TREND_LABEL[state.glucose.trend].toLowerCase()}` : ""}`,
    asleep ? `Asleep, ${statusLabel(state.sleep.status)} sleep` : `Activity ${statusLabel(state.activity.status)}`,
  ].filter(Boolean).join(". ");

  return (
    <div
      className={cn(
        "twin-stage relative isolate w-full overflow-hidden rounded-stage border border-line",
        asleep ? "bg-surface-3" : "bg-surface-2",
        !live && "twin-paused",
        className,
      )}
      style={{
        ...vars,
        aspectRatio: `${VB_W} / ${VB_H}`,
        backgroundImage: "radial-gradient(var(--line) 1px, transparent 1px)",
        backgroundSize: "12px 12px",
      }}
    >
      {/* slow scan line: the "digital twin" texture */}
      <div aria-hidden className="twin-scan pointer-events-none absolute inset-x-0 top-0 h-[18%] bg-gradient-to-b from-transparent via-white/50 to-transparent" />

      <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className={cn("relative h-full w-full transition-[filter,opacity] duration-700", !live && "opacity-90 saturate-[.55]")} role="img" aria-label={summary || "Twin figure, no data yet"}>
        <defs>
          <radialGradient id="twin-aura" cx="50%" cy="45%" r="50%">
            <stop offset="0%" style={{ stopColor: "var(--aura)", stopOpacity: 0.32 }} />
            <stop offset="60%" style={{ stopColor: "var(--aura)", stopOpacity: 0.12 }} />
            <stop offset="100%" style={{ stopColor: "var(--aura)", stopOpacity: 0 }} />
          </radialGradient>
          <linearGradient id="twin-skin" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#ffffff" />
            <stop offset="100%" stopColor="#f1f5f3" />
          </linearGradient>
        </defs>

        {/* bed: fades in for the sleep scene */}
        <motion.g initial={false} animate={{ opacity: asleep ? 1 : 0 }} transition={{ duration: 0.6 }}>
          <rect x={46} y={272} width={336} height={12} rx={7} fill="var(--line-strong)" opacity={0.7} />
          <rect x={50} y={240} width={64} height={30} rx={14} fill="#fff" stroke="var(--line-strong)" />
          <rect x={48} y={284} width={8} height={26} rx={3} fill="var(--line-strong)" />
          <rect x={372} y={284} width={8} height={26} rx={3} fill="var(--line-strong)" />
        </motion.g>

        <motion.g
          initial={false}
          animate={asleep ? { rotate: -90, scale: 0.8, y: 10, x: 4 } : { rotate: 0, scale: 1, y: 0, x: 0 }}
          transition={{ type: "spring", stiffness: 70, damping: 16 }}
        >
          <g transform="translate(90 10)">
            <g
              className={cn(level === "light" && "twin-sway", walking && "twin-bob")}
              style={{ transformOrigin: "120px 400px" }}
            >
              {/* metabolic aura: glucose band colour behind the torso */}
              <ellipse
                cx={120}
                cy={168}
                rx={104}
                ry={132}
                fill="url(#twin-aura)"
                className={cn((gBand === "very_low" || gBand === "very_high") && "twin-glow")}
              />

              <Limb origin={[106, 214]} d="M0 0 L-3 96 L-5 172" width={20} className={walking ? "twin-step-reverse" : undefined}>
                <ellipse cx={-10} cy={180} rx={14} ry={6.5} fill="url(#twin-skin)" stroke="var(--line-strong)" strokeWidth={1.5} />
              </Limb>
              <Limb origin={[134, 214]} d="M0 0 L3 96 L5 172" width={20} className={walking ? "twin-step" : undefined}>
                <ellipse cx={10} cy={180} rx={14} ry={6.5} fill="url(#twin-skin)" stroke="var(--line-strong)" strokeWidth={1.5} />
              </Limb>
              <Limb origin={[84, 106]} d="M0 0 L-11 62 L-17 116" width={18} className={walking ? "twin-swing" : undefined}>
                <circle cx={-18} cy={124} r={8.5} fill="url(#twin-skin)" stroke="var(--line-strong)" strokeWidth={1.5} />
              </Limb>

              {/* neck, torso */}
              <rect x={110} y={72} width={20} height={26} rx={8} fill="url(#twin-skin)" stroke="var(--line-strong)" strokeWidth={1.5} />
              <path
                d="M80 106 C80 97 88 92 99 91 L141 91 C152 92 160 97 160 106 L154 192 C153 210 146 219 134 221 L106 221 C94 219 87 210 86 192 Z"
                fill="url(#twin-skin)"
                stroke="var(--line-strong)"
                strokeWidth={1.5}
              />

              {/* lungs (oxygen): breathe at the measured rate; fill follows the SpO₂ band */}
              <g className="twin-part twin-breathe">
                <motion.ellipse cx={103} cy={140} rx={13} ry={25} fill={vital.oxygen} initial={false} animate={{ opacity: spo2Fill }} transition={{ duration: 0.6 }} />
                <motion.ellipse cx={137} cy={140} rx={13} ry={25} fill={vital.oxygen} initial={false} animate={{ opacity: spo2Fill }} transition={{ duration: 0.6 }} />
                {state.spo2.status === "low" && (
                  <>
                    <ellipse cx={103} cy={140} rx={13} ry={25} fill="none" stroke="var(--status-warn)" strokeWidth={1.5} />
                    <ellipse cx={137} cy={140} rx={13} ry={25} fill="none" stroke="var(--status-warn)" strokeWidth={1.5} />
                  </>
                )}
              </g>

              {/* heart: beats at the measured heart rate, grey and still when stale */}
              <g transform="translate(127 150)">
                {hrFresh && <circle r={10} fill="none" stroke={vital.heart} strokeWidth={1.5} className="twin-part twin-ripple" />}
                <path
                  d="M0 -3 C0 -8 -7 -9.5 -8.5 -4.5 C-9.5 0.5 -3.5 5 0 8.5 C3.5 5 9.5 0.5 8.5 -4.5 C7 -9.5 0 -8 0 -3 Z"
                  transform="scale(1.45)"
                  fill={hrFresh ? vital.heart : "var(--ink-3)"}
                  className={cn("twin-part transition-[fill] duration-500", hrFresh && "twin-beat")}
                />
              </g>

              {/* the patient's left arm (viewer's right) carries the CGM and the watch */}
              <Limb origin={[156, 106]} d="M0 0 L11 62 L17 116" width={18} className={walking ? "twin-swing-reverse" : undefined}>
                <circle cx={18} cy={124} r={8.5} fill="url(#twin-skin)" stroke="var(--line-strong)" strokeWidth={1.5} />
                <AnimatePresence>
                  {glucosePulse > 0 && (
                    <motion.circle
                      key={glucosePulse}
                      cx={6}
                      cy={36}
                      fill="none"
                      stroke={isBand(gBand) ? band[gBand] : vital.glucose}
                      strokeWidth={2}
                      initial={{ r: 8, opacity: 0.8 }}
                      animate={{ r: 30, opacity: 0 }}
                      exit={{ opacity: 0 }}
                      transition={{ duration: 1.2, ease: "easeOut" }}
                    />
                  )}
                </AnimatePresence>
                <circle cx={6} cy={36} r={8} fill="#fff" stroke={vital.glucose} strokeWidth={3} />
                <circle cx={6} cy={36} r={2.5} fill={vital.glucose} />
                <rect x={9} y={102} width={16} height={13} rx={4} fill={vital.activity} />
                <rect x={12} y={105} width={10} height={7} rx={2} fill="#fff" opacity={0.85} />
              </Limb>

              {/* head */}
              <circle cx={120} cy={50} r={27} fill="url(#twin-skin)" stroke="var(--line-strong)" strokeWidth={1.5} />
              {asleep ? (
                <g stroke="var(--ink-2)" strokeWidth={1.6} strokeLinecap="round" fill="none">
                  <path d="M106 52 q4 3.5 8 0" />
                  <path d="M126 52 q4 3.5 8 0" />
                </g>
              ) : (
                <g fill="var(--ink-2)">
                  <circle cx={110} cy={50} r={2.4} />
                  <circle cx={130} cy={50} r={2.4} />
                </g>
              )}
              <path d="M113 61 q7 4.5 14 0" fill="none" stroke="var(--ink-3)" strokeWidth={1.5} strokeLinecap="round" />
            </g>
          </g>
        </motion.g>

        {/* sleep: z's drift up from the pillow (fewer in deep sleep) */}
        {asleep &&
          Array.from({ length: state.sleep.status === "deep" ? 1 : state.sleep.status === "rem" ? 2 : 3 }, (_, i) => (
            <text key={i} x={92 + i * 10} y={208 - i * 6} className="twin-z" style={{ animationDelay: `${i * 0.9}s` }}
              fill="var(--ink-3)" fontSize={14 + i * 3} fontWeight={600}>
              z
            </text>
          ))}

        {/* leader lines to the organ callouts */}
        <AnimatePresence>
          {!asleep && (
            <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="hidden sm:block"
              stroke="var(--line-strong)" strokeWidth={1} fill="none" strokeDasharray="2 3">
              <path d="M226 158 L262 130 L300 130" />
              <path d="M180 150 L150 128 L120 128" />
            </motion.g>
          )}
        </AnimatePresence>
      </svg>

      {/* callouts (HTML, so text stays crisp and readable at any stage size) */}
      <AnimatePresence>
        {!asleep ? (
          <motion.div key="awake" className="absolute inset-0 hidden sm:block" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <Callout style={at(300, 130)} side="right" icon={<HeartPulse size={13} style={{ color: vital.heart }} />}
              text={hr != null ? `${fmtNumber(hr)} bpm` : "—"} muted={!hrFresh} />
            <Callout style={at(120, 128)} side="left" icon={<Wind size={13} style={{ color: vital.oxygen }} />}
              text={`${fmtNumber(state.spo2.value as number)}% · ${fmtNumber(rr)}/min`} muted={state.spo2.value == null} />
            <Callout style={at(306, 200)} side="right"
              icon={<span className="size-2.5 rounded-full border-2" style={{ borderColor: vital.glucose }} />}
              text={state.glucose.value != null ? `CGM ${fmtNumber(state.glucose.value as number)} ${state.glucose.trend ? TREND_GLYPH[state.glucose.trend] : ""}` : "CGM —"}
              muted={state.glucose.status === "stale"} />
            <Callout style={at(306, 262)} side="right" icon={<Watch size={13} style={{ color: vital.activity }} />}
              text={state.steps_today.value == null && state.active_kcal.value != null
                ? `${fmtNumber(state.active_kcal.value as number, 1)} kcal/min`
                : `${fmtNumber(state.steps_today.value as number)} steps`}
              muted={state.steps_today.value == null && state.active_kcal.value == null} />
          </motion.div>
        ) : (
          <motion.div key="asleep" className="absolute inset-x-0 bottom-3 flex justify-center" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface/90 px-3 py-1 text-xs font-medium text-ink shadow-card backdrop-blur">
              <Moon size={13} className="text-ink-2" />
              {statusLabel(state.sleep.status)} sleep
              {state.sleep.until && <span className="text-ink-3">· until {fmtTime(state.sleep.until)}</span>}
            </span>
          </motion.div>
        )}
      </AnimatePresence>

      {/* caption: posture and freshness (the sleep chip takes its place while asleep) */}
      <div className={cn("absolute inset-x-0 bottom-3 flex justify-center px-3", asleep && "hidden")}>
        <motion.span
          key={level}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          className="inline-flex items-center gap-1.5 rounded-full bg-surface/85 px-3 py-1 text-xs text-ink-2 shadow-card backdrop-blur"
        >
          {asleep ? <Moon size={13} /> : <Footprints size={13} style={{ color: vital.activity }} />}
          {POSTURE_LABEL[level] ?? statusLabel(level)}
          {!live && <span className="text-ink-3">· {pausedLabel ?? `last seen ${now ? fmtAge(state.glucose.time ?? state.heart_rate.time, now) : "—"}`}</span>}
        </motion.span>
      </div>
    </div>
  );
}

const TREND_GLYPH: Record<string, string> = { rising_fast: "⇈", rising: "↗", steady: "→", falling: "↘", falling_fast: "⇊" };
const POSTURE_LABEL: Record<string, string> = {
  sedentary: "Resting",
  light: "Light activity",
  moderate: "Walking · moderate",
  vigorous: "Brisk walk · vigorous",
  sleeping: "Asleep",
};

/** A limb drawn from its joint: outline stroke + white stroke, rotated about the joint by CSS. */
function Limb({ origin, d, width, className, children }: {
  origin: [number, number];
  d: string;
  width: number;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <g transform={`translate(${origin[0]} ${origin[1]})`}>
      <g className={className} style={{ transformOrigin: "0px 0px" }}>
        <path d={d} stroke="var(--line-strong)" strokeWidth={width + 3} strokeLinecap="round" strokeLinejoin="round" fill="none" />
        <path d={d} stroke="#fbfcfc" strokeWidth={width} strokeLinecap="round" strokeLinejoin="round" fill="none" />
        {children}
      </g>
    </g>
  );
}

function Callout({ style, side, icon, text, muted }: { style: CSSProperties; side: "left" | "right"; icon: ReactNode; text: string; muted?: boolean }) {
  return (
    <span
      className={cn(
        "absolute inline-flex -translate-y-1/2 items-center gap-1.5 whitespace-nowrap rounded-full border border-line bg-surface/95 px-2.5 py-1 text-xs font-medium tabular-nums shadow-card backdrop-blur",
        side === "left" && "-translate-x-full",
        muted ? "text-ink-3" : "text-ink",
      )}
      style={style}
    >
      {icon}
      {text}
    </span>
  );
}
