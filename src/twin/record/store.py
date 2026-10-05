"""Database side of the patient record: every row the record pages need for one patient.

A patient's record is small (hundreds of rows), so the store loads whole sections and
twin.record.assemble filters, groups and pages them. Times come back in the clinic zone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select

from twin.config import settings
from twin.db import session_scope
from twin.models import views as v

SECTIONS = frozenset({"medications", "conditions", "results", "visits", "baseline", "cgm"})


@dataclass
class RecordData:
    patient: dict[str, Any]
    medications: list[dict] = field(default_factory=list)
    conditions: list[dict] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)
    visits: list[dict] = field(default_factory=list)
    baseline: dict | None = None
    cgm: dict | None = None


def _clean(row: dict, tz) -> dict:
    out = {}
    for k, val in row.items():
        if isinstance(val, Decimal):
            val = float(val)
        elif isinstance(val, datetime):
            val = val.astimezone(tz)
        elif isinstance(val, UUID):
            val = str(val)
        out[k] = val
    return out


class SqlRecordStore:
    async def load(self, patient_id: UUID, sections: set[str] = SECTIONS) -> RecordData | None:
        tz = settings().tz
        rows = lambda result: [_clean(dict(r), tz) for r in result.mappings().all()]  # noqa: E731

        async def of(view, order=None):
            stmt = select(view).where(view.c.patient_id == patient_id)
            return rows(await s.execute(stmt.order_by(*order) if order is not None else stmt))

        async with session_scope() as s:
            patient = await of(v.patient_summary)
            if not patient:
                return None
            data = RecordData(patient=patient[0])
            if "medications" in sections:
                data.medications = await of(v.medication_regimen, [v.medication_regimen.c.started_at])
            if "conditions" in sections:
                data.conditions = await of(v.condition_episode, [v.condition_episode.c.onset_at])
            if "results" in sections:
                data.results = await of(v.observation_result,
                                        [v.observation_result.c.effective_at, v.observation_result.c.is_synthetic])
            if "visits" in sections:
                data.visits = await of(v.visit, [v.visit.c.started_at])
            if "baseline" in sections:
                baseline = await of(v.patient_baseline)
                data.baseline = baseline[0] if baseline else None
            if "cgm" in sections:
                window = await of(v.cgm_window)
                consistency = await of(v.consistency)
                daily = await of(v.cgm_daily, [v.cgm_daily.c.day])
                for d in daily:
                    d["day"] = d["day"].date().isoformat()
                data.cgm = {"window": window[0] if window else None,
                            "consistency": consistency[0] if consistency else None, "daily": daily}
        return data
