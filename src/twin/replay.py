"""Live sensor feed: replays stored readings over WebSocket at N x real time.

    GET /patients[?tag=composite-patient]   -> patients with their sensor windows
    WS  /ws/patients/{patient_id}?speed=60&kinds=glucose,activity,meal
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import UUID

import psycopg
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect

from twin.config import settings

app = FastAPI(title="Digital twin sensor replay")


async def _connect() -> psycopg.AsyncConnection:
    cfg = settings()
    return await psycopg.AsyncConnection.connect(cfg.database_url, options=f"-c timezone={cfg.source_tz}")


@app.get("/health")
async def health() -> dict:
    async with await _connect() as conn:
        await conn.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/patients")
async def patients(tag: str | None = None) -> list[dict]:
    async with await _connect() as conn:
        cur = await conn.execute(
            """
            SELECT s.patient_id, s.given_name, s.family_name, s.sex, s.age, s.source, s.source_subject_id,
                   s.tags, w.window_start, w.window_end
            FROM report.patient_summary s LEFT JOIN report.sensor_window w USING (patient_id)
            WHERE %(tag)s::text IS NULL OR %(tag)s = ANY(s.tags)
            ORDER BY s.source_subject_id
            """,
            {"tag": tag},
        )
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in await cur.fetchall()]


@app.websocket("/ws/patients/{patient_id}")
async def stream(
    ws: WebSocket,
    patient_id: UUID,
    speed: float | None = Query(None, ge=0, description="playback multiplier; 0 = as fast as possible"),
    kinds: str | None = Query(None, description="comma-separated: glucose,activity,meal"),
    start: datetime | None = Query(None, description="skip events before this twin time"),
    max_sleep: float = Query(10.0, gt=0, description="cap on any single wait, seconds"),
) -> None:
    speed = settings().replay_speed if speed is None else speed
    kind_list = [k.strip() for k in kinds.split(",")] if kinds else None
    await ws.accept()
    try:
        async with await _connect() as conn:
            exists = await (await conn.execute("SELECT 1 FROM core.patient WHERE patient_id = %s", (patient_id,))).fetchone()
            if not exists:
                await ws.send_json({"kind": "error", "detail": f"unknown patient {patient_id}"})
                await ws.close(code=4404)
                return
            await ws.send_json({"kind": "start", "patient_id": str(patient_id), "speed": speed})
            async with conn.transaction(), conn.cursor(name="replay") as cur:
                await cur.execute(
                    """
                    SELECT time, kind, source, payload FROM report.replay_stream
                    WHERE patient_id = %s
                      AND (%s::text[] IS NULL OR kind = ANY(%s::text[]))
                      AND time >= coalesce(%s::timestamptz, '-infinity')
                    ORDER BY time, kind
                    """,
                    (patient_id, kind_list, kind_list, start),
                )
                previous = None
                sent = 0
                async for time, kind, source, payload in cur:
                    if previous is not None and speed > 0:
                        delay = (time - previous).total_seconds() / speed
                        if delay > 0:
                            await asyncio.sleep(min(delay, max_sleep))
                    previous = time
                    await ws.send_json({"time": time.isoformat(), "kind": kind, "source": source, **payload})
                    sent += 1
            await ws.send_json({"kind": "end", "events": sent})
            await ws.close()
    except WebSocketDisconnect:
        return


def serve(host: str, port: int) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port)
