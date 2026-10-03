"""Read Synthea FHIR R4 transaction bundles without loading them into a server.

Only the facts needed for matching and for the patient master record are
extracted. The index is cached next to the bundles because the cohort is ~1 GB.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BMI_LOINC = "39156-5"
SYNTHEA_ID_SYSTEM = "https://github.com/synthetichealth/synthea"
MRN_TYPE = "MR"


@dataclass(frozen=True)
class SyntheaPatient:
    patient_id: str
    bundle_file: str
    sex: str
    birth_date: date
    deceased: bool
    given_name: str
    family_name: str
    name_prefix: str | None
    mrn: str
    address_city: str | None
    address_state: str | None
    address_postal: str | None
    last_encounter_end: datetime
    latest_bmi: float | None

    def age_on(self, day: date) -> int:
        b = self.birth_date
        return day.year - b.year - ((day.month, day.day) < (b.month, b.day))

    def last_encounter_local_date(self, tz: ZoneInfo) -> date:
        return self.last_encounter_end.astimezone(tz).date()


def summarise_bundle(path: Path) -> SyntheaPatient | None:
    bundle = json.loads(path.read_bytes())
    resources = [e["resource"] for e in bundle.get("entry", [])]
    patient = next((r for r in resources if r["resourceType"] == "Patient"), None)
    if patient is None:
        return None

    encounter_ends = [
        datetime.fromisoformat(r["period"].get("end") or r["period"]["start"])
        for r in resources
        if r["resourceType"] == "Encounter" and "period" in r
    ]
    bmis = sorted(
        (r["effectiveDateTime"], r["valueQuantity"]["value"])
        for r in resources
        if r["resourceType"] == "Observation"
        and "effectiveDateTime" in r
        and "valueQuantity" in r
        and any(c.get("code") == BMI_LOINC for c in r["code"].get("coding", []))
    )
    if not encounter_ends:
        return None

    name = next((n for n in patient.get("name", []) if n.get("use") == "official"), patient["name"][0])
    mrn = next(
        i["value"]
        for i in patient.get("identifier", [])
        if any(c.get("code") == MRN_TYPE for c in i.get("type", {}).get("coding", []))
    )
    address = (patient.get("address") or [{}])[0]
    return SyntheaPatient(
        patient_id=patient["id"],
        bundle_file=path.name,
        sex=patient["gender"],
        birth_date=date.fromisoformat(patient["birthDate"]),
        deceased="deceasedDateTime" in patient or patient.get("deceasedBoolean", False),
        given_name=" ".join(name.get("given", [])),
        family_name=name.get("family", ""),
        name_prefix=(name.get("prefix") or [None])[0],
        mrn=mrn,
        address_city=address.get("city"),
        address_state=address.get("state"),
        address_postal=address.get("postalCode"),
        last_encounter_end=max(encounter_ends),
        latest_bmi=float(bmis[-1][1]) if bmis else None,
    )


def is_patient_bundle(path: Path) -> bool:
    return path.suffix == ".json" and not path.name.startswith(("hospitalInformation", "practitionerInformation"))


def index_cohort(fhir_dir: Path, refresh: bool = False) -> list[SyntheaPatient]:
    cache = fhir_dir.parent / "cohort_index.json"
    bundles = sorted(p for p in fhir_dir.iterdir() if is_patient_bundle(p))
    if cache.exists() and not refresh:
        cached = json.loads(cache.read_text())
        if cached.get("files") == [p.name for p in bundles]:
            return [_from_json(d) for d in cached["patients"]]

    patients = [p for p in (summarise_bundle(b) for b in bundles) if p is not None]
    cache.write_text(
        json.dumps(
            {"files": [p.name for p in bundles], "patients": [asdict(p) for p in patients]},
            default=str,
        )
    )
    return patients


def _from_json(d: dict) -> SyntheaPatient:
    return SyntheaPatient(
        **{
            **d,
            "birth_date": date.fromisoformat(d["birth_date"]),
            "last_encounter_end": datetime.fromisoformat(d["last_encounter_end"]),
        }
    )


def support_bundles(fhir_dir: Path) -> list[Path]:
    """Organization/Location and Practitioner bundles; must load before patients."""
    return sorted(fhir_dir.glob("hospitalInformation*.json")) + sorted(
        fhir_dir.glob("practitionerInformation*.json")
    )
