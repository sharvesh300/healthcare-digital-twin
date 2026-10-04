"""`reconcile` step: make the FHIR record agree with the real participant.

* metric-based tags (gmi-warn / gmi-inconsistent) are recomputed from report.consistency
* FHIR Patient gets the twin's tags as meta.tag and the participant's race/ethnicity
* measured baseline labs and derived BMI / LDL become the newest Observations,
  tagged composite-override; Synthea history is left untouched
"""

from __future__ import annotations

import csv
from decimal import Decimal

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert

from twin.config import Settings, settings
from twin.db import lookup, session_scope
from twin.fhir.client import FhirClient, twin_id
from twin.models import (
    DataSource,
    Observation,
    ObservationCode,
    Patient,
    PatientTag,
    Tag,
)
from twin.models import views as v
from twin.pipeline.ehr import fhir_patients

TAG_SYSTEM = "urn:healthcare-digital-twin:tags"
OVERRIDE_TAG = {"system": TAG_SYSTEM, "code": "composite-override",
                "display": "Value from the real CGMacros participant, overriding synthetic history"}
GMI_TAGS = {"warn": "gmi-warn", "inconsistent": "gmi-inconsistent"}
VITAL_SIGNS = {"29463-7", "8302-2", "39156-5"}
US_CORE_RACE = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race"
US_CORE_ETHNICITY = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity"
OMB = "urn:oid:2.16.840.1.113883.6.238"

# CGMacros self-identification -> (OMB race category | None, hispanic?)
RACE_MAP = {
    "Black or African American": (("2054-5", "Black or African American"), False),
    "White": (("2106-3", "White"), False),
    "Hispanic/Latino": (None, True),
}


def _num(value) -> float | None:
    return None if value is None else float(value) if isinstance(value, Decimal) else value


def _race_extensions(race_ethnicity: str | None) -> list[dict]:
    if not race_ethnicity or race_ethnicity not in RACE_MAP:
        return []
    race, hispanic = RACE_MAP[race_ethnicity]
    race_ext = {"url": US_CORE_RACE, "extension": []}
    if race:
        race_ext["extension"].append({"url": "ombCategory", "valueCoding": {"system": OMB, "code": race[0], "display": race[1]}})
    race_ext["extension"].append({"url": "text", "valueString": race_ethnicity})
    eth_code = ("2135-2", "Hispanic or Latino") if hispanic else ("2186-5", "Not Hispanic or Latino")
    eth_ext = {
        "url": US_CORE_ETHNICITY,
        "extension": [
            {"url": "ombCategory", "valueCoding": {"system": OMB, "code": eth_code[0], "display": eth_code[1]}},
            {"url": "text", "valueString": eth_code[1]},
        ],
    }
    return [race_ext, eth_ext]


def _observation(patient_id, loinc, display, unit, value, effective, derived_from=()) -> dict:
    effective = effective.astimezone(settings().tz)
    category = "vital-signs" if loinc in VITAL_SIGNS else "laboratory"
    obs = {
        "resourceType": "Observation",
        "id": twin_id(patient_id, "baseline", loinc),
        "meta": {"tag": [OVERRIDE_TAG]},
        "status": "final",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                  "code": category}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": loinc, "display": display}], "text": display},
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": effective.isoformat(),
        "issued": effective.isoformat(),
        "valueQuantity": {"value": value, "unit": unit, "system": "http://unitsofmeasure.org", "code": unit},
    }
    if derived_from:
        obs["derivedFrom"] = [{"reference": f"Observation/{twin_id(patient_id, 'baseline', c)}"} for c in derived_from]
    return obs


async def run_reconcile(cfg: Settings, log=print) -> list[dict]:
    async with session_scope() as s:
        await _retag_from_consistency(s)
    async with FhirClient() as fhir:
        await fhir.wait_ready()
        report = await _sync_patients(fhir, log)

    out = cfg.reports_dir / "consistency_report.csv"
    with out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(report[0]) if report else ["subject_id"])
        writer.writeheader()
        writer.writerows(report)
    return report


async def _retag_from_consistency(s) -> None:
    """Metric-based tags follow the data: drop and recompute gmi-warn/gmi-inconsistent."""
    tag_ids = await lookup(s, Tag.code, Tag.tag_id)
    await s.execute(delete(PatientTag).where(PatientTag.tag_id.in_([tag_ids[t] for t in GMI_TAGS.values()])))
    rows = [
        {"patient_id": pid, "tag_id": tag_ids[GMI_TAGS[status]]}
        for pid, status in (await s.execute(select(v.consistency.c.patient_id, v.consistency.c.status)))
        if status in GMI_TAGS
    ]
    if rows:
        await s.execute(insert(PatientTag).values(rows))


async def _sync_patients(fhir: FhirClient, log) -> list[dict]:
    report = []
    async with session_scope() as s:
        tag_meta = {code: {"system": system, "code": code, "display": display}
                    for code, system, display in (await s.execute(select(Tag.code, Tag.fhir_system, Tag.display)))}
        codes = {loinc: (display, unit) for loinc, display, unit in
                 (await s.execute(select(ObservationCode.loinc, ObservationCode.display, ObservationCode.ucum_unit)))}
        ps, c = v.patient_summary.c, v.consistency.c
        patients = (await s.execute(
            select(ps.patient_id, ps.race_ethnicity, ps.tags, ps.source_subject_id,
                   c.hba1c, c.gmi, c.abs_diff, c.status, c.mean_mg_dl, c.glucose_source)
            .select_from(v.patient_summary.outerjoin(v.consistency, ps.patient_id == c.patient_id))
            .where(ps.patient_id.in_(fhir_patients()))
            .order_by(ps.source_subject_id)
        )).all()

    for patient_id, race_eth, tags, subject_id, hba1c, gmi, diff, status, mean, cgm in patients:
        pid = str(patient_id)
        # Patient: tags + race/ethnicity. HAPI merges tags on update, so tags of
        # ours that are no longer assigned are removed with $meta-delete.
        patient = await fhir.get(f"/Patient/{pid}")
        current = {t.get("code") for t in patient.get("meta", {}).get("tag", []) if t.get("system") == TAG_SYSTEM}
        await fhir.meta_delete_tags("Patient", pid, [tag_meta[t] for t in current - set(tags) if t in tag_meta])
        patient["meta"] = {"tag": [tag_meta[t] for t in tags]}
        race = _race_extensions(race_eth)
        if race:  # replace Synthea's race/ethnicity only when the real participant reported one
            patient["extension"] = [
                e for e in patient.get("extension", []) if e["url"] not in (US_CORE_RACE, US_CORE_ETHNICITY)
            ] + race

        # Baseline labs, measured then derived.
        async with session_scope() as s:
            # Only real (non-synthetic) numeric values override the synthetic EHR.
            labs = (await s.execute(
                select(ObservationCode.loinc, Observation.value_num, Observation.effective_at)
                .join(ObservationCode, ObservationCode.code_id == Observation.code_id)
                .join(DataSource, DataSource.source_id == Observation.source_id)
                .where(Observation.patient_id == patient_id, Observation.value_num.is_not(None),
                       DataSource.is_synthetic.is_(False))
                .distinct(ObservationCode.loinc)
                .order_by(ObservationCode.loinc, Observation.effective_at.desc())
            )).all()
            b = v.patient_baseline.c
            bmi, bmi_synth, ldl, ldl_synth, effective = (await s.execute(
                select(b.bmi, b.bmi_is_synthetic, b.ldl, b.ldl_is_synthetic, b.effective_at)
                .where(b.patient_id == patient_id)
            )).one()

            resources = [patient]
            for loinc, value, at in labs:
                display, unit = codes[loinc]
                resources.append(_observation(pid, loinc, display, unit, _num(value), at))
            # Derived values only when every input is real.
            if bmi is not None and not bmi_synth:
                resources.append(_observation(pid, "39156-5", *codes["39156-5"], bmi, effective,
                                              derived_from=("29463-7", "8302-2")))
            if ldl is not None and not ldl_synth:
                resources.append(_observation(pid, "13457-7", *codes["13457-7"], ldl, effective,
                                              derived_from=("2093-3", "2085-9", "2571-8")))
            await fhir.put_all(resources)
            await s.execute(update(Patient).where(Patient.patient_id == patient_id).values(fhir_synced_at=func.now()))

        row = {"subject_id": subject_id, "patient_id": pid, "hba1c": hba1c, "cgm_mean_mg_dl": mean,
               "gmi": gmi, "abs_diff": diff, "status": status, "cgm": cgm, "tags": ";".join(tags)}
        report.append(row)
        log(row)
    return report
