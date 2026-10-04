"""Database side of the live twin: rebuild state (report.twin_latest), record transitions
(ts.twin_state_transition), pair live devices and write ingested readings (ts.*)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert

from twin.db import session_scope
from twin.models import (
    Device,
    DeviceKind,
    DeviceModel,
    GlucoseFused,
    GlucoseReading,
    SleepSegment,
    TwinStateTransition,
    WearableMetric,
    WearableSample,
)
from twin.models import views as v
from twin.streaming.events import GlucoseEvent, SleepEvent, WearableEvent
from twin.streaming.state import RULES, Reading, Rules, Transition

# ── state loading ────────────────────────────────────────────────────


class SqlStateLoader:
    def __init__(self, rules: Rules = RULES):
        self.rules = rules

    async def patient(self, patient_id: UUID) -> dict[str, Any] | None:
        p = v.patient_summary.c
        async with session_scope() as s:
            row = (await s.execute(
                select(p.patient_id, p.display_name, p.given_name, p.family_name, p.sex, p.age, p.source,
                       p.source_subject_id, p.tags).where(p.patient_id == patient_id))).mappings().first()
        return {**row, "patient_id": str(row["patient_id"])} if row else None

    async def readings(self, patient_id: UUID) -> list[Reading]:
        t = v.twin_latest.c
        async with session_scope() as s:
            latest = (await s.execute(select(v.twin_latest).where(t.patient_id == patient_id))).mappings().all()
            out = []
            for row in latest:
                if row["metric"] == "glucose":
                    out += await self._glucose_window(s, patient_id, row)
                elif row["metric"] == "steps":
                    out.append(await self._steps_today(s, row))
                else:
                    value = row["value_text"] if row["metric"] == "sleep" else row["value_num"]
                    out.append(Reading(row["time"], row["metric"], value, row["unit"], row["source"], row["until"]))
        return out

    async def series(self, patient_id: UUID, metrics: Sequence[str], since: datetime,
                     until: datetime) -> dict[str, list[tuple[datetime, float]]]:
        """Points per metric between since and until, for charts. Live-device readings, plus the
        recorded history (fused CGM, recorded wearables) before the first live point, so a chart
        runs on seamlessly from the recording into the live stream."""
        out = {}
        async with session_scope() as s:
            for metric in metrics:
                p = {"p": patient_id, "a": since, "b": until, "m": metric}
                if metric == "glucose":
                    live_q, rec_q = _GLUCOSE_LIVE, _GLUCOSE_RECORDED
                else:
                    live_q, rec_q = _WEARABLE.format(live="m.is_live_simulator"), _WEARABLE.format(
                        live="NOT m.is_live_simulator")
                live = (await s.execute(text(live_q), p)).all()
                cut = live[0][0] if live else until
                recorded = [r for r in (await s.execute(text(rec_q), p)).all() if r[0] < cut]
                out[metric] = [(t, float(v)) for t, v in recorded + live]
        return out

    async def _glucose_window(self, s, patient_id: UUID, row) -> list[Reading]:
        """The latest glucose and the readings before it in the trend window (same source)."""
        start = row["time"] - self.rules.trend_window
        if row["is_live"]:
            q = (select(GlucoseReading.time, GlucoseReading.glucose_mg_dl)
                 .where(GlucoseReading.device_id == row["device_id"], GlucoseReading.time.between(start, row["time"])))
        else:
            q = (select(GlucoseFused.time, GlucoseFused.glucose_mg_dl)
                 .where(GlucoseFused.patient_id == patient_id, GlucoseFused.time.between(start, row["time"])))
        return [Reading(t, "glucose", float(g), "mg/dL", row["source"]) for t, g in (await s.execute(q)).all()]

    async def _steps_today(self, s, row) -> Reading:
        """Steps since local midnight of the latest step reading, from the same device."""
        local = row["time"].astimezone(self.rules.tz)
        midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
        total = await s.scalar(
            select(func.sum(WearableSample.value))
            .join(WearableMetric, WearableMetric.metric_id == WearableSample.metric_id)
            .where(WearableSample.device_id == row["device_id"], WearableMetric.code == "steps",
                   WearableSample.time >= midnight, WearableSample.time <= row["time"]))
        return Reading(row["time"], "steps", float(total or 0), row["unit"], row["source"])


_GLUCOSE_LIVE = """
SELECT r.time, r.glucose_mg_dl FROM ts.glucose_reading r
JOIN core.device d USING (device_id) JOIN ref.device_model m USING (model_id)
WHERE d.patient_id = :p AND m.is_live_simulator AND m.kind = 'cgm' AND r.time BETWEEN :a AND :b
ORDER BY r.time"""
_GLUCOSE_RECORDED = """
SELECT time, glucose_mg_dl FROM ts.glucose_fused WHERE patient_id = :p AND time BETWEEN :a AND :b ORDER BY time"""
_WEARABLE = """
SELECT w.time, avg(w.value) FROM ts.wearable_sample w
JOIN core.device d USING (device_id) JOIN ref.device_model m USING (model_id)
JOIN ref.wearable_metric wm ON wm.metric_id = w.metric_id AND wm.code = :m
WHERE d.patient_id = :p AND {live} AND w.time BETWEEN :a AND :b
GROUP BY w.time ORDER BY w.time"""


# ── transitions ──────────────────────────────────────────────────────


class SqlTransitionStore:
    async def save(self, patient_id: UUID, items: Sequence[Transition], version: int) -> None:
        rows = [{"patient_id": patient_id, "signal": t.signal, "time": t.time, "from_status": t.from_status,
                 "to_status": t.to_status, "value": Decimal(str(t.value)) if t.value is not None else None,
                 "state_version": version} for t in items]
        async with session_scope() as s:
            await s.execute(insert(TwinStateTransition).values(rows).on_conflict_do_nothing())

    async def history(self, patient_id: UUID, since: datetime | None, signal: str | None,
                      limit: int) -> list[dict[str, Any]]:
        t = TwinStateTransition
        q = select(t.signal, t.time, t.from_status, t.to_status, t.value, t.state_version).where(t.patient_id == patient_id)
        if since:
            q = q.where(t.time >= since)
        if signal:
            q = q.where(t.signal == signal)
        async with session_scope() as s:
            rows = (await s.execute(q.order_by(t.time.desc()).limit(limit))).all()
        return [{"signal": str(sig), "time": tm, "from": fr, "to": to, "value": float(val) if val is not None else None,
                 "state_version": ver} for sig, tm, fr, to, val, ver in rows]


# ── ingestion ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DeviceInfo:
    patient_id: UUID
    kind: DeviceKind
    source: str  # "manufacturer model"
    is_live: bool


@dataclass
class IngestResult:
    new: dict[UUID, list[Reading]] = field(default_factory=lambda: defaultdict(list))
    accepted: int = 0
    duplicates: int = 0
    rejected: list[dict[str, Any]] = field(default_factory=list)


ACCEPTS = {"glucose": {DeviceKind.cgm, DeviceKind.glucometer}, "wearable": {DeviceKind.wearable},
           "sleep": {DeviceKind.wearable}}


class SqlIngestor:
    """Writes device events to the sensor hypertables and returns the readings that were new.

    Only live devices (ref.device_model.is_live_simulator) are accepted: the historical
    devices are loaded by the pipeline, and live rows on them would mix into the research views.
    """

    def __init__(self) -> None:
        self._devices: dict[int, DeviceInfo] = {}
        self._metrics: dict[str, tuple[int, str]] = {}

    async def pair(self, patient_id: UUID, kind: DeviceKind) -> dict[str, Any]:
        """The patient's live device of this kind (created if missing)."""
        async with session_scope() as s:
            model = (await s.execute(select(DeviceModel).where(
                DeviceModel.is_live_simulator.is_(True), DeviceModel.kind == kind))).scalar_one_or_none()
            if model is None:
                raise LookupError(f"no live-simulator device model of kind {kind}; run `twin init-db`")
            stmt = insert(Device).values(patient_id=patient_id, model_id=model.model_id)
            device_id = await s.scalar(stmt.on_conflict_do_update(
                index_elements=[Device.patient_id, Device.model_id], set_={"patient_id": stmt.excluded.patient_id}
            ).returning(Device.device_id))
        source = f"{model.manufacturer} {model.model_name}"
        self._devices[device_id] = DeviceInfo(patient_id, kind, source, True)
        return {"device_id": device_id, "kind": str(kind), "model": source}

    async def _resolve(self, s, device_ids: set[int]) -> None:
        missing = device_ids - self._devices.keys()
        if missing:
            rows = await s.execute(
                select(Device.device_id, Device.patient_id, DeviceModel.kind, DeviceModel.manufacturer,
                       DeviceModel.model_name, DeviceModel.is_live_simulator)
                .join(DeviceModel, DeviceModel.model_id == Device.model_id).where(Device.device_id.in_(missing)))
            for did, pid, kind, maker, name, live in rows:
                self._devices[did] = DeviceInfo(pid, kind, f"{maker} {name}", live)
        if not self._metrics:
            self._metrics = {code: (mid, unit) for code, mid, unit in await s.execute(
                select(WearableMetric.code, WearableMetric.metric_id, WearableMetric.unit))}

    def _check(self, event) -> str | None:
        device = self._devices.get(event.device_id)
        if device is None:
            return f"unknown device {event.device_id}"
        if not device.is_live:
            return f"device {event.device_id} is not a live device; pair one with POST /patients/{{id}}/devices"
        if device.kind not in ACCEPTS[event.kind]:
            return f"device {event.device_id} is a {device.kind}, not a source of {event.kind} events"
        if isinstance(event, WearableEvent) and event.metric not in self._metrics:
            return f"unknown metric {event.metric!r}"
        return None

    async def write(self, events: Sequence[GlucoseEvent | WearableEvent | SleepEvent]) -> IngestResult:
        result = IngestResult()
        # table -> key -> (event index, row)
        pending: dict[Any, dict[tuple, tuple[int, dict]]] = defaultdict(dict)
        async with session_scope() as s:
            await self._resolve(s, {e.device_id for e in events})
            for i, e in enumerate(events):
                if reason := self._check(e):
                    result.rejected.append({"index": i, "reason": reason})
                elif isinstance(e, GlucoseEvent):
                    pending[GlucoseReading].setdefault((e.device_id, e.time), (i, {
                        "device_id": e.device_id, "time": e.time, "glucose_mg_dl": e.glucose_mg_dl}))
                elif isinstance(e, WearableEvent):
                    mid = self._metrics[e.metric][0]
                    pending[WearableSample].setdefault((e.device_id, mid, e.time), (i, {
                        "device_id": e.device_id, "metric_id": mid, "time": e.time, "value": Decimal(str(e.value))}))
                else:
                    pending[SleepSegment].setdefault((e.device_id, e.time), (i, {
                        "device_id": e.device_id, "start_time": e.time, "end_time": e.until, "stage": e.stage}))

            inserted: list[int] = []
            for model, rows in pending.items():
                keys = [c for c in model.__table__.primary_key]
                items = list(rows.values())
                for start in range(0, len(items), 1000):
                    chunk = items[start:start + 1000]
                    stmt = insert(model).values([row for _, row in chunk]).on_conflict_do_nothing().returning(*keys)
                    for key in (await s.execute(stmt)).all():
                        inserted.append(rows[tuple(key)][0])

        for i in sorted(inserted):
            e = events[i]
            device = self._devices[e.device_id]
            if isinstance(e, GlucoseEvent):
                reading = Reading(e.time, "glucose", float(e.glucose_mg_dl), "mg/dL", device.source)
            elif isinstance(e, WearableEvent):
                reading = Reading(e.time, e.metric, e.value, self._metrics[e.metric][1], device.source)
            else:
                reading = Reading(e.time, "sleep", str(e.stage), None, device.source, e.until)
            result.new[device.patient_id].append(reading)
        result.accepted = len(inserted)
        result.duplicates = len(events) - len(result.rejected) - len(inserted)
        return result

    async def reset(self) -> int:
        """Delete every live device (their readings cascade) and all recorded transitions."""
        async with session_scope() as s:
            ids = select(DeviceModel.model_id).where(DeviceModel.is_live_simulator.is_(True))
            n = (await s.execute(delete(Device).where(Device.model_id.in_(ids)))).rowcount
            await s.execute(delete(TwinStateTransition))
        self._devices.clear()
        return n
