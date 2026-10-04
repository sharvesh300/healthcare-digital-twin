from datetime import timedelta
from uuid import uuid4

import pytest
from conftest import T0, FakeIngestor
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from twin.api.deps import ingestor, twin_manager
from twin.api.replay import app


@pytest.fixture
def client(twin, loader):
    fake = FakeIngestor(loader)
    app.dependency_overrides[twin_manager] = lambda: twin
    app.dependency_overrides[ingestor] = lambda: fake
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def glucose(device_id: int, minutes: float, value: int) -> dict:
    return {"kind": "glucose", "device_id": device_id, "time": (T0 + timedelta(minutes=minutes)).isoformat(),
            "glucose_mg_dl": value}


def test_get_unknown_patient_is_404(client):
    assert client.get(f"/patients/{uuid4()}").status_code == 404


def test_get_patient_returns_identity_and_state(client, loader):
    pid = loader.add()
    body = client.get(f"/patients/{pid}").json()
    assert body["patient"]["patient_id"] == str(pid)
    assert body["state"]["version"] == 0 and body["state"]["glucose"]["value"] is None


def test_websocket_snapshot_then_deltas(client, loader):
    pid = loader.add()
    device = client.post(f"/patients/{pid}/devices", json={"kind": "cgm"}).json()["device_id"]
    with client.websocket_connect(f"/ws/patients/{pid}/state") as ws:
        snapshot = ws.receive_json()
        assert (snapshot["type"], snapshot["version"]) == ("snapshot", 0)

        r = client.post("/ingest/events", json={"events": [glucose(device, 0, 150), glucose(device, 5, 190)]}).json()
        assert (r["accepted"], r["duplicates"], r["patients_updated"]) == (2, 0, 1)
        delta = ws.receive_json()
        assert (delta["type"], delta["version"]) == ("delta", 1)
        assert delta["changes"]["glucose.value"] == 190.0 and delta["changes"]["glucose.status"] == "high"
        assert delta["time"] == "2026-10-04T09:05:00-05:00"
        assert delta["changes"]["glucose.time"] == "2026-10-04T09:05:00-05:00"  # same zone as snapshots

        # Re-sent batch: stored already, so nothing reaches the twin.
        r = client.post("/ingest/events", json={"events": [glucose(device, 5, 190)]}).json()
        assert (r["accepted"], r["duplicates"], r["patients_updated"]) == (0, 1, 0)
        ws.send_json({"type": "resync"})
        again = ws.receive_json()  # the next message is the snapshot, not a delta
        assert (again["type"], again["version"]) == ("snapshot", 1)
        assert again["state"]["glucose"]["status"] == "high"


def test_websocket_unknown_patient_closes_4404(client):
    with client.websocket_connect(f"/ws/patients/{uuid4()}/state") as ws:
        assert ws.receive_json()["type"] == "error"
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 4404


def test_transitions_are_listed(client, loader):
    pid = loader.add()
    device = client.post(f"/patients/{pid}/devices", json={"kind": "cgm"}).json()["device_id"]
    client.get(f"/patients/{pid}")  # load the state
    client.post("/ingest/events", json={"events": [glucose(device, 0, 60)]})
    rows = client.get(f"/patients/{pid}/transitions").json()
    assert [(r["signal"], r["from"], r["to"]) for r in rows] == [("glucose", None, "low")]
    assert rows[0]["time"] == "2026-10-04T09:00:00-05:00"


def test_ingest_validates_events(client):
    bad = [glucose(1, 0, 700), {"kind": "sleep", "device_id": 1, "time": T0.isoformat(), "stage": "deep",
                                "until": T0.isoformat()}, {"kind": "glucose", "device_id": 1,
                                                           "time": "2026-10-04T09:00:00", "glucose_mg_dl": 100}]
    for event in bad:  # out of range, zero-length sleep, no UTC offset
        assert client.post("/ingest/events", json={"events": [event]}).status_code == 422


def test_unknown_device_is_rejected_not_fatal(client, loader):
    r = client.post("/ingest/events", json={"events": [glucose(99, 0, 100)]}).json()
    assert r["accepted"] == 0 and r["rejected"] == [{"index": 0, "reason": "unknown device 99"}]
