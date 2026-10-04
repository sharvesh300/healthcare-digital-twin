"use client";

import { CalendarClock, Pause, Play, RotateCcw } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";

import type { ReplayProgress } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { fmtDate, fmtSpan, fmtTime, fromZonedInput, toZonedInput } from "@/lib/twin/format";
import type { ReplayCommand } from "@/lib/twin/use-twin-stream";

export const SPEEDS = [30, 60, 120, 300, 600] as const;
const HOUR = 3600_000;

export interface ReplayWindow {
  start: number;
  end: number;
}

/** Latest moment a replay can reach: the end of the recording, or now if it runs past now. */
export const replayLimit = (w: ReplayWindow) => Math.min(w.end, Date.now());

function lastNight(limit: number, earliest: number): ReplayWindow {
  const day = toZonedInput(limit).slice(0, 10);
  let end = fromZonedInput(`${day}T07:00`)!;
  if (end > limit) end -= 24 * HOUR;
  return { start: Math.max(earliest, end - 9 * HOUR), end };
}

/** Pick the window, then play: presets, From/To in clinic time, play/pause, scrubber, speed. */
export function ReplayBar({ recording, window: win, speed, progress, ready, send, onWindow, onSpeed }: {
  recording: ReplayWindow;
  window: ReplayWindow;
  speed: number;
  progress: ReplayProgress | null;
  ready: boolean;
  send: (c: ReplayCommand) => void;
  onWindow: (w: ReplayWindow) => void;
  onSpeed: (s: number) => void;
}) {
  const [drag, setDrag] = useState<number | null>(null);
  const limit = replayLimit(recording);
  const playing = progress?.status === "playing";
  const ended = progress?.status === "ended";
  const cursor = drag ?? (progress ? Date.parse(progress.cursor) : win.start);
  const pct = ((cursor - win.start) / (win.end - win.start)) * 100;

  const presets: { label: string; w: () => ReplayWindow }[] = [
    { label: "Last 3 h", w: () => ({ start: Math.max(recording.start, limit - 3 * HOUR), end: limit }) },
    { label: "Last 6 h", w: () => ({ start: Math.max(recording.start, limit - 6 * HOUR), end: limit }) },
    { label: "Last 24 h", w: () => ({ start: Math.max(recording.start, limit - 24 * HOUR), end: limit }) },
    { label: "Last night", w: () => lastNight(limit, recording.start) },
  ];
  const isPreset = (w: ReplayWindow) => Math.abs(w.start - win.start) < 60_000 && Math.abs(w.end - win.end) < 60_000;

  const setFrom = (value: string) => {
    const t = fromZonedInput(value);
    if (t != null && t < win.end) onWindow({ start: Math.max(recording.start, t), end: win.end });
  };
  const setTo = (value: string) => {
    const t = fromZonedInput(value);
    if (t != null && t > win.start) onWindow({ start: win.start, end: Math.min(limit, t) });
  };
  const commitSeek = (t: number) => {
    setDrag(null);
    send({ type: "seek", to: new Date(t).toISOString() });
  };

  return (
    <motion.section
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.2, 0.8, 0.2, 1] }}
      aria-label="Replay controls"
      className="rounded-card border border-line bg-surface p-4 shadow-card sm:p-5"
    >
      {/* window: presets and From / To */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <div className="flex flex-wrap gap-1.5">
          {presets.map(({ label, w }) => {
            const active = isPreset(w());
            return (
              <button key={label} onClick={() => onWindow(w())}
                className={cn("rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                  active ? "border-primary/30 bg-primary-soft text-primary-strong" : "border-line bg-surface text-ink-2 hover:border-line-strong hover:text-ink")}>
                {label}
              </button>
            );
          })}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-ink-3">
          <CalendarClock size={14} aria-hidden />
          <label className="flex items-center gap-1.5">
            From
            <input type="datetime-local" value={toZonedInput(win.start)} min={toZonedInput(recording.start)} max={toZonedInput(win.end)}
              onChange={(e) => setFrom(e.target.value)}
              className="h-8 rounded-control border border-line bg-surface px-2 font-mono text-xs text-ink tabular-nums focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/15" />
          </label>
          <label className="flex items-center gap-1.5">
            To
            <input type="datetime-local" value={toZonedInput(win.end)} min={toZonedInput(win.start)} max={toZonedInput(limit)}
              onChange={(e) => setTo(e.target.value)}
              className="h-8 rounded-control border border-line bg-surface px-2 font-mono text-xs text-ink tabular-nums focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/15" />
          </label>
          <span className="tabular-nums">{fmtSpan(win.end - win.start)}</span>
        </div>
      </div>

      {/* transport: play / pause, scrubber, speed */}
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-3">
        <motion.button
          whileTap={{ scale: 0.94 }}
          onClick={() => send({ type: playing ? "pause" : "play" })}
          disabled={!ready}
          aria-label={playing ? "Pause replay" : ended ? "Replay again" : "Play replay"}
          className="grid size-11 shrink-0 place-items-center rounded-full bg-primary text-white shadow-card transition-colors hover:bg-primary-strong disabled:cursor-wait disabled:opacity-60"
        >
          {playing ? <Pause size={18} fill="currentColor" /> : ended ? <RotateCcw size={18} /> : <Play size={18} fill="currentColor" className="ml-0.5" />}
        </motion.button>

        <div className="min-w-[220px] flex-1">
          <div className="mb-1.5 flex items-baseline justify-between text-[11px] tabular-nums text-ink-3">
            <span>{fmtDate(win.start)} {fmtTime(win.start)}</span>
            <span className="text-sm font-semibold text-ink">{fmtTime(cursor)}<span className="ml-1 text-[11px] font-normal text-ink-3">{fmtDate(cursor)}</span></span>
            <span>{fmtDate(win.end)} {fmtTime(win.end)}</span>
          </div>
          <div className="relative h-5">
            <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-surface-2" />
            <div className="absolute left-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-primary transition-[width] duration-200 ease-linear"
              style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
            <input
              type="range"
              aria-label="Replay position"
              min={win.start}
              max={win.end}
              step={60_000}
              value={cursor}
              disabled={!ready}
              onChange={(e) => setDrag(Number(e.target.value))}
              onPointerUp={(e) => commitSeek(Number((e.target as HTMLInputElement).value))}
              onKeyUp={(e) => commitSeek(Number((e.target as HTMLInputElement).value))}
              className="absolute inset-0 h-5 w-full cursor-pointer appearance-none bg-transparent
                [&::-webkit-slider-thumb]:size-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full
                [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-white [&::-webkit-slider-thumb]:bg-primary [&::-webkit-slider-thumb]:shadow
                [&::-moz-range-thumb]:size-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-white [&::-moz-range-thumb]:bg-primary"
            />
          </div>
        </div>

        <div role="radiogroup" aria-label="Replay speed" className="flex rounded-control border border-line bg-surface-2 p-0.5">
          {SPEEDS.map((s) => (
            <button key={s} role="radio" aria-checked={speed === s}
              onClick={() => {
                onSpeed(s);
                send({ type: "speed", value: s });
              }}
              className={cn("relative rounded-[8px] px-2.5 py-1 text-xs font-medium tabular-nums transition-colors", speed === s ? "text-ink" : "text-ink-3 hover:text-ink-2")}>
              {speed === s && <motion.span layoutId="replay-speed" className="absolute inset-0 rounded-[8px] bg-surface shadow-card" transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
              <span className="relative">{s}×</span>
            </button>
          ))}
        </div>
      </div>
      <p className="mt-3 text-[11px] text-ink-3">
        {speed}× plays {fmtSpan(speed * 60_000)} of the recording per minute · the whole window takes {fmtSpan((win.end - win.start) / speed)}.
        The replay uses the recorded data and the twin&apos;s live rules; streamed readings are not included.
      </p>
    </motion.section>
  );
}
