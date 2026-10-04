"""Twin API server: patient list, recorded-history replay, the live twin and the /twin endpoints.

    GET /patients[?tag=composite-patient]   -> patients with their sensor windows
    WS  /ws/patients/{patient_id}?speed=60&kinds=glucose_fused,glucose,activity,medication
                                            -> recorded history, straight from the database
    /patients/{patient_id}, /ws/patients/{patient_id}/state, /ingest/events
                                            -> the live twin, see twin.api.patients / twin.api.ingest
    /twin/...                               -> see twin.api.twin_view

The live twin keeps state in this process: run a single worker.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from uuid import UUID

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import select, text

from twin.api.ingest import router as ingest_router
from twin.api.patients import router as patients_router
from twin.api.twin_view import router as twin_router
from twin.config import settings
from twin.db import dispose_engine, engine, session_scope
from twin.models import Patient
from twin.models import views as v
from twin.streaming.bus import InProcessBus
from twin.streaming.manager import PatientTwinStateManager
from twin.streaming.state import Rules
from twin.streaming.store import SqlIngestor, SqlStateLoader, SqlTransitionStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    rules = Rules(tz=settings().tz)
    app.state.twin = PatientTwinStateManager(SqlStateLoader(rules), SqlTransitionStore(), InProcessBus(), rules)
    app.state.ingestor = SqlIngestor()
    ticker = asyncio.create_task(app.state.twin.run())  # staleness checks, eviction
    try:
        yield
    finally:
        ticker.cancel()
        with suppress(asyncio.CancelledError):
            await ticker
        await dispose_engine()


app = FastAPI(title="Healthcare digital twin API", lifespan=lifespan)
app.include_router(twin_router)
app.include_router(patients_router)
app.include_router(ingest_router)


@app.get("/health")
async def health() -> dict:
    async with engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/patients")
async def patients(request: Request, tag: str | None = None) -> list[dict]:
    """Patients with their sensor window and, for twins loaded in this process, a live summary
    (`live`: streaming flag and latest glucose) so a list can show live badges without sockets."""
    s_, w = v.patient_summary.c, v.sensor_window.c
    stmt = (
        select(s_.patient_id, s_.given_name, s_.family_name, s_.sex, s_.age, s_.source, s_.source_subject_id,
               s_.tags, w.window_start, w.window_end)
        .select_from(v.patient_summary.outerjoin(v.sensor_window, s_.patient_id == w.patient_id))
        .order_by(s_.source_subject_id)
    )
    if tag:
        stmt = stmt.where(s_.tags.contains([tag]))
    tz = settings().tz
    async with session_scope() as s:
        rows = (await s.execute(stmt)).mappings().all()
    twin = request.app.state.twin

    def live(patient_id) -> dict | None:
        state = twin.cached(patient_id)
        if state is None:
            return None
        g = state.glucose
        return {"streaming": state.streaming, "version": state.version,
                "glucose": {"value": g.value, "status": g.status, "trend": g.trend,
                            "time": g.time.astimezone(tz).isoformat() if g.time else None}}

    return [
        {**row, **{k: row[k].astimezone(tz) for k in ("window_start", "window_end") if row[k] is not None},
         "live": live(row["patient_id"])}
        for row in rows
    ]


@app.websocket("/ws/patients/{patient_id}")
async def stream(
    ws: WebSocket,
    patient_id: UUID,
    speed: float | None = Query(None, ge=0, description="playback multiplier; 0 = as fast as possible"),
    kinds: str | None = Query(None, description="comma-separated: glucose,activity,meal"),
    start: datetime | None = Query(None, description="skip events before this twin time"),
    max_sleep: float = Query(10.0, gt=0, description="cap on any single wait, seconds"),
) -> None:
    cfg = settings()
    speed = cfg.replay_speed if speed is None else speed
    await ws.accept()
    try:
        async with session_scope() as s:
            if await s.get(Patient, patient_id) is None:
                await ws.send_json({"kind": "error", "detail": f"unknown patient {patient_id}"})
                await ws.close(code=4404)
                return
            await ws.send_json({"kind": "start", "patient_id": str(patient_id), "speed": speed})

            r = v.replay_stream.c
            stmt = select(r.time, r.kind, r.source, r.payload).where(r.patient_id == patient_id)
            if kinds:
                stmt = stmt.where(r.kind.in_([k.strip() for k in kinds.split(",")]))
            if start:
                stmt = stmt.where(r.time >= start)
            # Server-side cursor: rows are fetched in batches as the replay advances.
            result = await s.stream(stmt.order_by(r.time, r.kind).execution_options(yield_per=500))

            previous = None
            sent = 0
            async for time, kind, source, payload in result:
                if previous is not None and speed > 0:
                    delay = (time - previous).total_seconds() / speed
                    if delay > 0:
                        await asyncio.sleep(min(delay, max_sleep))
                previous = time
                await ws.send_json({"time": time.astimezone(cfg.tz).isoformat(), "kind": kind, "source": source,
                                    **payload})
                sent += 1
        await ws.send_json({"kind": "end", "events": sent})
        await ws.close()
    except WebSocketDisconnect:
        return


def serve(host: str, port: int) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port)
