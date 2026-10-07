from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from test_prediction import StubBundle, _inputs
from twin.api.prediction import forecast_store, gru_loader
from twin.api.replay import app
from twin.prediction.model import ModelUnavailable

PID = uuid4()
TZ = ZoneInfo("America/Chicago")


class FakeStore:
    calls: list = []

    async def load(self, patient_id, at):
        FakeStore.calls.append(at)
        if patient_id != PID:
            return None
        inputs = _inputs()
        inputs.patient_id = PID
        return inputs


def _broken():
    raise ModelUnavailable("glucose forecaster unavailable: no exported glucose forecaster in data/models")


@pytest.fixture
def client():
    FakeStore.calls = []
    bundle = StubBundle(delta=(10, 25, 40, 60))
    app.dependency_overrides[forecast_store] = FakeStore
    app.dependency_overrides[gru_loader] = lambda: (lambda: bundle)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_glucose_forecast(client):
    r = client.get(f"/patients/{PID}/predictions/glucose")
    assert r.status_code == 200
    body = r.json()
    assert body["patient_id"] == str(PID) and body["unavailable"] is None
    assert [f["horizon_min"] for f in body["forecast"]] == [15, 30, 45, 60]
    assert body["forecast"][-1] == {"horizon_min": 60, "time": "2026-09-30T15:32:00-05:00", "glucose": 210.0,
                                    "low": 200.0, "high": 222.0, "change": 60.0, "band": "high",
                                    "warnings": ["high", "spike"]}
    assert body["origin"]["time"] == "2026-09-30T14:32:00-05:00"  # clinic zone
    # same severity -> soonest first: high from +45 (190), spike at +60 (+60 mg/dL), then the info
    assert [(w["kind"], w["horizon_min"]) for w in body["warnings"]] == [("high", 45), ("spike", 60),
                                                                          ("possible_high", 30)]
    assert body["model"]["name"] == "gru"
    assert FakeStore.calls == [None]  # no `at`: the store starts from the latest reading


def test_at_without_an_offset_is_clinic_time(client):
    client.get(f"/patients/{PID}/predictions/glucose", params={"at": "2026-09-30T14:32:00"})
    client.get(f"/patients/{PID}/predictions/glucose", params={"at": "2026-09-30T19:32:00Z"})
    local, utc = FakeStore.calls
    assert local == datetime(2026, 9, 30, 14, 32, tzinfo=TZ) == utc
    assert local.utcoffset() == timedelta(hours=-5)


def test_unknown_patient_is_404(client):
    r = client.get(f"/patients/{uuid4()}/predictions/glucose")
    assert r.status_code == 404 and "unknown patient" in r.json()["detail"]


def test_missing_model_is_503_with_the_fix(client):
    app.dependency_overrides[gru_loader] = lambda: _broken
    r = client.get(f"/patients/{PID}/predictions/glucose")
    assert r.status_code == 503 and "no exported glucose forecaster" in r.json()["detail"]


def test_no_bundle_on_disk_is_503(tmp_path):
    from twin.prediction.model import gru_bundle

    with pytest.raises(ModelUnavailable, match="train-glucose-forecaster"):
        gru_bundle(tmp_path)
