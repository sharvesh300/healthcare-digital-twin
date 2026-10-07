"""Model predictions for a patient's twin.

    GET /patients/{id}/predictions/glucose[?at=]   glucose forecast at +15/30/45/60 min

`at` is a twin time (ISO 8601; without an offset it is read in the clinic zone). Without it,
the forecast starts from the latest CGM reading. Readings after `at` come back as `actual`
so a past forecast can be checked against what happened. The shape is described in
twin.prediction.assemble.

Errors: 404 unknown patient; 503 when the GRU bundle isn't exported, fails its checks, or the
`ml` extra isn't installed. A twin whose data can't support a forecast gets 200 with
`unavailable.reason`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from twin.config import settings
from twin.prediction import assemble
from twin.prediction.model import ModelUnavailable, gru_bundle
from twin.prediction.store import SqlForecastStore

router = APIRouter(prefix="/patients/{patient_id}/predictions", tags=["predictions"])


def forecast_store() -> SqlForecastStore:
    return SqlForecastStore()


def gru_loader() -> Callable:
    """Returns the loader of the exported GRU bundle (called only for twins that use it)."""
    root = settings().data_dir / "models" / "glucose_forecast"
    return lambda: gru_bundle(root)


@router.get("/glucose")
async def glucose_forecast(
    patient_id: UUID,
    at: datetime | None = Query(None, description="forecast origin (twin time); default: the latest CGM reading"),
    store: SqlForecastStore = Depends(forecast_store),
    loader: Callable = Depends(gru_loader),
) -> dict:
    tz = settings().tz
    if at is not None and at.tzinfo is None:
        at = at.replace(tzinfo=tz)
    inputs = await store.load(patient_id, at)
    if inputs is None:
        raise HTTPException(404, f"unknown patient {patient_id}")
    try:
        # Off the event loop: the GRU runs in torch and the ARIMA fallback fits per request (~1 s).
        return await run_in_threadpool(assemble.forecast, inputs, tz, loader)
    except ModelUnavailable as e:
        raise HTTPException(503, str(e)) from e
