import random
from datetime import UTC, datetime, timedelta

from twin.streaming.events import EventBatch
from twin.streaming.simulator import LOOP_GAP, Playback, Recorded

REC = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)  # recorded (twin) time
NOW = datetime(2026, 10, 4, 14, 0, tzinfo=UTC)  # start of the run
DEVICES = {"cgm": 1, "wearable": 2}


def recording() -> list[Recorded]:
    return ([Recorded(REC + timedelta(minutes=5 * i), "glucose", 100.0 + i) for i in range(4)]
            + [Recorded(REC + timedelta(minutes=i), "wearable", 70.0, metric="heart_rate") for i in range(16)]
            + [Recorded(REC, "sleep", "light", until=REC + timedelta(minutes=30))])


def play(**kw) -> Playback:
    items = sorted(recording(), key=lambda r: (r.time, r.kind != "sleep"))
    return Playback(items, NOW, DEVICES, rng=random.Random(1), **kw)


def test_recording_is_retimed_to_the_run_and_released_by_device_time():
    p = play()
    first = p.due(NOW + timedelta(minutes=5))
    assert [e["kind"] for e in first[:2]] == ["sleep", "glucose"]
    assert first[0]["time"] == NOW.isoformat() and first[0]["until"] == (NOW + timedelta(minutes=30)).isoformat()
    assert sum(e["kind"] == "glucose" for e in first) == 2  # t = 0 and 5 min
    assert max(e["time"] for e in first) == (NOW + timedelta(minutes=5)).isoformat()
    rest = p.due(NOW + timedelta(hours=1))
    assert len(first) + len(rest) == 21 and p.done


def test_events_are_valid_ingest_payloads():
    EventBatch.model_validate({"events": play().due(NOW + timedelta(hours=1))})


def test_drop_rate_loses_readings():
    assert len(play(drop_rate=1.0).due(NOW + timedelta(hours=1))) == 0
    assert 0 < len(play(drop_rate=0.5).due(NOW + timedelta(hours=1))) < 21


def test_late_readings_come_in_the_next_batch_out_of_order():
    p = play(late_rate=1.0)  # every reading is held back one batch
    assert p.due(NOW + timedelta(minutes=5)) == []
    late = p.due(NOW + timedelta(minutes=6))
    assert len(late) == 9  # sleep + 2 glucose + 6 heart rate from the first batch; minute 6 is held again
    assert max(e["time"] for e in late) == (NOW + timedelta(minutes=5)).isoformat()


def test_jitter_changes_glucose_and_heart_rate_only_within_limits():
    events = play(jitter=0.05).due(NOW + timedelta(hours=1))
    glucose = [e["glucose_mg_dl"] for e in events if e["kind"] == "glucose"]
    assert glucose != [100, 101, 102, 103] and all(20 <= g <= 600 for g in glucose)
    assert all(isinstance(g, int) for g in glucose)


def test_loop_restarts_after_the_end_with_a_gap():
    p = play(loop=True)
    p.due(NOW + timedelta(minutes=15))
    span = timedelta(minutes=15)  # last recorded - first recorded
    again = p.due(NOW + span + LOOP_GAP)
    assert any(e["time"] == (NOW + span + LOOP_GAP).isoformat() and e["kind"] == "sleep" for e in again)
    assert not p.done


def test_start_from_a_point_in_the_recording():
    items = [r for r in sorted(recording(), key=lambda r: r.time) if r.time >= REC + timedelta(minutes=10)]
    p = Playback(items, NOW, DEVICES, t0=REC + timedelta(minutes=10))
    first = p.due(NOW)
    assert {e["time"] for e in first} == {NOW.isoformat()}
    assert {e["kind"] for e in first} == {"glucose", "wearable"}


def test_no_device_for_a_kind_means_no_events_of_that_kind():
    items = sorted(recording(), key=lambda r: r.time)
    events = Playback(items, NOW, {"cgm": 1}).due(NOW + timedelta(hours=1))
    assert {e["kind"] for e in events} == {"glucose"}
