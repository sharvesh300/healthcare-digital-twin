from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from twin.api.record import record_store
from twin.api.replay import app
from twin.record.assemble import dosage
from twin.record.store import RecordData

PID = uuid4()
V1, V2, V3 = "00000000-0000-0000-0000-0000000000a1", "00000000-0000-0000-0000-0000000000a2", \
    "00000000-0000-0000-0000-0000000000a3"


def t(y, m, d, h=9):
    return datetime(y, m, d, h, tzinfo=UTC)


def visit(eid, start, hours=0.5, cls="ambulatory", type_="General examination", reason=None):
    return {"encounter_id": eid, "encounter_class": cls, "type": type_, "reason": reason, "started_at": start,
            "ended_at": start + timedelta(hours=hours), "source": "synthea", "is_synthetic": True}


def result(analyte, at, value=None, text=None, eid=None, source="synthea"):
    return {"analyte": analyte, "loinc": "x", "loinc_display": analyte, "category": "laboratory", "effective_at": at,
            "value_num": value, "value_text": text, "ucum_unit": None, "encounter_id": eid, "source": source,
            "is_synthetic": source == "synthea"}


def condition(concept_id, display, onset, abated=None, eid=None, kind="diagnosis", group=None):
    return {"concept_id": concept_id, "system": "sct", "code": str(concept_id), "display": display, "kind": kind,
            "condition_group": group, "condition_group_display": group and group.title(), "onset_at": onset,
            "abated_at": abated, "active": abated is None, "encounter_id": eid, "source": "synthea",
            "is_synthetic": True}


def med(regimen_id, rxcui, name, start, end=None, eid=None, product=None, drug_class=None, lowering=False,
        dose=None, unit=None, times=None, prn=False, product_rxcui="p"):
    return {"regimen_id": regimen_id, "rxcui": rxcui, "medication": name, "product_rxcui": product_rxcui,
            "product": product, "drug_class": drug_class, "drug_class_display": drug_class, "glucose_lowering": lowering,
            "started_at": start, "ended_at": end, "active": end is None, "dose_value": dose, "dose_unit": unit,
            "times_per_day": times, "as_needed": prn, "encounter_id": eid, "source": "synthea", "is_synthetic": True}


def record() -> RecordData:
    return RecordData(
        patient={"patient_id": str(PID), "display_name": "Test Patient", "sex": "female", "source": "cgmacros",
                 "tags": ["composite-patient"]},
        visits=[visit(V1, t(2020, 1, 10)), visit(V2, t(2022, 6, 1), hours=48, cls="inpatient", type_="Admission"),
                visit(V3, t(2024, 3, 5), reason="Hypertension")],
        results=[
            result("hba1c", t(2020, 1, 10), 6.1, eid=V1), result("hba1c", t(2024, 3, 5), 7.4, eid=V3),
            result("hba1c", t(2024, 3, 5), 7.0, eid=V3, source="cgmacros"),  # same time: real first in the store
            result("sbp", t(2024, 3, 5), 138, eid=V3), result("dbp", t(2024, 3, 5), 76, eid=V3),
            result("sbp", t(2020, 1, 10), 118, eid=V1), result("dbp", t(2020, 1, 10), 74, eid=V1),
            result("smoking_status", t(2024, 3, 5), text="Never smoked", eid=V3),
        ],
        conditions=[
            condition(1, "Acute bronchitis", t(2019, 1, 1), t(2019, 1, 10)),
            condition(1, "Acute bronchitis", t(2022, 6, 1), t(2022, 6, 3), eid=V2),
            condition(1, "Acute bronchitis", t(2024, 3, 5), eid=V3),
            condition(2, "Hypertension", t(2024, 3, 5), eid=V3, group="hypertension"),
            condition(3, "Unemployed", t(2020, 1, 10), kind="finding"),
        ],
        medications=[
            med(1, 860975, "metformin", t(2020, 1, 10), t(2024, 3, 5), eid=V1, product="Metformin 500 MG Oral Tablet",
                drug_class="biguanide", lowering=True, dose=500, unit="MG", times=2, product_rxcui="860975"),
            med(2, 860975, "metformin", t(2024, 3, 5), eid=V3, product="Metformin 1000 MG Oral Tablet",
                drug_class="biguanide", lowering=True, dose=1000, unit="MG", times=2, product_rxcui="861004"),
            med(3, 29046, "lisinopril", t(2024, 3, 5), eid=V3, drug_class="ace_inhibitor", times=1),
            med(4, 8782, "propofol", t(2022, 6, 1), t(2022, 6, 1, 11), eid=V2),
        ],
    )


class FakeRecordStore:
    async def load(self, patient_id, sections=None):
        return record() if patient_id == PID else None


@pytest.fixture
def client():
    app.dependency_overrides[record_store] = FakeRecordStore
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def get(client, path=""):
    r = client.get(f"/patients/{PID}/record{path}")
    assert r.status_code == 200, r.text
    return r.json()


def test_overview_shape(client):
    o = get(client)
    assert o["summary"]["medications_active"] == 2 and o["summary"]["glucose_lowering_active"] == 1
    assert o["summary"]["diagnoses_active"] == 2
    assert o["summary"]["last_visit"]["encounter_id"] == V3
    assert [h["measure"] for h in o["summary"]["headline"]] == ["hba1c", "blood_pressure"]
    assert o["medications"]["single_day"] == 1 and [m["medication"] for m in o["medications"]["items"]] == [
        "metformin", "lisinopril"]
    assert o["conditions"]["diagnoses"]["total"] == 2 and o["conditions"]["findings"]["total"] == 1
    assert [p["panel"] for p in o["tests"]["panels"]] == ["glycaemic", "vitals", "lifestyle"]
    assert o["visits"]["total"] == 3 and "CGMacros" in o["provenance"]["note"]


def test_unknown_patient_and_entries_are_404(client):
    assert client.get(f"/patients/{uuid4()}/record").status_code == 404
    for path in ("/tests/ldl", "/conditions/999", "/medications/1", f"/visits/{uuid4()}"):
        assert client.get(f"/patients/{PID}/record{path}").status_code == 404, path


def test_a_test_returns_every_result_with_flags(client):
    d = get(client, "/tests/hba1c")
    assert [r["values"]["hba1c"] for r in d["results"]] == [6.1, 7.4]  # one result per time
    assert [r["flag"] for r in d["results"]] == ["high", "high"]
    assert d["stats"]["count"] == 2 and d["stats"]["by_analyte"]["hba1c"]["max"] == 7.4
    assert d["results"][-1]["visit"]["encounter_id"] == V3
    assert [m["medication"] for m in d["related"]["medications"]] == ["metformin"]


def test_blood_pressure_pairs_systolic_and_diastolic(client):
    d = get(client, "/tests/blood_pressure")
    assert [r["values"] for r in d["results"]] == [{"sbp": 118, "dbp": 74}, {"sbp": 138, "dbp": 76}]
    assert [r["flag"] for r in d["results"]] == ["normal", "high"]
    assert d["measure"]["ranges"] == {"sbp": [None, 129], "dbp": [None, 79]}
    assert [c["display"] for c in d["related"]["diagnoses"]] == ["Hypertension"]
    assert [m["medication"] for m in d["related"]["medications"]] == ["lisinopril"]


def test_out_of_range_filter_and_coded_results(client):
    flagged = get(client, "/tests?flag=out_of_range")
    assert {m["measure"] for p in flagged["panels"] for m in p["measures"]} == {"hba1c", "blood_pressure"}
    smoking = get(client, "/tests/smoking_status")["results"][0]
    assert (smoking["text"], smoking["flag"]) == ("Never smoked", None)


def test_a_recurring_condition_returns_every_episode(client):
    c = get(client, "/conditions/1")
    assert c["condition"]["episodes"] == 3 and c["condition"]["active"]
    assert [e["duration_days"] for e in c["episodes"]] == [9, 2, None]
    assert [(e["visit"] or {}).get("encounter_id") for e in c["episodes"]] == [None, V2, V3]
    resolved = get(client, "/conditions?active=false")
    assert resolved["total"] == 0  # bronchitis is active again
    assert get(client, "/conditions?kind=finding")["items"][0]["display"] == "Unemployed"


def test_medication_episodes_and_dose_changes(client):
    m = get(client, "/medications/860975")
    assert m["medication"]["episodes"] == 2 and m["medication"]["dosage"]["text"] == "1000 MG · twice daily"
    assert [e["product"] for e in m["episodes"]] == ["Metformin 500 MG Oral Tablet", "Metformin 1000 MG Oral Tablet"]
    assert m["dose_changes"][0]["to"] == "Metformin 1000 MG Oral Tablet · 1000 MG · twice daily"
    assert [c["display"] for c in m["related"]["diagnoses"]] == ["Acute bronchitis", "Hypertension"]
    listed = get(client, "/medications")
    assert [x["medication"] for x in listed["single_day"]] == ["propofol"]
    assert get(client, "/medications?glucose_lowering=true")["total"] == 1


def test_visit_links_everything_recorded_at_it(client):
    v = get(client, f"/visits/{V3}")
    assert v["visit"]["counts"] == {"tests": 3, "diagnoses": 2, "medications": 2}
    assert [(p["panel"], [i["measure"] for i in p["items"]]) for p in v["tests"]] == [
        ("glycaemic", ["hba1c"]), ("vitals", ["blood_pressure"]), ("lifestyle", ["smoking_status"])]
    assert {c["display"] for c in v["diagnoses"]["recorded"]} == {"Acute bronchitis", "Hypertension"}
    assert {m["medication"] for m in v["medications"]["started"]} == {"metformin", "lisinopril"}
    assert [m["medication"] for m in v["medications"]["stopped"]] == ["metformin"]  # the 500 mg episode ended here
    assert v["previous"]["encounter_id"] == V2 and v["next"] is None
    inpatient = get(client, f"/visits/{V2}")
    assert inpatient["visit"]["duration_h"] == 48 and [c["display"] for c in inpatient["diagnoses"]["resolved"]] == []


def test_visits_page_with_a_cursor_and_filters(client):
    first = get(client, "/visits?limit=2")
    assert [v["encounter_id"] for v in first["items"]] == [V3, V2] and first["total"] == 3
    rest = get(client, f"/visits?limit=2&cursor={first['next_cursor']}")
    assert [v["encounter_id"] for v in rest["items"]] == [V1] and rest["next_cursor"] is None
    assert get(client, "/visits?class=inpatient")["total"] == 1 and get(client, "/visits?year=2020")["total"] == 1
    assert first["years"][0] == {"year": 2024, "count": 1}


def test_dosage_reads_naturally():
    base = {"dose_value": None, "dose_unit": None, "times_per_day": None, "as_needed": False}
    assert dosage({**base, "dose_value": 5.0, "dose_unit": "mg", "times_per_day": 1})["text"] == "5 mg · once daily"
    assert dosage({**base, "as_needed": True})["text"] == "as needed"
    assert dosage({**base, "times_per_day": 1 / 7})["text"] == "weekly"
    assert dosage(base)["text"] is None
