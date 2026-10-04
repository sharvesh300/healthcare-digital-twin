"""PatientTwinStateManager: keeps each patient's live twin state, applies new readings,
records status transitions and publishes every change on the event bus.

    ingestion ──handle(readings)──▶ apply ──▶ update ──▶ publish ──▶ bus ──▶ WebSocket
                                      ▲
    report.twin_latest ──load()───────┘   (on first use, and after eviction)

State is derived from TimescaleDB and rebuilt by `load()`, so it is safe to lose: it is
cached in memory only. All changes to one patient run under that patient's lock, so the
versions a client sees are strictly sequential.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from twin.streaming.bus import InProcessBus, Subscription
from twin.streaming.state import (
    RULES,
    Clock,
    PatientTwinState,
    Reading,
    Rules,
    StateDelta,
    Transition,
    apply_readings,
    delta,
    mark_stale,
    transitions,
)

log = logging.getLogger(__name__)


class UnknownPatient(LookupError):
    pass


class StateLoader(Protocol):
    async def patient(self, patient_id: UUID) -> dict[str, Any] | None:
        """Identity and demographics, or None if there is no such patient."""

    async def readings(self, patient_id: UUID) -> list[Reading]:
        """What the state is rebuilt from: the latest reading per metric, the glucose
        readings in the trend window, and today's steps."""

    async def series(self, patient_id: UUID, metrics: Sequence[str], since: datetime,
                     until: datetime) -> dict[str, list[tuple[datetime, float]]]:
        """Chart points per metric (live readings plus the recorded history before them)."""

    async def recorded(self, patient_id: UUID, since: datetime, until: datetime) -> list[Reading]:
        """The recorded (non-live) readings in a window, for a replay."""


class TransitionStore(Protocol):
    async def save(self, patient_id: UUID, items: Sequence[Transition], version: int) -> None: ...

    async def history(self, patient_id: UUID, since: datetime | None, signal: str | None,
                      limit: int) -> list[dict[str, Any]]: ...


class PatientTwinStateManager:
    def __init__(self, loader: StateLoader, store: TransitionStore, bus: InProcessBus, rules: Rules = RULES,
                 stream_idle: timedelta = timedelta(seconds=60), evict_after: timedelta = timedelta(minutes=10),
                 wall_clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.loader, self.store, self.bus, self.rules = loader, store, bus, rules
        self.stream_idle, self.evict_after = stream_idle, evict_after
        self._now = wall_clock
        self._states: dict[UUID, PatientTwinState] = {}
        self._touched: dict[UUID, datetime] = {}
        self._locks: defaultdict[UUID, asyncio.Lock] = defaultdict(asyncio.Lock)

    @staticmethod
    def topic(patient_id: UUID) -> str:
        return f"patient:{patient_id}"

    # ── load / read ──────────────────────────────────────────────────

    async def patient(self, patient_id: UUID) -> dict[str, Any]:
        info = await self.loader.patient(patient_id)
        if info is None:
            raise UnknownPatient(patient_id)
        return info

    async def load(self, patient_id: UUID) -> PatientTwinState:
        """(Re)build the patient's state from the database and cache it. Version restarts at 0."""
        await self.patient(patient_id)
        readings = await self.loader.readings(patient_id)
        wall = self._now()
        latest = max((r.time for r in readings), default=wall)
        empty = PatientTwinState(patient_id, clock=Clock(max(wall, latest), wall))
        loaded = apply_readings(empty, readings, self.rules, now=wall)
        state = replace(loaded.state if loaded else empty, version=0, as_of=wall)
        self._states[patient_id] = state
        self._touched[patient_id] = wall
        return state

    async def _get(self, patient_id: UUID) -> PatientTwinState:
        self._touched[patient_id] = self._now()
        return self._states.get(patient_id) or await self.load(patient_id)

    async def get(self, patient_id: UUID) -> PatientTwinState:
        async with self._locks[patient_id]:
            return await self._get(patient_id)

    async def snapshot(self, patient_id: UUID) -> dict[str, Any]:
        return (await self.get(patient_id)).to_dict(self.rules.tz)

    def cached(self, patient_id: UUID) -> PatientTwinState | None:
        """The state if it is loaded; never touches the database."""
        return self._states.get(patient_id)

    def version(self, patient_id: UUID) -> int | None:
        state = self._states.get(patient_id)
        return state.version if state else None

    def subscribe(self, patient_id: UUID) -> AbstractAsyncContextManager[Subscription]:
        return self.bus.subscribe(self.topic(patient_id))

    # ── apply / update / publish ─────────────────────────────────────

    def apply(self, state: PatientTwinState, readings: list[Reading], now: datetime | None = None) -> StateDelta | None:
        """Pure: what the readings change (see twin.streaming.state.apply_readings)."""
        return apply_readings(state, readings, self.rules, now)

    async def update(self, patient_id: UUID, change: StateDelta) -> PatientTwinState:
        """Commit a delta: bump the version, record its transitions, cache the new state."""
        old = self._states[patient_id]
        state = replace(change.state, version=old.version + 1, as_of=self._now())
        if change.transitions:
            await self.store.save(patient_id, change.transitions, state.version)
        self._states[patient_id] = state
        return state

    async def publish(self, patient_id: UUID, state: PatientTwinState, change: StateDelta) -> None:
        tz = self.rules.tz
        await self.bus.publish(self.topic(patient_id), {
            "type": "delta", "patient_id": str(patient_id), "version": state.version,
            "time": change.time.astimezone(tz).isoformat() if change.time else None,
            "changes": change.changes, "transitions": [t.to_dict(tz) for t in change.transitions],
        })

    async def handle(self, patient_id: UUID, readings: list[Reading], wall: datetime | None = None) -> StateDelta | None:
        """New readings from ingestion (already stored): apply -> update -> publish.
        One batch becomes at most one published delta."""
        if not readings:
            return None
        async with self._locks[patient_id]:
            wall = wall or self._now()
            if patient_id not in self._states:
                # Loading reads the database, which already holds these readings: applying
                # them again would count steps twice. No one has seen an earlier version.
                state = await self._get(patient_id)
                self._states[patient_id] = replace(state, streaming=True, clock=state.clock.observe(
                    max(r.time for r in readings), wall))
                return None
            state = await self._get(patient_id)
            clocked = replace(state, streaming=True,
                              clock=state.clock.observe(max(r.time for r in readings), wall))
            applied = self.apply(clocked, readings)
            change = delta(state, applied.state if applied else clocked,
                           list(applied.transitions) if applied else [], max(r.time for r in readings), self.rules.tz)
            if change is None:  # nothing visible changed; keep the advanced clock
                self._states[patient_id] = replace(state, clock=clocked.clock)
                return None
            new = await self.update(patient_id, change)
            await self.publish(patient_id, new, change)
            return change

    # ── background ───────────────────────────────────────────────────

    async def tick(self) -> None:
        """Staleness and stream-idle checks for every cached patient; evict idle states."""
        wall = self._now()
        for patient_id in list(self._states):
            async with self._locks[patient_id]:
                state = self._states.get(patient_id)
                if state is None or state.clock is None:
                    continue
                at = state.clock.now(wall)
                new = mark_stale(state, at, self.rules)
                if new.streaming and wall - state.clock.wall > self.stream_idle:
                    new = replace(new, streaming=False)
                change = delta(state, new, transitions(state, new, at), at, self.rules.tz)
                if change is not None:
                    state = await self.update(patient_id, change)
                    await self.publish(patient_id, state, change)
                elif (not self.bus.subscribers(self.topic(patient_id))
                      and wall - self._touched.get(patient_id, wall) > self.evict_after):
                    del self._states[patient_id]
                    self._touched.pop(patient_id, None)

    async def run(self, interval: float = 5.0) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await self.tick()
            except Exception:  # e.g. the database briefly unavailable: keep ticking
                log.exception("twin state tick failed")
