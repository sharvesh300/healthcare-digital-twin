"""`reconcile` step: make the FHIR record agree with the real participant.

* metric-based tags (gmi-warn / gmi-inconsistent) are recomputed from report.consistency
* FHIR Patient gets the twin's tags as meta.tag and the participant's race/ethnicity
* measured baseline labs and derived BMI / LDL become the newest Observations,
  tagged composite-override; Synthea history is left untouched
"""

from __future__ import annotations

import csv
from decimal import Decimal

from twin.config import Settings
from twin.db import connect
from twin.fhir_client import FhirClient, twin_id

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


def run_reconcile(cfg: Settings, log=print) -> list[dict]:
    fhir = FhirClient()
    fhir.wait_ready()
    report = []
    with connect() as conn:
        tag_ids = dict(conn.execute("SELECT code, tag_id FROM ref.tag").fetchall())
        tag_meta = {code: {"system": system, "code": code, "display": display}
                    for code, system, display in conn.execute("SELECT code, fhir_system, display FROM ref.tag")}
        codes = {loinc: (display, unit) for loinc, display, unit in
                 conn.execute("SELECT loinc, display, ucum_unit FROM ref.observation_code")}

        # 1. Metric-based tags follow the data.
        conn.execute("DELETE FROM core.patient_tag WHERE tag_id = ANY(%s)",
                     ([tag_ids[t] for t in GMI_TAGS.values()],))
        for patient_id, status in conn.execute("SELECT patient_id, status FROM report.consistency").fetchall():
            if status in GMI_TAGS:
                conn.execute("INSERT INTO core.patient_tag (patient_id, tag_id) VALUES (%s, %s)",
                             (patient_id, tag_ids[GMI_TAGS[status]]))
        conn.commit()

        patients = conn.execute(
            """
            SELECT s.patient_id, s.race_ethnicity, s.tags, s.source_subject_id,
                   c.hba1c, c.gmi, c.abs_diff, c.status, c.mean_mg_dl, c.device_model
            FROM report.patient_summary s LEFT JOIN report.consistency c USING (patient_id)
            ORDER BY s.source_subject_id
            """
        ).fetchall()
        for patient_id, race_eth, tags, subject_id, hba1c, gmi, diff, status, mean, cgm in patients:
            pid = str(patient_id)
            # 2. Patient: tags + race/ethnicity. HAPI merges tags on update, so tags of
            #    ours that are no longer assigned are removed with $meta-delete.
            patient = fhir.get(f"/Patient/{pid}")
            current = {t.get("code") for t in patient.get("meta", {}).get("tag", []) if t.get("system") == TAG_SYSTEM}
            fhir.meta_delete_tags("Patient", pid, [tag_meta[c] for c in current - set(tags) if c in tag_meta])
            patient["meta"] = {"tag": [tag_meta[c] for c in tags]}
            patient["extension"] = [
                e for e in patient.get("extension", []) if e["url"] not in (US_CORE_RACE, US_CORE_ETHNICITY)
            ] + _race_extensions(race_eth)

            # 3. Baseline labs, measured then derived.
            labs = conn.execute(
                """
                SELECT DISTINCT ON (c.loinc) c.loinc, lr.value, lr.effective_at
                FROM core.lab_result lr JOIN ref.observation_code c USING (code_id)
                WHERE lr.patient_id = %s ORDER BY c.loinc, lr.effective_at DESC
                """,
                (patient_id,),
            ).fetchall()
            resources = [patient]
            for loinc, value, effective in labs:
                display, unit = codes[loinc]
                resources.append(_observation(pid, loinc, display, unit, _num(value), effective))
            bmi, ldl, effective = conn.execute(
                "SELECT bmi, ldl, effective_at FROM report.patient_baseline WHERE patient_id = %s", (patient_id,)
            ).fetchone()
            if bmi is not None:
                resources.append(_observation(pid, "39156-5", *codes["39156-5"], _num(bmi), effective,
                                              derived_from=("29463-7", "8302-2")))
            if ldl is not None:
                resources.append(_observation(pid, "13457-7", *codes["13457-7"], _num(ldl), effective,
                                              derived_from=("2093-3", "2085-9", "2571-8")))
            fhir.put_all(resources)
            conn.execute("UPDATE core.patient SET fhir_synced_at = now() WHERE patient_id = %s", (patient_id,))
            conn.commit()

            row = {"subject_id": subject_id, "patient_id": pid, "hba1c": _num(hba1c), "cgm_mean_mg_dl": _num(mean),
                   "gmi": _num(gmi), "abs_diff": _num(diff), "status": status, "cgm": cgm, "tags": ";".join(tags)}
            report.append(row)
            log(row)

    out = cfg.reports_dir / "consistency_report.csv"
    with out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(report[0]) if report else ["subject_id"])
        writer.writeheader()
        writer.writerows(report)
    return report
