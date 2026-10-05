"""The patient record: an overview, lists and a detail page for each kind of entry.

    GET /patients/{id}/record                          overview (summary tiles and every section)
    GET /patients/{id}/record/tests[?panel=&flag=out_of_range]
    GET /patients/{id}/record/tests/{measure}          every result of one test or vital (blood_pressure = SBP + DBP)
    GET /patients/{id}/record/conditions[?active=&kind=&group=]
    GET /patients/{id}/record/conditions/{concept_id}  every episode of one diagnosis or finding
    GET /patients/{id}/record/medications[?active=&glucose_lowering=&drug_class=]
    GET /patients/{id}/record/medications/{rxcui}      every prescription of one medication
    GET /patients/{id}/record/visits[?year=&class=&limit=&cursor=]
    GET /patients/{id}/record/visits/{encounter_id}    everything recorded at one visit

Every entry carries `source` and `is_synthetic`; times are in the clinic zone. The shapes are
described in twin.record.assemble.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from twin.record import assemble as a
from twin.record.store import RecordData, SqlRecordStore

router = APIRouter(prefix="/patients/{patient_id}/record", tags=["record"])


def record_store() -> SqlRecordStore:
    return SqlRecordStore()


async def _load(store: SqlRecordStore, patient_id: UUID, *sections: str) -> RecordData:
    data = await (store.load(patient_id, set(sections)) if sections else store.load(patient_id))
    if data is None:
        raise HTTPException(404, f"unknown patient {patient_id}")
    return data


def _found(item: dict | None, what: str) -> dict:
    if item is None:
        raise HTTPException(404, f"no {what} in this record")
    return item


@router.get("")
async def record(patient_id: UUID, store: SqlRecordStore = Depends(record_store)) -> dict:
    return a.overview(await _load(store, patient_id))


@router.get("/tests")
async def tests(patient_id: UUID, panel: str | None = None, flag: Literal["out_of_range"] | None = None,
                store: SqlRecordStore = Depends(record_store)) -> dict:
    return a.tests_list(await _load(store, patient_id, "results"), panel, flag == "out_of_range")


@router.get("/tests/{measure}")
async def test_detail(patient_id: UUID, measure: str, store: SqlRecordStore = Depends(record_store)) -> dict:
    data = await _load(store, patient_id, "results", "medications", "conditions", "visits")
    return _found(a.measure_detail(data, measure), f"results for {measure}")


@router.get("/conditions")
async def conditions(patient_id: UUID, active: bool | None = None, kind: Literal["diagnosis", "finding"] | None = None,
                     group: str | None = None, store: SqlRecordStore = Depends(record_store)) -> dict:
    return a.conditions_list(await _load(store, patient_id, "conditions"), active, kind, group)


@router.get("/conditions/{concept_id}")
async def condition_detail(patient_id: UUID, concept_id: int, store: SqlRecordStore = Depends(record_store)) -> dict:
    data = await _load(store, patient_id, "conditions", "medications", "results", "visits")
    return _found(a.condition_detail(data, concept_id), f"condition {concept_id}")


@router.get("/medications")
async def medications(patient_id: UUID, active: bool | None = None, glucose_lowering: bool | None = None,
                      drug_class: str | None = None, store: SqlRecordStore = Depends(record_store)) -> dict:
    return a.medications_list(await _load(store, patient_id, "medications"), active, glucose_lowering, drug_class)


@router.get("/medications/{rxcui}")
async def medication_detail(patient_id: UUID, rxcui: int, store: SqlRecordStore = Depends(record_store)) -> dict:
    data = await _load(store, patient_id, "medications", "conditions", "results", "visits")
    return _found(a.medication_detail(data, rxcui), f"medication {rxcui}")


@router.get("/visits")
async def visits(patient_id: UUID, year: int | None = None, cls: str | None = Query(None, alias="class"),
                 limit: int = Query(20, ge=1, le=200), cursor: str | None = None,
                 store: SqlRecordStore = Depends(record_store)) -> dict:
    data = await _load(store, patient_id, "visits", "results", "conditions", "medications")
    return a.visits_page(data, year, cls, limit, cursor)


@router.get("/visits/{encounter_id}")
async def visit_detail(patient_id: UUID, encounter_id: UUID, store: SqlRecordStore = Depends(record_store)) -> dict:
    data = await _load(store, patient_id, "visits", "results", "conditions", "medications")
    return _found(a.visit_detail(data, str(encounter_id)), f"visit {encounter_id}")
