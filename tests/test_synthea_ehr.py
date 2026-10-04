import json
from datetime import datetime

from twin.models.base import EncounterClass
from twin.sources.synthea_ehr import MedicationOrder, parse_bundle, regimen_episodes

RX = "http://www.nlm.nih.gov/research/umls/rxnorm"
SCT = "http://snomed.info/sct"


def _bundle(tmp_path):
    entries = [
        {"fullUrl": "urn:uuid:p1", "resource": {"resourceType": "Patient", "id": "p1"}},
        {"resource": {"resourceType": "Observation", "effectiveDateTime": "2026-01-01T09:00:00+00:00",
                      "code": {"coding": [{"code": "85354-9"}]},
                      "component": [
                          {"code": {"coding": [{"code": "8480-6"}]}, "valueQuantity": {"value": 132, "code": "mm[Hg]"}},
                          {"code": {"coding": [{"code": "8462-4"}]}, "valueQuantity": {"value": 84, "code": "mm[Hg]"}}]}},
        {"resource": {"resourceType": "Observation", "effectiveDateTime": "2026-01-01T09:00:00+00:00",
                      "code": {"coding": [{"code": "4548-4"}]}, "valueQuantity": {"value": 7.4, "code": "%"}}},
        {"resource": {"resourceType": "Observation", "effectiveDateTime": "2026-01-01T09:00:00+00:00",
                      "code": {"coding": [{"code": "72166-2"}]},
                      "valueCodeableConcept": {"coding": [{"system": SCT, "code": "266919005", "display": "Never smoker"}]}}},
        {"resource": {"resourceType": "Observation", "effectiveDateTime": "2026-01-01T09:00:00+00:00",
                      "code": {"coding": [{"code": "72514-3"}]}, "valueQuantity": {"value": 3, "code": "{score}"}}},
        {"resource": {"resourceType": "Condition", "onsetDateTime": "2015-03-01T00:00:00+00:00",
                      "code": {"coding": [{"system": SCT, "code": "44054006", "display": "Diabetes mellitus type 2"}]}}},
        {"fullUrl": "urn:uuid:med1", "resource": {"resourceType": "Medication",
                                                  "code": {"coding": [{"system": RX, "code": "106892"}]}}},
        {"resource": {"resourceType": "MedicationRequest", "id": "mr1", "status": "active",
                      "authoredOn": "2025-06-01T00:00:00+00:00", "medicationReference": {"reference": "urn:uuid:med1"}}},
        {"resource": {"resourceType": "MedicationRequest", "id": "mr2", "status": "stopped",
                      "authoredOn": "2024-01-01T00:00:00+00:00",
                      "medicationCodeableConcept": {"coding": [{"system": RX, "code": "860975", "display": "Metformin"}]},
                      "dosageInstruction": [{"timing": {"repeat": {"frequency": 2, "period": 1, "periodUnit": "d"}},
                                             "doseAndRate": [{"doseQuantity": {"value": 1}}]}]}},
        {"resource": {"resourceType": "Encounter", "id": "e1", "class": {"code": "AMB"},
                      "period": {"start": "2026-01-01T08:45:00+00:00", "end": "2026-01-01T09:15:00+00:00"}}},
    ]
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps({"resourceType": "Bundle", "entry": entries}))
    return path


def test_parse_bundle(tmp_path):
    ehr = parse_bundle(_bundle(tmp_path), {"8480-6", "8462-4", "4548-4", "72166-2"})
    assert sorted((n.loinc, n.value) for n in ehr.numeric) == [("4548-4", 7.4), ("8462-4", 84.0), ("8480-6", 132.0)]
    assert [(c.loinc, c.code) for c in ehr.coded] == [("72166-2", "266919005")]  # 72514-3 not requested
    assert [(c.code, c.onset_at.year) for c in ehr.conditions] == [("44054006", 2015)]
    products = {m.product_rxcui: m for m in ehr.medications}
    assert set(products) == {"106892", "860975"}  # one via a Medication resource in the bundle
    assert products["860975"].times_per_day == 2 and products["860975"].dose_quantity == 1
    assert [(e.encounter_class, e.encounter_id) for e in ehr.encounters] == [(EncounterClass.ambulatory, "e1")]


def test_regimen_episodes_merge_repeat_orders():
    t = lambda y, m: datetime(y, m, 1)
    orders = [
        MedicationOrder("a1", "860975", "Metformin", t(2020, 1), "stopped", 1, 2),
        MedicationOrder("a2", "860975", "Metformin", t(2022, 1), "active", 2, 2),
        MedicationOrder("b1", "314076", "Lisinopril", t(2021, 1), "stopped", 1, 1),
        MedicationOrder("b2", "314076", "Lisinopril", t(2023, 1), "stopped", 1, 1),
    ]
    eps = {e.product_rxcui: e for e in regimen_episodes(orders)}
    assert (eps["860975"].started_at, eps["860975"].ended_at, eps["860975"].dose_quantity) == (t(2020, 1), None, 2)
    assert (eps["314076"].started_at, eps["314076"].ended_at, eps["314076"].first_request_id) == (t(2021, 1), t(2023, 1), "b1")
