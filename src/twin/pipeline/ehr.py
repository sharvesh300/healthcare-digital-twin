"""EHR steps for composite twins.

`load-ehr`  load the matched patients' Synthea histories into HAPI FHIR (system of record)
`copy-ehr`  copy their clinical content into the twin DB (source = synthea, synthetic)
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, select, tuple_
from sqlalchemy.dialects.postgresql import insert

from twin.config import Settings
from twin.db import copy_records, session_scope
from twin.fhir.client import FhirClient, synthea_to_put_transaction
from twin.models import (
    Concept,
    Condition,
    DataSource,
    Encounter,
    MedicationProduct,
    MedicationRegimen,
    Observation,
    ObservationCode,
    PatientTag,
    Tag,
)
from twin.sources.synthea import SYNTHEA_ID_SYSTEM, index_cohort, support_bundles
from twin.sources.synthea_ehr import SyntheaEhr, parse_bundle, regimen_episodes


def fhir_patients():
    """Patients with a FHIR record: the composite twins (a real participant from CGMacros
    or BIG IDEAs + a Synthea EHR). Single-source cohorts (NHANES, ...) live in the twin DB only."""
    return (select(PatientTag.patient_id).join(Tag, Tag.tag_id == PatientTag.tag_id)
            .where(Tag.code == "composite-patient"))


def synthea_bundles(cfg: Settings) -> dict[str, Path]:
    """Synthea patient id -> bundle path, across all generated cohorts."""
    return {p.patient_id: d / p.bundle_file for d in cfg.synthea_fhir_dirs for p in index_cohort(d)}


async def prune_unlinked(fhir: FhirClient, linked: set[str], log=print) -> list[str]:
    """Remove Synthea patients from FHIR that are no longer linked in core.patient.

    `match` drops stale links from the twin DB when the cohort or the matching rule
    changes; this keeps FHIR in step. Every Synthea patient carries the Synthea
    identifier system, so patients loaded but never tagged are caught too.
    """
    in_fhir = await fhir.search_ids("Patient", identifier=f"{SYNTHEA_ID_SYSTEM}|")
    stale = sorted(set(in_fhir) - linked)
    for patient_id in stale:
        t0 = time.monotonic()
        n = await fhir.delete_patient(patient_id)
        log(f"pruned {patient_id}: {n} resources ({time.monotonic() - t0:.0f}s)")
    return stale


async def run_load_ehr(cfg: Settings, force: bool = False, log=print) -> int:
    async with session_scope() as s:
        linked = {str(pid) for pid in await s.scalars(fhir_patients())}
    async with FhirClient() as fhir:
        await fhir.wait_ready()
        await prune_unlinked(fhir, linked, log)
        return await _load(fhir, cfg, linked, force, log)


async def _load(fhir: FhirClient, cfg: Settings, linked: set[str], force: bool, log) -> int:
    # Organizations/Locations/Practitioners: batch bundles with conditional create
    # (ifNoneExist), so reloading is harmless. Patient bundles reference them by identifier.
    for path in [b for d in cfg.synthea_fhir_dirs for b in support_bundles(d)]:
        t0 = time.monotonic()
        await fhir.post_bundle(path.read_bytes())
        log(f"loaded {path.name} ({time.monotonic() - t0:.0f}s)")

    bundles = synthea_bundles(cfg)
    loaded = 0
    for patient_id in sorted(linked):
        if not force and await fhir.exists("Patient", patient_id):
            log(f"skip {patient_id} (already in FHIR)")
            continue
        path = bundles[patient_id]
        t0 = time.monotonic()
        await fhir.post_bundle(synthea_to_put_transaction(json.loads(path.read_bytes()), fhir.base))
        loaded += 1
        log(f"loaded {path.name} ({path.stat().st_size / 1e6:.1f} MB, {time.monotonic() - t0:.0f}s)")
    return loaded


# ── copy-ehr: Synthea clinical content -> twin database (source = synthea) ───────

# Known unit labels in Synthea output that mean the expected UCUM unit. eGFR is already
# normalised to 1.73 m2; some Synthea versions label it "mL/min".
UNIT_ALIASES = {("33914-3", "mL/min"): "mL/min/{1.73_m2}"}

def _dose(strength_value, strength_unit, quantity) -> tuple[Decimal | None, str | None]:
    """Dose per administration from product strength x quantity (tablets etc.). Liquids
    and insulin (UNT/ML) give no dose: the administered volume is not in the data."""
    if strength_value is None or quantity is None or not strength_unit or "/" in strength_unit:
        return None, None
    return Decimal(str(round(float(strength_value) * float(quantity), 3))), strength_unit


async def _concept_ids(s, concepts: set[tuple[str, str, str]]) -> dict[tuple[str, str], int]:
    if concepts:
        rows = [{"system": a, "code": b, "display": c} for a, b, c in sorted(concepts)]
        for start in range(0, len(rows), 1000):
            await s.execute(insert(Concept).values(rows[start:start + 1000]).on_conflict_do_nothing())
    keys = {(a, b) for a, b, _ in concepts}
    found = (await s.execute(select(Concept.system, Concept.code, Concept.concept_id)
                             .where(tuple_(Concept.system, Concept.code).in_(keys)))).all() if keys else []
    return {(a, b): cid for a, b, cid in found}


async def _copy_patient(s, ehr: SyntheaEhr, source_id: int, codes: dict, products: dict) -> dict:
    pid = uuid.UUID(ehr.patient_id)
    for model in (Observation, Condition, MedicationRegimen, Encounter):
        await s.execute(delete(model).where(model.patient_id == pid, model.source_id == source_id))

    concepts = await _concept_ids(s, {(c.system, c.code, c.display) for c in ehr.conditions}
                                  | {(c.system, c.code, c.display) for c in ehr.coded})
    stats = {"unit_mismatch": 0, "unmapped_products": set()}

    obs: dict[tuple[int, datetime], tuple] = {}
    for n in ehr.numeric:
        code_id, unit = codes[n.loinc]
        if unit and UNIT_ALIASES.get((n.loinc, n.unit), n.unit) != unit:
            stats["unit_mismatch"] += 1
            continue
        obs[(code_id, n.effective_at)] = (pid, code_id, n.effective_at, Decimal(str(n.value)), None, source_id)
    for c in ehr.coded:
        code_id, _ = codes[c.loinc]
        obs[(code_id, c.effective_at)] = (pid, code_id, c.effective_at, None, concepts[(c.system, c.code)], source_id)
    await copy_records(s, Observation, ("patient_id", "code_id", "effective_at", "value_num", "value_concept_id",
                                        "source_id"), obs.values())

    conditions = {(concepts[(c.system, c.code)], c.onset_at): c for c in ehr.conditions}
    if conditions:
        await s.execute(insert(Condition), [
            {"patient_id": pid, "concept_id": cid, "onset_at": onset, "abated_at": c.abated_at, "source_id": source_id}
            for (cid, onset), c in conditions.items()])

    regimens = []
    for ep in regimen_episodes(ehr.medications):
        ingredients = products.get(ep.product_rxcui)
        if not ingredients:
            stats["unmapped_products"].add(ep.product_rxcui)
            continue
        for medication_id, strength_value, strength_unit in ingredients:
            dose, unit = _dose(strength_value, strength_unit, ep.dose_quantity)
            regimens.append({
                "patient_id": pid, "medication_id": medication_id, "started_at": ep.started_at,
                "ended_at": ep.ended_at, "dose_value": dose, "dose_unit": unit,
                "times_per_day": Decimal(str(round(ep.times_per_day, 2))) if ep.times_per_day else None,
                "as_needed": ep.as_needed, "source_id": source_id, "source_ref": ep.first_request_id,
            })
    if regimens:
        await s.execute(insert(MedicationRegimen), regimens)

    if ehr.encounters:
        await s.execute(insert(Encounter), [
            {"encounter_id": uuid.UUID(e.encounter_id), "patient_id": pid, "encounter_class": e.encounter_class,
             "started_at": e.started_at, "ended_at": e.ended_at, "source_id": source_id} for e in ehr.encounters])

    return {"observations": len(obs), "conditions": len(conditions), "regimens": len(regimens),
            "encounters": len(ehr.encounters), "unit_mismatch": stats["unit_mismatch"],
            "unmapped_products": len(stats["unmapped_products"])}


async def run_copy_ehr(cfg: Settings, log=print) -> list[dict]:
    """Copy composite twins' Synthea history (observations, conditions, medications,
    encounters) into the twin DB, flagged synthetic, so every chart is queryable in one place."""
    async with session_scope() as s:
        source_id = await s.scalar(select(DataSource.source_id).where(DataSource.code == "synthea"))
        codes = {loinc: (cid, unit) for loinc, cid, unit in
                 (await s.execute(select(ObservationCode.loinc, ObservationCode.code_id, ObservationCode.ucum_unit))).all()}
        products: dict[str, list] = {}
        for rx, mid, sv, su in (await s.execute(select(MedicationProduct.product_rxcui, MedicationProduct.medication_id,
                                                        MedicationProduct.strength_value,
                                                        MedicationProduct.strength_unit))).all():
            products.setdefault(rx, []).append((mid, sv, su))
        composite = {str(pid) for pid in await s.scalars(fhir_patients())}
    if not products:
        log("warning: ref.medication_product is empty (run seeds/build_medication_seeds.py); medications skipped")
    bundles = synthea_bundles(cfg)

    report = []
    for patient_id in sorted(composite):
        ehr = parse_bundle(bundles[patient_id], set(codes))
        async with session_scope() as s:
            stats = await _copy_patient(s, ehr, source_id, codes, products)
        report.append({"patient_id": patient_id, **stats})
        log(report[-1])
    return report
