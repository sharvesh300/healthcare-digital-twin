"""Clinical content of a Synthea FHIR bundle, for copying into the twin database.

Only what the twin models is extracted:
  * Observation  -> numeric (valueQuantity, incl. BP panel components) or coded
                    (valueCodeableConcept) values, for LOINC codes listed in
                    ref.observation_code, and only when the unit matches the expected UCUM unit
  * Condition    -> code, onset, abatement
  * MedicationRequest -> RxNorm product, authored date, status, dosage (inline code or a
                    Medication resource in the bundle)
  * Encounter    -> class, period, type and reason (SNOMED CT)

Observations, conditions and medication requests keep the id of the encounter they were
recorded at, so the record can show what happened at each visit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from twin.models.base import EncounterClass

RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
ENCOUNTER_CLASS = {
    "AMB": EncounterClass.ambulatory, "EMER": EncounterClass.emergency, "IMP": EncounterClass.inpatient,
    "VR": EncounterClass.virtual, "HH": EncounterClass.home,
}
PERIOD_PER_DAY = {"d": 1.0, "h": 24.0, "wk": 1 / 7, "mo": 1 / 30}


@dataclass
class NumericValue:
    loinc: str
    effective_at: datetime
    value: float
    unit: str | None
    encounter_id: str | None = None


@dataclass
class CodedValue:
    loinc: str
    effective_at: datetime
    system: str
    code: str
    display: str
    encounter_id: str | None = None


@dataclass
class ConditionRecord:
    system: str
    code: str
    display: str
    onset_at: datetime
    abated_at: datetime | None
    encounter_id: str | None = None


@dataclass
class MedicationOrder:
    request_id: str
    product_rxcui: str
    display: str
    authored_at: datetime
    status: str
    dose_quantity: float | None = None
    times_per_day: float | None = None
    as_needed: bool = False
    encounter_id: str | None = None


Coding = tuple[str, str, str]  # system, code, display


@dataclass
class EncounterRecord:
    encounter_id: str
    encounter_class: EncounterClass
    started_at: datetime
    ended_at: datetime | None
    type: Coding | None = None
    reason: Coding | None = None


@dataclass
class SyntheaEhr:
    patient_id: str
    numeric: list[NumericValue] = field(default_factory=list)
    coded: list[CodedValue] = field(default_factory=list)
    conditions: list[ConditionRecord] = field(default_factory=list)
    medications: list[MedicationOrder] = field(default_factory=list)
    encounters: list[EncounterRecord] = field(default_factory=list)


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _effective(r: dict) -> datetime | None:
    return _dt(r.get("effectiveDateTime") or (r.get("effectivePeriod") or {}).get("start"))


def _encounter(r: dict) -> str | None:
    """Id of the encounter a resource was recorded at ("urn:uuid:<id>" or "Encounter/<id>")."""
    ref = (r.get("encounter") or {}).get("reference")
    return ref.rsplit(":", 1)[-1].rsplit("/", 1)[-1] if ref else None


def _coding(concepts: list | None) -> Coding | None:
    for concept in concepts or []:
        for c in concept.get("coding", []):
            if c.get("system") and c.get("code"):
                return c["system"], c["code"], c.get("display", c["code"])
    return None


def _rxnorm(concept: dict | None) -> tuple[str, str] | None:
    for c in (concept or {}).get("coding", []):
        if c.get("system") == RXNORM:
            return c["code"], c.get("display", "")
    return None


def _dosage(r: dict) -> tuple[float | None, float | None, bool]:
    di = (r.get("dosageInstruction") or [{}])[0]
    as_needed = bool(di.get("asNeededBoolean", False))
    repeat = (di.get("timing") or {}).get("repeat") or {}
    times = None
    if repeat.get("frequency") and repeat.get("period") and repeat.get("periodUnit") in PERIOD_PER_DAY:
        times = repeat["frequency"] / repeat["period"] * PERIOD_PER_DAY[repeat["periodUnit"]]
    dose = None
    for d in di.get("doseAndRate") or []:
        dose = (d.get("doseQuantity") or {}).get("value", dose)
    return dose, times, as_needed


def parse_bundle(path: Path, loinc_codes: set[str]) -> SyntheaEhr:
    bundle = json.loads(path.read_bytes())
    resources = [(e.get("fullUrl", ""), e["resource"]) for e in bundle["entry"]]
    medications = {url: r for url, r in resources if r["resourceType"] == "Medication"}
    patient = next(r for _, r in resources if r["resourceType"] == "Patient")
    ehr = SyntheaEhr(patient_id=patient["id"])

    for _, r in resources:
        kind = r["resourceType"]
        if kind == "Observation":
            at = _effective(r)
            if at is None:
                continue
            code = r["code"]["coding"][0]["code"]
            enc = _encounter(r)
            if code in loinc_codes and "valueQuantity" in r:
                q = r["valueQuantity"]
                ehr.numeric.append(NumericValue(code, at, float(q["value"]), q.get("code") or q.get("unit"), enc))
            elif code in loinc_codes and "valueCodeableConcept" in r:
                c = r["valueCodeableConcept"]["coding"][0]
                ehr.coded.append(CodedValue(code, at, c["system"], c["code"], c.get("display", c["code"]), enc))
            for comp in r.get("component", []):
                ccode = comp["code"]["coding"][0]["code"]
                if ccode in loinc_codes and "valueQuantity" in comp:
                    q = comp["valueQuantity"]
                    ehr.numeric.append(NumericValue(ccode, at, float(q["value"]), q.get("code") or q.get("unit"), enc))
        elif kind == "Condition":
            c = r["code"]["coding"][0]
            onset = _dt(r.get("onsetDateTime") or r.get("recordedDate"))
            if onset:
                ehr.conditions.append(ConditionRecord(c["system"], c["code"], c.get("display", c["code"]), onset,
                                                      _dt(r.get("abatementDateTime")), _encounter(r)))
        elif kind == "MedicationRequest":
            coded = _rxnorm(r.get("medicationCodeableConcept"))
            if coded is None and "medicationReference" in r:
                coded = _rxnorm((medications.get(r["medicationReference"]["reference"]) or {}).get("code"))
            authored = _dt(r.get("authoredOn"))
            if coded and authored:
                dose, times, as_needed = _dosage(r)
                ehr.medications.append(MedicationOrder(r["id"], coded[0], coded[1], authored, r.get("status", ""),
                                                       dose, times, as_needed, _encounter(r)))
        elif kind == "Encounter":
            period = r.get("period") or {}
            cls = ENCOUNTER_CLASS.get((r.get("class") or {}).get("code"))
            if cls and period.get("start"):
                ehr.encounters.append(EncounterRecord(r["id"], cls, _dt(period["start"]), _dt(period.get("end")),
                                                      _coding(r.get("type")), _coding(r.get("reasonCode"))))
    return ehr


@dataclass
class RegimenEpisode:
    product_rxcui: str
    display: str
    first_request_id: str
    started_at: datetime
    ended_at: datetime | None
    dose_quantity: float | None
    times_per_day: float | None
    as_needed: bool
    encounter_id: str | None = None  # where it was first prescribed


def regimen_episodes(orders: list[MedicationOrder]) -> list[RegimenEpisode]:
    """Merge repeated orders of the same product into one episode: from the first order to
    the last one, open-ended if the latest order is still active. Dosage from the latest."""
    by_product: dict[str, list[MedicationOrder]] = {}
    for o in orders:
        by_product.setdefault(o.product_rxcui, []).append(o)
    episodes = []
    for product, items in by_product.items():
        items.sort(key=lambda o: o.authored_at)
        first, last = items[0], items[-1]
        episodes.append(RegimenEpisode(
            product, last.display, first.request_id, first.authored_at,
            None if last.status == "active" else last.authored_at,
            last.dose_quantity, last.times_per_day, last.as_needed, first.encounter_id,
        ))
    return episodes
