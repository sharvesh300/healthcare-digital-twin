from datetime import timedelta
from uuid import uuid4

import pytest
from conftest import T0, FakeIngestor
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from twin.api.deps import ingestor, twin_manager
from twin.api.replay import app
from twin.streaming.replay import ReplayEngine
from twin.streaming.state import Reading


def g(minutes: float, value: float) -> Reading:
    return Reading(T0 + timedelta(minutes=minutes), "glucose", value, "mg/dL", "Fused CGM")


def hr(minutes: float, value: float) -> Reading:
    return Reading(T0 + timedelta(minutes=minutes), "heart_rate", value, "/min", "Fitbit Sense")


READINGS = [g(-10, 120), g(-5, 125), hr(-1, 70), g(0, 130), g(5, 150), g(10, 190), hr(10, 95), g(15, 200), g(20, 170)]
START, END = T0, T0 + timedelta(minutes=20)


def engine(**kw) -> ReplayEngine:
    return ReplayEngine(uuid4(), READINGS, START, END, **kw)


def test_seek_builds_the_state_at_the_start_from_the_warmup():
    e = engine()
    snap = e.seek(START)
    assert (snap["type"], snap["version"]) == ("snapshot", 0)
    assert snap["state"]["glucose"]["value"] == 130.0 and snap["state"]["heart_rate"]["value"] == 70.0
    assert snap["state"]["streaming"] is False
    assert [p[1] for p in snap["series"]["glucose"]] == [120.0, 125.0, 130.0]
    assert snap["replay"]["status"] == "paused" and snap["replay"]["cursor"] == "2026-10-04T09:00:00-05:00"


def test_play_advance_and_end():
    e = engine()
    e.seek(START)
    (started,) = e.play()
    assert started["version"] == 1 and started["changes"] == {"streaming": True}
    (step,) = e.advance(START + timedelta(minutes=12))
    assert step["version"] == 2 and step["changes"]["glucose.value"] == 190.0
    assert ("in_range", "high") in [(t["from"], t["to"]) for t in step["transitions"] if t["signal"] == "glucose"]
    assert e.progress()["status"] == "playing"
    (last,) = e.advance(START + timedelta(hours=5))  # clamped to the end; the replay pauses itself
    assert last["changes"]["streaming"] is False and last["changes"]["glucose.value"] == 170.0
    assert e.progress()["status"] == "ended" and e.cursor == END


def test_play_from_the_end_restarts_with_a_snapshot():
    e = engine()
    e.seek(END)
    (snap,) = e.play()
    assert snap["type"] == "snapshot" and snap["state"]["streaming"] is True
    assert snap["replay"]["cursor"] == "2026-10-04T09:00:00-05:00"


def test_seek_mid_window_has_the_state_and_recent_changes_as_of_then():
    e = engine()
    e.seek(START)
    snap = e.seek(START + timedelta(minutes=16))
    assert snap["state"]["glucose"]["value"] == 200.0 and snap["state"]["glucose"]["status"] == "high"
    assert snap["feed"][0]["time"] <= snap["replay"]["cursor"]
    assert snap["version"] == 1


def test_speed_is_clamped():
    e = engine()
    e.set_speed(0)
    assert e.speed == 1
    e.set_speed(10**9)
    assert e.speed == 3600


# ── WebSocket ────────────────────────────────────────────────────────


@pytest.fixture
def client(twin, loader):
    app.dependency_overrides[twin_manager] = lambda: twin
    app.dependency_overrides[ingestor] = lambda: FakeIngestor(loader)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_replay_socket_plays_to_the_end(client, loader):
    pid = loader.add(READINGS)
    url = f"/ws/patients/{pid}/state/replay?start={START.isoformat().replace('+', '%2B')}" \
          f"&end={END.isoformat().replace('+', '%2B')}&speed=3600&autoplay=true"
    with client.websocket_connect(url) as ws:
        snap = ws.receive_json()
        assert snap["type"] == "snapshot" and snap["replay"]["status"] == "playing"
        versions, values = [snap["version"]], []
        for _ in range(200):
            m = ws.receive_json()
            if m["type"] == "delta":
                versions.append(m["version"])
                values.append(m["changes"].get("glucose.value"))
            if m["type"] == "replay" and m["status"] == "ended":
                break
        assert versions == list(range(len(versions)))  # sequential, like the live stream
        assert 170.0 in values
        ws.send_json({"type": "seek", "to": (START + timedelta(minutes=10)).isoformat()})
        snap = ws.receive_json()
        assert snap["type"] == "snapshot" and snap["state"]["glucose"]["value"] == 190.0


def test_replay_socket_rejects_a_bad_window(client, loader):
    pid = loader.add(READINGS)
    url = f"/ws/patients/{pid}/state/replay?start={END.isoformat().replace('+', '%2B')}&end={START.isoformat().replace('+', '%2B')}"
    with client.websocket_connect(url) as ws:
        assert ws.receive_json()["type"] == "error"
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 4422


def test_live_snapshot_carries_chart_series_and_feed(client, loader):
    pid = loader.add([g(0, 150)])
    with client.websocket_connect(f"/ws/patients/{pid}/state") as ws:
        snap = ws.receive_json()
    assert snap["series"]["glucose"] == [["2026-10-04T09:00:00-05:00", 150.0]]
    assert snap["feed"] == []
