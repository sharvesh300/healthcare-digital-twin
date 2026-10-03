"""`load-ehr` step: load the matched patients' Synthea histories into HAPI FHIR."""

from __future__ import annotations

import json
import time

from sqlalchemy import select

from twin.config import Settings
from twin.db import session_scope
from twin.fhir.client import FhirClient, synthea_to_put_transaction
from twin.models import Patient
from twin.sources.synthea import SYNTHEA_ID_SYSTEM, index_cohort, support_bundles


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
        linked = {str(pid) for pid in await s.scalars(select(Patient.patient_id))}
    async with FhirClient() as fhir:
        await fhir.wait_ready()
        await prune_unlinked(fhir, linked, log)
        return await _load(fhir, cfg, linked, force, log)


async def _load(fhir: FhirClient, cfg: Settings, linked: set[str], force: bool, log) -> int:
    # Organizations/Locations/Practitioners: batch bundles with conditional create
    # (ifNoneExist), so reloading is harmless. Patient bundles reference them by identifier.
    for path in support_bundles(cfg.synthea_fhir_dir):
        t0 = time.monotonic()
        await fhir.post_bundle(path.read_bytes())
        log(f"loaded {path.name} ({time.monotonic() - t0:.0f}s)")

    bundles = {p.patient_id: p.bundle_file for p in index_cohort(cfg.synthea_fhir_dir)}
    loaded = 0
    for patient_id in sorted(linked):
        if not force and await fhir.exists("Patient", patient_id):
            log(f"skip {patient_id} (already in FHIR)")
            continue
        path = cfg.synthea_fhir_dir / bundles[patient_id]
        t0 = time.monotonic()
        await fhir.post_bundle(synthea_to_put_transaction(json.loads(path.read_bytes()), fhir.base))
        loaded += 1
        log(f"loaded {path.name} ({path.stat().st_size / 1e6:.1f} MB, {time.monotonic() - t0:.0f}s)")
    return loaded
