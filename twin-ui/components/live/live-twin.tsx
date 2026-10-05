"use client";

import { Activity, Brain, Check, Copy, Crosshair, Droplet, Flame, Footprints, HeartPulse, History, Moon, Radio, Terminal, Thermometer, Waves, Wind, X, Zap } from "lucide-react";
import { AnimatePresence, motion, type Variants } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";

import { ChartCard, type MomentInspect } from "@/components/charts/time-series-chart";
import { TransitionFeed } from "@/components/feed/transition-feed";
import { TwinFigure } from "@/components/twin/twin-figure";
import { GlucoseHero } from "@/components/vitals/glucose-hero";
import { BandChip, StatusChip } from "@/components/vitals/chips";
import { VitalCard } from "@/components/vitals/vital-card";
import type { Signal, TwinState } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { fmtAge, fmtDate, fmtNumber, fmtTime, isAbnormal, isAsleep, SIGNAL_LABEL, statusLabel, statusTone, tzAbbr } from "@/lib/twin/format";
import type { FeedItem, Point, TwinInit } from "@/lib/twin/store";
import { useNow, useTwinStream, type StreamSource } from "@/lib/twin/use-twin-stream";
import { band, GLUCOSE_LIMITS, glucoseBand, heartRateBand, isBand, tone, vital } from "@/lib/tokens";

import { ConnectionBadge } from "./connection-badge";
import { ReplayBar, type ReplayWindow } from "./replay-bar";

const container: Variants = { hidden: {}, show: { transition: { staggerChildren: 0.06, delayChildren: 0.05 } } };
const item: Variants = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.2, 0.8, 0.2, 1] } },
};

/** The device clock: the newest reading across signals (a fast replay runs ahead of the wall clock). */
function deviceTime(s: TwinState): string | null {
  const times = [s.glucose, s.heart_rate, s.activity, s.spo2, s.respiration_rate, s.sleep].map((x) => x.time).filter(Boolean) as string[];
  return times.sort().at(-1) ?? null;
}

type Mode = "live" | "replay";
/** A moment being inspected: when, what led there (a status change, a chart reading). */
type Focus = { t: number; label: string; id?: string };

const HOUR = 3600_000;
const iso = (t: number) => new Date(t).toISOString();

function defaultWindow(extent: ReplayWindow): ReplayWindow {
  return { start: Math.max(extent.start, extent.end - 6 * HOUR), end: extent.end };
}

/** A window around an inspected moment: an hour of lead-in, two hours to play on. */
function windowAround(t: number, extent: ReplayWindow): ReplayWindow {
  const end = Math.min(extent.end, t + 2 * HOUR);
  return { start: Math.min(Math.max(extent.start, t - HOUR), end - 10 * 60_000), end };
}

/** The twin, live now or replayed: the same components either way, fed by the same protocol.
 *  Any moment (a chart point, a status change, `?at=`) opens the replay paused there, so the
 *  whole twin can be seen as it was. */
export function LiveTwin({ patientId, init, recording: rec, initialAt = null }: {
  patientId: string;
  init: TwinInit;
  recording: { start: string; end: string } | null;
  /** open the replay at this moment (ms) */
  initialAt?: number | null;
}) {
  const recording = useMemo(() => (rec ? { start: Date.parse(rec.start), end: Date.parse(rec.end) } : null), [rec]);
  // Streamed readings run on past the recording (a fast simulator even ahead of the wall
  // clock): the replayable extent ends at the newest reading seen live.
  const [liveEnd, setLiveEnd] = useState<number | null>(() => {
    const d = deviceTime(init.state);
    return d ? Date.parse(d) : null;
  });
  const [mountedAt] = useState(() => Date.now()); // a recording time-shifted past now is cut at now
  const firstPoint = Math.min(init.series.glucose?.[0]?.t ?? Infinity, init.series.heart_rate?.[0]?.t ?? Infinity);
  const extent = useMemo((): ReplayWindow | null => {
    const start = Math.min(recording?.start ?? Infinity, firstPoint, liveEnd ?? Infinity);
    const end = Math.max(recording ? Math.min(recording.end, mountedAt) : -Infinity, liveEnd ?? -Infinity);
    return Number.isFinite(start) && end > start ? { start, end } : null;
  }, [recording, firstPoint, liveEnd, mountedAt]);

  const opening = initialAt != null && extent ? Math.min(Math.max(initialAt, extent.start), extent.end) : null;
  const [mode, setMode] = useState<Mode>(opening != null ? "replay" : "live");
  const [win, setWin] = useState<ReplayWindow | null>(() => (opening != null && extent ? windowAround(opening, extent) : null));
  const [at, setAt] = useState<number | null>(opening); // where a new session opens; later moves are seeks
  const [focus, setFocus] = useState<Focus | null>(() => (opening != null ? { t: opening, label: "the linked moment" } : null));
  const [speed, setSpeed] = useState(120);
  const [sessionSpeed, setSessionSpeed] = useState(120); // speed a session opens with; later changes are commands
  const top = useRef<HTMLDivElement>(null);

  const source: StreamSource = mode === "replay" && win
    ? { kind: "replay", start: iso(win.start), end: iso(win.end), speed: sessionSpeed, autoplay: false, live: true, ...(at != null && { at: iso(at) }) }
    : { kind: "live" };
  const { view, send } = useTwinStream(patientId, init, source);
  const wall = useNow();
  const replaying = source.kind === "replay";
  // Ages ("2 min ago") are measured on the clock being watched: the replay's, or the wall's.
  const now = replaying ? (view.replay ? Date.parse(view.replay.cursor) : null) : wall;
  const s = view.state;
  const device = deviceTime(s);
  if (!replaying && device && (liveEnd == null || Date.parse(device) > liveEnd)) setLiveEnd(Date.parse(device));

  const setUrl = (t: number | null) => {
    const q = new URLSearchParams(window.location.search);
    if (t == null) q.delete("at");
    else q.set("at", iso(t));
    const qs = q.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${qs ? `?${qs}` : ""}`);
  };

  const enterReplay = () => {
    if (!extent) return;
    setWin((w) => w ?? defaultWindow(extent));
    setSessionSpeed(speed);
    setMode("replay");
  };
  const goLive = () => {
    setMode("live");
    setFocus(null);
    setAt(null);
    setUrl(null);
  };
  const changeWindow = (w: ReplayWindow) => {
    setSessionSpeed(speed);
    setAt(null);
    setFocus(null);
    setUrl(null);
    setWin(w);
  };
  /** Show the whole twin as it was at `t`: seek if the open replay covers it, else open one there. */
  const inspect = (t: number, label: string, id?: string) => {
    if (!extent) return;
    const moment = Math.min(Math.max(t, extent.start), extent.end);
    setFocus({ t: moment, label, id });
    setUrl(moment);
    if (replaying && win && view.status === "live" && moment >= win.start && moment <= win.end) {
      send({ type: "seek", to: iso(moment) });
    } else {
      setWin(windowAround(moment, extent));
      setAt(moment);
      setSessionSpeed(speed);
      setMode("replay");
    }
  };
  // bring the figure and the replay controls into view when a moment is picked further down
  // (instantly: the replay's snapshot re-renders the page and would cancel a smooth scroll)
  const focusT = focus?.t;
  useEffect(() => {
    if (focusT != null && (top.current?.getBoundingClientRect().top ?? 0) < 0) top.current?.scrollIntoView({ block: "start" });
  }, [focusT]);
  const inspectFeed = (t: FeedItem) => inspect(Date.parse(t.time), `${SIGNAL_LABEL[t.signal]} → ${statusLabel(t.to)}`, t.id);
  const chartInspect = (label: string, exclude: "glucose" | "heart_rate"): MomentInspect | undefined =>
    extent ? {
      action: replaying ? "Jump the replay here" : "See the full twin then",
      onOpen: (t) => inspect(t, label),
      render: (t) => <MomentSummary t={t} series={view.series} feed={view.feed} exclude={exclude} />,
    } : undefined;

  return (
    <motion.div ref={top} variants={container} initial="hidden" animate="show" className="scroll-mt-24 space-y-5">
      <motion.div variants={item} className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <div role="radiogroup" aria-label="View" className="flex rounded-control border border-line bg-surface-2 p-0.5">
            {([["live", "Live now", Radio], ["replay", "Replay", History]] as const).map(([m, label, Icon]) => {
              const disabled = m === "replay" && !extent;
              return (
                <button key={m} role="radio" aria-checked={mode === m} disabled={disabled}
                  title={disabled ? "No recorded sensor data to replay" : undefined}
                  onClick={() => (m === "replay" ? enterReplay() : goLive())}
                  className={cn("relative inline-flex items-center gap-1.5 rounded-[8px] px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                    mode === m ? "text-ink" : "text-ink-3 hover:text-ink-2")}>
                  {mode === m && <motion.span layoutId="view-mode" className="absolute inset-0 rounded-[8px] bg-surface shadow-card" transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
                  <Icon size={13} className={cn("relative", mode === m && "text-primary")} />
                  <span className="relative">{label}</span>
                </button>
              );
            })}
          </div>
          {replaying ? (
            <ReplayBadge status={view.replay?.status ?? null} connected={view.status === "live"} speed={view.replay?.speed ?? speed} />
          ) : (
            <ConnectionBadge status={view.status} streaming={s.streaming} />
          )}
          <span className="text-xs text-ink-3">
            {replaying ? "Replay time" : "Device time"}{" "}
            <span className="font-mono text-ink-2 tabular-nums">
              {replaying ? (view.replay ? fmtTime(view.replay.cursor, true) : "—") : device ? fmtTime(device, true) : "—"}
            </span>{" "}
            {device ? tzAbbr(device) : ""}
          </span>
        </div>
        <span className="font-mono text-[11px] text-ink-3 tabular-nums" title="Twin state version">v{s.version}</span>
      </motion.div>

      <AnimatePresence initial={false}>
        {replaying && focus && (
          <motion.div key="focus" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.25, ease: [0.2, 0.8, 0.2, 1] }}
            className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-status-warn/25 bg-[color-mix(in_srgb,var(--status-warn)_6%,var(--surface))] px-4 py-3 shadow-card">
            <div className="flex min-w-0 items-center gap-3">
              <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-surface text-status-warn shadow-card">
                <Crosshair aria-hidden size={15} />
              </span>
              <div className="min-w-0">
                <p className="text-sm font-medium text-ink sm:truncate">
                  Inspecting {focus.label} <span className="font-normal text-ink-3">· {fmtDate(focus.t)}, {fmtTime(focus.t)}</span>
                </p>
                <p className="text-xs text-ink-3">
                  {view.replay?.status === "playing" ? "Playing on from there: watch what happened next." : "The whole twin as it was then. Press play to see what happened next."}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {view.replay && Math.abs(Date.parse(view.replay.cursor) - focus.t) > 30_000 && (
                <button onClick={() => send({ type: "seek", to: iso(focus.t) })}
                  className="rounded-control border border-line bg-surface px-3 py-1.5 text-xs font-medium text-ink-2 hover:border-line-strong hover:text-ink">
                  Back to {fmtTime(focus.t)}
                </button>
              )}
              <button onClick={goLive}
                className="inline-flex items-center gap-1.5 rounded-control bg-primary px-3 py-1.5 text-xs font-medium text-white shadow-card hover:bg-primary-strong">
                <Radio aria-hidden size={13} /> Back to live
              </button>
              <button onClick={() => { setFocus(null); setUrl(null); }} aria-label="Dismiss"
                className="grid size-7 place-items-center rounded-md text-ink-3 hover:bg-surface hover:text-ink">
                <X size={14} />
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence initial={false}>
        {replaying && extent && win && (
          <motion.div key="replay-bar" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.3, ease: [0.2, 0.8, 0.2, 1] }} className="overflow-hidden">
            <ReplayBar extent={extent} window={win} speed={speed} progress={view.replay} ready={view.status === "live"}
              send={send} onWindow={changeWindow} onSpeed={setSpeed} marker={focus?.t} />
          </motion.div>
        )}
      </AnimatePresence>

      {!replaying && !s.streaming && view.status !== "not_found" && <motion.div variants={item}><NotStreaming patientId={patientId} lastSeen={device} now={now} /></motion.div>}

      <div className="grid grid-cols-12 gap-5">
        <motion.div variants={item} className="col-span-12 lg:col-span-5">
          <TwinFigure state={s} glucosePulse={view.pulse.glucose ?? 0} now={now} className="lg:sticky lg:top-24"
            pausedLabel={replaying ? (view.replay?.status === "ended" ? "Replay ended" : "Replay paused") : undefined} />
        </motion.div>

        <div className="col-span-12 space-y-5 lg:col-span-7">
          <motion.div variants={item}>
            <GlucoseHero glucose={s.glucose} points={view.series.glucose} now={now} pulse={view.pulse.glucose ?? 0} />
          </motion.div>
          <motion.div variants={item} className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <VitalCard icon={HeartPulse} label="Heart rate" hue={vital.heart} signal={s.heart_rate} unit="bpm"
              tone={statusTone("heart_rate", s.heart_rate.status)} now={now} pulse={view.pulse.heart_rate} />
            <VitalCard icon={Droplet} label="SpO₂" hue={vital.oxygen} signal={s.spo2} unit="%"
              tone={statusTone("spo2", s.spo2.status)} now={now} pulse={view.pulse.spo2} />
            <VitalCard icon={Wind} label="Breathing" hue={vital.oxygen} signal={s.respiration_rate} digits={1} unit="/min" now={now} />
            <VitalCard icon={Activity} label="Activity" hue={vital.activity} signal={s.activity} now={now} pulse={view.pulse.activity}
              text={s.activity.status ? statusLabel(s.activity.status) : null}
              footer={<span className="text-[11px] tabular-nums text-ink-2">{metsText(s.activity)}</span>} />
            {/* Some wearables (the CGMacros Fitbits) record no steps: show their energy expenditure instead. */}
            {s.steps_today.value != null || s.active_kcal.value == null ? (
              <VitalCard icon={Footprints} label="Steps today" hue={vital.activity} signal={s.steps_today} now={now} />
            ) : (
              <VitalCard icon={Flame} label="Active energy" hue={vital.activity} signal={s.active_kcal} digits={1} unit="kcal/min" now={now} />
            )}
            <VitalCard icon={Moon} label="Sleep" hue={vital.sleep} signal={s.sleep} now={now} pulse={view.pulse.sleep}
              text={s.sleep.status ? statusLabel(s.sleep.status) : null}
              footer={<span className="text-[11px] text-ink-2">{isAsleep(s.sleep.status) && s.sleep.until ? `until ${fmtTime(s.sleep.until)}` : s.sleep.time ? `since ${fmtTime(s.sleep.time)}` : ""}</span>} />
          </motion.div>
        </div>

        <div className="col-span-12 space-y-5 xl:col-span-8">
          <motion.div variants={item}>
            <ChartCard
              title="Glucose"
              icon={<Droplet aria-hidden size={14} strokeWidth={2.4} style={{ color: vital.glucose }} />}
              meta="mg/dL · target 70–180"
              live={s.streaming}
              spec={{
                points: view.series.glucose,
                color: vital.glucose,
                unit: "mg/dL",
                target: [GLUCOSE_LIMITS.low, GLUCOSE_LIMITS.high],
                thresholds: [GLUCOSE_LIMITS.veryLow, GLUCOSE_LIMITS.low, GLUCOSE_LIMITS.high, GLUCOSE_LIMITS.veryHigh],
                floor: [60, 200],
                glucose: true,
                flag: (v) => {
                  const b = glucoseBand(v);
                  return b === "in_range" ? null : band[b];
                },
              }}
              height={220}
              inspect={chartInspect("a glucose reading", "glucose")}
            />
          </motion.div>
          <motion.div variants={item}>
            <ChartCard
              title="Heart rate"
              icon={<HeartPulse aria-hidden size={14} strokeWidth={2.4} style={{ color: vital.heart }} />}
              meta="beats per minute"
              live={s.streaming}
              spec={{ points: view.series.heart_rate, color: vital.heart, unit: "bpm", floor: [55, 100], gapMin: 10,
                flag: (v) => (heartRateBand(v) === "normal" ? null : tone.warn), flagLabel: (v) => statusLabel(heartRateBand(v)) }}
              height={170}
              inspect={chartInspect("a heart-rate reading", "heart_rate")}
            />
          </motion.div>
        </div>
        <motion.div variants={item} className="col-span-12 xl:col-span-4">
          <TransitionFeed items={view.feed} className="h-full" onInspect={extent ? inspectFeed : undefined} activeId={replaying ? focus?.id : null} />
        </motion.div>
      </div>

      <motion.div variants={item}>
        <MoreSignals state={s} now={now} />
      </motion.div>
    </motion.div>
  );
}

function ReplayBadge({ status, connected, speed }: { status: string | null; connected: boolean; speed: number }) {
  const playing = status === "playing";
  return (
    <span role="status" className={cn("inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium",
      playing ? "border-primary/20 bg-primary-soft text-primary-strong" : "border-line bg-surface text-ink-2")}>
      <History size={13} className={cn(playing && "animate-spin [animation-direction:reverse] [animation-duration:3s]")} />
      {!connected ? "Loading replay…" : playing ? `Replaying · ${speed}×` : status === "ended" ? "Replay ended" : "Replay paused"}
    </span>
  );
}

/** The reading nearest `t` (within `tolerance`), or null. Points are sorted by time. */
function nearestPoint(points: Point[], t: number, tolerance = 15 * 60_000): Point | null {
  let best: Point | null = null;
  for (const p of points) {
    if (Math.abs(p.t - t) <= tolerance && (!best || Math.abs(p.t - t) < Math.abs(best.t - t))) best = p;
    if (p.t > t + tolerance) break;
  }
  return best;
}

/** In a pinned chart moment: the other vital then, and the status changes around it. */
function MomentSummary({ t, series, feed, exclude }: {
  t: number;
  series: Record<"glucose" | "heart_rate", Point[]>;
  feed: FeedItem[];
  exclude: "glucose" | "heart_rate";
}) {
  const g = exclude === "glucose" ? null : nearestPoint(series.glucose, t);
  const hr = exclude === "heart_rate" ? null : nearestPoint(series.heart_rate, t);
  const near = feed.filter((f) => Math.abs(Date.parse(f.time) - t) <= 20 * 60_000).slice(0, 3);
  return (
    <div className="space-y-1.5 text-xs">
      {g && (
        <div className="flex items-center justify-between gap-2">
          <span className="inline-flex items-center gap-1.5 text-ink-2"><Droplet aria-hidden size={12} style={{ color: vital.glucose }} /> Glucose</span>
          <span className="inline-flex items-center gap-1.5 tabular-nums font-medium text-ink">{fmtNumber(g.v)} <BandChip status={glucoseBand(g.v)} size="sm" /></span>
        </div>
      )}
      {hr && (
        <div className="flex items-center justify-between gap-2">
          <span className="inline-flex items-center gap-1.5 text-ink-2"><HeartPulse aria-hidden size={12} style={{ color: vital.heart }} /> Heart rate</span>
          <span className="inline-flex items-center gap-1.5 tabular-nums font-medium text-ink">
            {fmtNumber(hr.v)} bpm <StatusChip status={heartRateBand(hr.v)} tone={statusTone("heart_rate", heartRateBand(hr.v))} />
          </span>
        </div>
      )}
      {!g && !hr && exclude && <p className="text-ink-3">No other readings close to this moment.</p>}
      {near.length > 0 && (
        <ul className="space-y-1 border-t border-line pt-1.5">
          {near.map((f) => (
            <li key={f.id} className="flex items-center justify-between gap-2 text-ink-2">
              <span className="inline-flex min-w-0 items-center gap-1.5 truncate">
                <span aria-hidden className="size-1.5 shrink-0 rounded-full"
                  style={{ background: isAbnormal(f.signal, f.to) ? (f.signal === "glucose" && isBand(f.to) ? band[f.to] : tone.warn) : "var(--line-strong)" }} />
                {SIGNAL_LABEL[f.signal]} → {statusLabel(f.to)}
              </span>
              <span className="shrink-0 tabular-nums text-ink-3">{fmtTime(f.time)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function metsText(a: Signal): string {
  if (a.value == null) return "";
  return a.unit === "{MET}" ? `${fmtNumber(a.value as number, 1)} MET` : `level ${fmtNumber(a.value as number)}`;
}

function MoreSignals({ state, now }: { state: TwinState; now: number | null }) {
  const items = [
    { icon: Waves, label: "HRV", s: state.hrv_rmssd, unit: "ms", digits: 0, hue: vital.heart },
    { icon: Thermometer, label: "Skin temp", s: state.skin_temp, unit: "°C", digits: 1, hue: "var(--ink-2)" },
    { icon: Brain, label: "Stress", s: state.stress, unit: "", digits: 0, hue: "var(--ink-2)" },
    { icon: Zap, label: "EDA", s: state.eda, unit: "µS", digits: 2, hue: "var(--ink-2)" },
    // shown in the vitals grid instead when there are no steps
    ...(state.steps_today.value != null ? [{ icon: Flame, label: "Active energy", s: state.active_kcal, unit: "kcal/min", digits: 1, hue: vital.activity }] : []),
  ].filter((i) => i.s.value != null);
  if (!items.length) return null;
  return (
    <section aria-label="More signals" className="flex flex-wrap items-center gap-2">
      <span className="label mr-1">More signals</span>
      {items.map(({ icon: Icon, label, s, unit, digits, hue }) => (
        <span key={label} className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1.5 text-xs shadow-card" title={s.source ?? undefined}>
          <Icon aria-hidden size={13} style={{ color: hue }} />
          <span className="text-ink-2">{label}</span>
          <span className="font-semibold tabular-nums text-ink">
            {fmtNumber(s.value as number, digits)}
            {unit && <span className="ml-0.5 font-normal text-ink-3">{unit}</span>}
          </span>
          <span className="text-ink-3">{now ? fmtAge(s.time, now) : ""}</span>
        </span>
      ))}
    </section>
  );
}

function NotStreaming({ patientId, lastSeen, now }: { patientId: string; lastSeen: string | null; now: number | null }) {
  const [copied, setCopied] = useState(false);
  const cmd = `scripts/stream.sh --patient ${patientId} --from-now`;
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-line bg-surface px-5 py-4 shadow-card">
      <div className="min-w-0">
        <p className="text-sm font-medium text-ink">Devices aren&apos;t streaming for this patient</p>
        <p className="mt-0.5 text-xs text-ink-3">
          Showing the last known state{lastSeen && now ? ` from ${fmtAge(lastSeen, now)}` : ""}. Start the simulator to see the twin live.
        </p>
      </div>
      <button
        onClick={() => {
          void navigator.clipboard?.writeText(cmd);
          setCopied(true);
          setTimeout(() => setCopied(false), 1600);
        }}
        className={cn(
          "group inline-flex max-w-full items-center gap-2 rounded-control border border-line bg-surface-2 px-3 py-2 font-mono text-xs text-ink-2 transition-colors hover:border-line-strong",
        )}
      >
        <Terminal aria-hidden size={13} className="shrink-0 text-ink-3" />
        <span className="truncate">{cmd}</span>
        {copied ? <Check aria-hidden size={13} className="shrink-0 text-primary" /> : <Copy aria-hidden size={13} className="shrink-0 text-ink-3 group-hover:text-ink-2" />}
        <span className="sr-only">{copied ? "Copied" : "Copy command"}</span>
      </button>
    </div>
  );
}
