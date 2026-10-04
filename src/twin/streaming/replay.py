"""Replay a patient's recorded data through the twin's own state rules.

The live twin folds device readings into a `PatientTwinState` as they arrive. A replay does
the same over a recorded window, on a virtual clock the viewer controls (play, pause, seek,
speed). It speaks the live WebSocket protocol (`snapshot`, then `delta`s with sequential
versions and transitions), so the dashboard renders a replay with the same components.

Pure: the engine is given the readings (twin.streaming.store.SqlStateLoader.recorded) and
returns JSON-ready messages; the WebSocket loop lives in twin.api.patients.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from twin.streaming.state import RULES, PatientTwinState, Reading, Rules, apply_readings, delta

# Readings before the window that are folded in first, so the state at `start` already has
# its latest values, glucose trend, today's steps and the current sleep stage, and the charts
# have context.
WARMUP = timedelta(hours=24)
FEED_SIZE = 40
CHART_METRICS = ("glucose", "heart_rate")
MIN_SPEED, MAX_SPEED = 1.0, 3600.0

Status = Literal["playing", "paused", "ended"]


def _iso(t: datetime, rules: Rules) -> str:
    return t.astimezone(rules.tz).isoformat()


class ReplayEngine:
    def __init__(self, patient_id: UUID, readings: list[Reading], start: datetime, end: datetime,
                 speed: float = 120.0, rules: Rules = RULES):
        if end <= start:
            raise ValueError("end must be after start")
        self.patient_id, self.start, self.end, self.rules = patient_id, start, end, rules
        self.readings = sorted(readings, key=lambda r: (r.time, r.metric != "sleep"))
        self.times = [r.time for r in self.readings]
        self.speed = speed
        self.playing = False
        self.version = -1
        self.cursor = start
        self.index = 0
        self.state = PatientTwinState(patient_id)

    @property
    def status(self) -> Status:
        if self.playing:
            return "playing"
        return "ended" if self.cursor >= self.end else "paused"

    def set_speed(self, speed: float) -> None:
        self.speed = min(max(float(speed), MIN_SPEED), MAX_SPEED)

    # ── messages ─────────────────────────────────────────────────────

    def progress(self) -> dict[str, Any]:
        return {"type": "replay", "status": self.status, "cursor": _iso(self.cursor, self.rules),
                "start": _iso(self.start, self.rules), "end": _iso(self.end, self.rules), "speed": self.speed}

    def seek(self, t: datetime) -> dict[str, Any]:
        """Rebuild the state as of `t` (clamped to the window) and return a snapshot that also
        carries the chart series and the recent transitions up to `t`."""
        t = min(max(t, self.start), self.end)
        self.index = bisect_right(self.times, t)
        history = self.readings[:self.index]
        folded = apply_readings(PatientTwinState(self.patient_id), history, self.rules, now=t)
        state = folded.state if folded else PatientTwinState(self.patient_id)
        self.version += 1
        self.cursor = t
        self.state = replace(state, version=self.version, as_of=t, streaming=self.playing, clock=None)
        feed = [x.to_dict(self.rules.tz) for x in reversed(folded.transitions[-FEED_SIZE:])] if folded else []
        since = t - WARMUP
        series = {m: [[_iso(r.time, self.rules), round(float(r.value), 3)] for r in history
                      if r.metric == m and r.time >= since] for m in CHART_METRICS}
        return {"type": "snapshot", "version": self.version, "state": self.state.to_dict(self.rules.tz),
                "series": series, "feed": feed, "replay": self.progress()}

    def play(self) -> list[dict[str, Any]]:
        """Start the clock. The state's `streaming` flag follows, so the figure's loops run
        while playing. Playing from the end restarts the window (a fresh snapshot)."""
        self.playing = True
        if self.cursor >= self.end:
            return [self.seek(self.start)]
        return self._streaming(True)

    def pause(self) -> list[dict[str, Any]]:
        self.playing = False
        return self._streaming(False)

    def _streaming(self, on: bool) -> list[dict[str, Any]]:
        message = self._commit(replace(self.state, streaming=on), [], self.cursor)
        return [message] if message else []

    def advance(self, to: datetime) -> list[dict[str, Any]]:
        """Move the clock to `to` (at most the end), folding in the readings on the way.
        Returns at most one delta message; at the end the replay pauses itself."""
        to = min(to, self.end)
        if to <= self.cursor:
            return []
        j = bisect_right(self.times, to, lo=self.index)
        batch = self.readings[self.index:j]
        self.index = j
        self.cursor = to
        change = apply_readings(self.state, batch, self.rules, now=to)
        new = change.state if change else self.state
        found = list(change.transitions) if change else []
        if to >= self.end:
            self.playing = False
            new = replace(new, streaming=False)
        message = self._commit(new, found, to)
        return [message] if message else []

    def _commit(self, new: PatientTwinState, found: list, at: datetime) -> dict[str, Any] | None:
        change = delta(self.state, new, found, at, self.rules.tz)
        if change is None:
            self.state = replace(new, version=self.state.version)
            return None
        self.version += 1
        self.state = replace(change.state, version=self.version, as_of=at)
        return {"type": "delta", "patient_id": str(self.patient_id), "version": self.version,
                "time": _iso(at, self.rules), "changes": change.changes,
                "transitions": [x.to_dict(self.rules.tz) for x in change.transitions]}
