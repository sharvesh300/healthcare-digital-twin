"""Event ingestion: devices POST batches of readings; new ones go to TimescaleDB, then to the twin.

    POST /ingest/events   {"events": [{"kind": "glucose", "device_id": 7, "time": "...", "glucose_mg_dl": 142}, ...]}

Re-sending a batch is safe: readings already stored are counted as duplicates and are not
applied to the twin again.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from twin.api.deps import ingestor, twin_manager
from twin.streaming.events import EventBatch
from twin.streaming.manager import PatientTwinStateManager
from twin.streaming.store import SqlIngestor

router = APIRouter(tags=["live twin"])


@router.post("/ingest/events")
async def ingest_events(batch: EventBatch, ingest: SqlIngestor = Depends(ingestor),
                        twin: PatientTwinStateManager = Depends(twin_manager)) -> dict:
    result = await ingest.write(batch.events)  # committed before the state changes
    published = 0
    for patient_id, readings in result.new.items():
        if await twin.handle(patient_id, readings):
            published += 1
    return {"accepted": result.accepted, "duplicates": result.duplicates, "rejected": result.rejected,
            "patients_updated": published}
