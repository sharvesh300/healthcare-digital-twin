"""The live twin of one patient.

    GET  /patients/{patient_id}                 identity + current twin state
    GET  /patients/{patient_id}/transitions     recorded status changes, newest first
    GET  /patients/{patient_id}/readings        chart points per metric (live + recorded)
    POST /patients/{patient_id}/devices         pair a live device {"kind": "cgm" | "wearable"}
    WS   /ws/patients/{patient_id}/state        snapshot, then a delta per change, heartbeats

WebSocket messages (server -> client):
    {"type": "snapshot", "version": 41, "state": {...}}
    {"type": "delta", "version": 42, "time": "...", "changes": {"glucose.value": 186, ...},
     "transitions": [{"signal": "glucose", "from": "in_range", "to": "high", ...}]}
    {"type": "heartbeat", "version": 42}
Client -> server: {"type": "resync"} asks for a fresh snapshot (send it after a version gap).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from twin.api.deps import ingestor, twin_manager
from twin.config import settings
from twin.models import DeviceKind, TwinSignal
from twin.streaming.manager import PatientTwinStateManager, UnknownPatient
from twin.streaming.store import SqlIngestor

router = APIRouter(tags=["live twin"])
HEARTBEAT_SECONDS = 20.0


async def _require(twin: PatientTwinStateManager, patient_id: UUID) -> dict:
    try:
        return await twin.patient(patient_id)
    except UnknownPatient:
        raise HTTPException(404, f"unknown patient {patient_id}")


@router.get("/patients/{patient_id}")
async def patient_twin(patient_id: UUID, twin: PatientTwinStateManager = Depends(twin_manager)) -> dict:
    patient = await _require(twin, patient_id)
    return {"patient": patient, "state": await twin.snapshot(patient_id)}


@router.get("/patients/{patient_id}/transitions")
async def patient_transitions(patient_id: UUID, since: datetime | None = None, signal: TwinSignal | None = None,
                              limit: int = Query(100, ge=1, le=1000),
                              twin: PatientTwinStateManager = Depends(twin_manager)) -> list[dict]:
    await _require(twin, patient_id)
    rows = await twin.store.history(patient_id, since, signal, limit)
    return [{**r, "time": r["time"].astimezone(twin.rules.tz).isoformat()} for r in rows]


CHART_METRICS = {"glucose", "heart_rate", "spo2", "respiration_rate", "mets", "steps", "hrv_rmssd", "skin_temp",
                 "stress", "eda", "active_kcal", "activity_level"}


@router.get("/patients/{patient_id}/readings")
async def patient_readings(patient_id: UUID, metrics: str = Query("glucose,heart_rate"),
                           until: datetime | None = Query(None, description="end of the window; default now"),
                           hours: float = Query(6, gt=0, le=72),
                           twin: PatientTwinStateManager = Depends(twin_manager)) -> dict:
    await _require(twin, patient_id)
    wanted = [m.strip() for m in metrics.split(",") if m.strip()]
    if unknown := set(wanted) - CHART_METRICS:
        raise HTTPException(422, f"unknown metrics {sorted(unknown)}; use {sorted(CHART_METRICS)}")
    tz = twin.rules.tz
    until = until or datetime.now(tz)
    since = until - timedelta(hours=hours)
    series = await twin.loader.series(patient_id, wanted, since, until)
    return {"since": since.astimezone(tz).isoformat(), "until": until.astimezone(tz).isoformat(),
            "series": {m: [[t.astimezone(tz).isoformat(), round(v, 3)] for t, v in pts] for m, pts in series.items()}}


class PairRequest(BaseModel):
    kind: Literal["cgm", "wearable"]


@router.post("/patients/{patient_id}/devices")
async def pair_device(patient_id: UUID, body: PairRequest, twin: PatientTwinStateManager = Depends(twin_manager),
                      ingest: SqlIngestor = Depends(ingestor)) -> dict:
    await _require(twin, patient_id)
    try:
        return await ingest.pair(patient_id, DeviceKind(body.kind))
    except LookupError as e:
        raise HTTPException(422, str(e))


@router.websocket("/ws/patients/{patient_id}/state")
async def state_stream(ws: WebSocket, patient_id: UUID, twin: PatientTwinStateManager = Depends(twin_manager)) -> None:
    origin = ws.headers.get("origin")
    if origin and origin not in settings().origins:  # browsers only; scripts send no Origin
        await ws.close(code=4403)
        return
    await ws.accept()
    try:
        await twin.patient(patient_id)
    except UnknownPatient:
        await ws.send_json({"type": "error", "detail": f"unknown patient {patient_id}"})
        await ws.close(code=4404)
        return

    # Subscribe before taking the snapshot so no change falls between them; deltas the
    # snapshot already contains are skipped by version.
    async with twin.subscribe(patient_id) as sub:
        last = -1

        async def send_snapshot() -> None:
            nonlocal last
            state = await twin.snapshot(patient_id)
            await ws.send_json({"type": "snapshot", "version": state["version"], "state": state})
            last = state["version"]

        # One loop waits for the next bus message and the next client message together.
        # (Not a TaskGroup: it would swallow the server's cancellation along with the disconnect.)
        next_message = asyncio.ensure_future(sub.get())
        next_request = asyncio.ensure_future(ws.receive_text())
        try:
            await send_snapshot()
            while True:
                done, _ = await asyncio.wait({next_message, next_request}, timeout=HEARTBEAT_SECONDS,
                                             return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    await ws.send_json({"type": "heartbeat", "version": twin.version(patient_id)})
                if next_request in done:
                    try:
                        request = json.loads(next_request.result())
                    except json.JSONDecodeError:
                        request = None
                    if isinstance(request, dict) and request.get("type") == "resync":
                        sub.request_resync()
                    next_request = asyncio.ensure_future(ws.receive_text())
                if next_message in done:
                    message = next_message.result()
                    if message["type"] == "resync":
                        await send_snapshot()
                    elif message["version"] > last:
                        await ws.send_json(message)
                        last = message["version"]
                    next_message = asyncio.ensure_future(sub.get())
        except WebSocketDisconnect:
            pass
        finally:
            next_message.cancel()
            next_request.cancel()
