"""`simulate-stream`: act as each patient's sensor devices and stream readings to the API.

For every patient the simulator pairs a live CGM and a live wearable
(POST /patients/{id}/devices), then replays the patient's own recording as if it were
happening now:

    device time = start of the run + (recorded time - first recorded time)

advancing `speed` times faster than the wall clock (--speed 1 is real time). Readings are
POSTed to /ingest/events in batches, one batch per patient per tick. Sources: the fused CGM
stream (one calibrated value every 5 min), the wearable samples and the sleep stages of the
patient's recorded devices (beat-level ibi_ms and wear_minutes are left out).

Knobs to exercise the twin: --jitter adds noise to glucose and heart rate, --drop-rate loses
readings (the twin marks signals stale), --late-rate holds readings back to the next batch
(out of order, like a CGM backfill), --loop restarts the recording when it ends.

Twin time is shifted so that most recordings span the present. --from-now starts each
recording at the current moment instead of its beginning, so at --speed 1 the device times
are exactly the recorded twin times: the stream continues the patient's history.
"""

from __future__ import annotations

import asyncio
import random
import time as clock
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select

from twin.db import session_scope
from twin.models import (
    Device,
    DeviceModel,
    GlucoseFused,
    Patient,
    PatientTag,
    SleepSegment,
    Tag,
    WearableMetric,
    WearableSample,
)

SKIP_METRICS = ("ibi_ms", "wear_minutes")
LOOP_GAP = timedelta(minutes=5)
BATCH = 500


@dataclass(frozen=True)
class Recorded:
    time: datetime  # twin time of the recording
    kind: str  # glucose | wearable | sleep
    value: float | str
    metric: str | None = None
    until: datetime | None = None


async def recording(patient_id: UUID, metrics: list[str] | None = None) -> list[Recorded]:
    """The patient's recorded data, in time order (sleep first within a timestamp)."""
    recorded_device = (select(Device.device_id).join(DeviceModel, DeviceModel.model_id == Device.model_id)
                       .where(Device.patient_id == patient_id, DeviceModel.is_live_simulator.is_(False)))
    async with session_scope() as s:
        glucose = (await s.execute(select(GlucoseFused.time, GlucoseFused.glucose_mg_dl)
                                   .where(GlucoseFused.patient_id == patient_id))).all()
        q = (select(WearableSample.time, WearableMetric.code, WearableSample.value)
             .join(WearableMetric, WearableMetric.metric_id == WearableSample.metric_id)
             .where(WearableSample.device_id.in_(recorded_device), WearableMetric.code.not_in(SKIP_METRICS)))
        if metrics:
            q = q.where(WearableMetric.code.in_(metrics))
        wearable = (await s.execute(q)).all()
        sleep = (await s.execute(select(SleepSegment.start_time, SleepSegment.end_time, SleepSegment.stage)
                                 .where(SleepSegment.device_id.in_(recorded_device)))).all()
    items = ([Recorded(t, "glucose", float(g)) for t, g in glucose]
             + [Recorded(t, "wearable", float(val), metric=code) for t, code, val in wearable]
             + [Recorded(a, "sleep", str(stage), until=b) for a, b, stage in sleep])
    items.sort(key=lambda r: (r.time, r.kind != "sleep"))
    return items


class Playback:
    """One patient's recording on the simulated device clock."""

    def __init__(self, items: list[Recorded], anchor: datetime, devices: dict[str, int], *, loop: bool = False,
                 jitter: float = 0.0, drop_rate: float = 0.0, late_rate: float = 0.0,
                 rng: random.Random | None = None, t0: datetime | None = None):
        self.items, self.devices, self.loop = items, devices, loop
        self.jitter, self.drop_rate, self.late_rate = jitter, drop_rate, late_rate
        self.rng = rng or random.Random()
        self.t0 = t0 or (items[0].time if items else anchor)  # recorded time that plays at `anchor`
        self.anchor = anchor
        self.cycle = timedelta(0)  # added per loop
        self.i = 0
        self.held: list[dict[str, Any]] = []

    @property
    def done(self) -> bool:
        return self.i >= len(self.items) and not self.held and not self.loop

    def device_time(self, item: Recorded) -> datetime:
        return self.anchor + (item.time - self.t0) + self.cycle

    def due(self, device_now: datetime) -> list[dict[str, Any]]:
        """Events with device time <= device_now, plus the ones held back last time (late)."""
        out, self.held = self.held, []
        while self.items:
            if self.i >= len(self.items):
                if not self.loop:
                    break
                self.cycle += self.items[-1].time - self.t0 + LOOP_GAP
                self.i = 0
            item = self.items[self.i]
            at = self.device_time(item)
            if at > device_now:
                break
            self.i += 1
            event = self.event(item, at)
            if event is None or self.rng.random() < self.drop_rate:
                continue
            if self.rng.random() < self.late_rate:
                self.held.append(event)
            else:
                out.append(event)
        return out

    def _noisy(self, value: float) -> float:
        return value * (1 + self.rng.gauss(0, self.jitter)) if self.jitter else value

    def event(self, item: Recorded, at: datetime) -> dict[str, Any] | None:
        if item.kind == "glucose":
            if "cgm" not in self.devices:
                return None
            value = min(max(round(self._noisy(float(item.value))), 20), 600)
            return {"kind": "glucose", "device_id": self.devices["cgm"], "time": at.isoformat(), "glucose_mg_dl": value}
        if "wearable" not in self.devices:
            return None
        if item.kind == "sleep":
            return {"kind": "sleep", "device_id": self.devices["wearable"], "time": at.isoformat(),
                    "stage": item.value, "until": (at + (item.until - item.time)).isoformat()}
        value = float(item.value)
        if item.metric == "heart_rate":
            value = round(self._noisy(value), 1)
        return {"kind": "wearable", "device_id": self.devices["wearable"], "time": at.isoformat(),
                "metric": item.metric, "value": value}


async def _patients(ids: list[UUID], tag: str | None) -> list[UUID]:
    if ids:
        return ids
    async with session_scope() as s:
        return list(await s.scalars(
            select(Patient.patient_id).join(PatientTag, PatientTag.patient_id == Patient.patient_id)
            .join(Tag, Tag.tag_id == PatientTag.tag_id).where(Tag.code == (tag or "composite-patient"))
            .order_by(Patient.source_subject_id)))


async def _post(client: httpx.AsyncClient, path: str, body: dict, tries: int = 5) -> dict:
    for attempt in range(tries):
        try:
            response = await client.post(path, json=body)
            if response.status_code < 500:
                response.raise_for_status()
                return response.json()
        except httpx.TransportError:
            if attempt == tries - 1:
                raise
        await asyncio.sleep(min(2 ** attempt * 0.5, 8))
    raise RuntimeError(f"POST {path} failed after {tries} tries")


async def run_stream(api: str, patient_ids: list[UUID], tag: str | None = None, *, speed: float = 60.0,
                     tick: float = 1.0, loop: bool = False, jitter: float = 0.0, drop_rate: float = 0.0,
                     late_rate: float = 0.0, skip_hours: float = 0.0, from_now: bool = False,
                     duration: float | None = None,
                     metrics: list[str] | None = None, seed: int | None = None, log: Callable = print) -> dict:
    rng = random.Random(seed)
    totals = {"sent": 0, "accepted": 0, "duplicates": 0, "rejected": 0}
    async with httpx.AsyncClient(base_url=api, timeout=60) as client:
        anchor = datetime.now(UTC)
        players: list[tuple[UUID, Playback]] = []
        for pid in await _patients(patient_ids, tag):
            items = await recording(pid, metrics)
            t0 = None
            if from_now and items and items[0].time <= anchor <= items[-1].time:
                t0 = anchor
                items = [r for r in items if r.time >= anchor]
            elif from_now and items:
                log(f"{pid}: recording does not span the present; starting at its beginning")
            if skip_hours and items:
                start = (t0 or items[0].time) + timedelta(hours=skip_hours)
                items = [r for r in items if r.time >= start]
                t0 = start if t0 else None
            if not items:
                log(f"{pid}: no recorded sensor data; skipped")
                continue
            devices = {}
            for kind, needed in (("cgm", any(r.kind == "glucose" for r in items)),
                                 ("wearable", any(r.kind != "glucose" for r in items))):
                if needed:
                    devices[kind] = (await _post(client, f"/patients/{pid}/devices", {"kind": kind}))["device_id"]
            players.append((pid, Playback(items, anchor, devices, loop=loop, jitter=jitter, drop_rate=drop_rate,
                                          late_rate=late_rate, rng=random.Random(rng.random()), t0=t0)))
            log(f"{pid}: {len(items)} readings from {items[0].time:%Y-%m-%d %H:%M} to {items[-1].time:%Y-%m-%d %H:%M}, "
                f"devices {devices}")
        if not players:
            log("nothing to stream")
            return totals
        log(f"streaming {len(players)} patients at {speed:g}x to {api}  (Ctrl-C to stop)")

        async def send(pid: UUID, events: list[dict]) -> None:
            for start in range(0, len(events), BATCH):
                chunk = events[start:start + BATCH]
                result = await _post(client, "/ingest/events", {"events": chunk})
                totals["sent"] += len(chunk)
                for key in ("accepted", "duplicates"):
                    totals[key] += result[key]
                totals["rejected"] += len(result["rejected"])
                if result["rejected"]:
                    log(f"{pid}: {len(result['rejected'])} rejected, e.g. {result['rejected'][0]['reason']}")

        started, last_log = clock.monotonic(), clock.monotonic()
        while not all(p.done for _, p in players):
            elapsed = clock.monotonic() - started
            if duration is not None and elapsed >= duration:
                break
            device_now = anchor + timedelta(seconds=elapsed * speed)
            await asyncio.gather(*(send(pid, events) for pid, p in players if (events := p.due(device_now))))
            if clock.monotonic() - last_log >= 10:
                last_log = clock.monotonic()
                log(f"device time {device_now:%Y-%m-%d %H:%M} UTC  {totals}")
            await asyncio.sleep(tick)
    log(f"done: {totals}")
    return totals
