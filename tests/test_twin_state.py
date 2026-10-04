from datetime import UTC, datetime, timedelta
from uuid import uuid4

from twin.models import TwinSignal
from twin.streaming.state import (
    RULES,
    Clock,
    PatientTwinState,
    Reading,
    apply_readings,
    band,
    glucose_trend,
    mark_stale,
    reduce,
)

T0 = datetime(2026, 10, 4, 14, 0, tzinfo=UTC)  # 09:00 in America/Chicago


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def glucose(minutes: float, value: float) -> Reading:
    return Reading(at(minutes), "glucose", value, "mg/dL", "Twin simulator Live CGM (simulated)")


def wear(minutes: float, metric: str, value: float) -> Reading:
    return Reading(at(minutes), metric, value, None, "watch")


def empty() -> PatientTwinState:
    return PatientTwinState(uuid4())


def test_glucose_bands_follow_the_consensus_ranges():
    b = lambda v: band(v, RULES.glucose_bands, RULES.glucose_above)  # noqa: E731
    assert [b(v) for v in (53.9, 54, 69.9, 70, 180, 180.1, 250, 250.1)] == [
        "very_low", "low", "low", "in_range", "in_range", "high", "high", "very_high"]


def test_glucose_trend_needs_enough_history():
    assert glucose_trend(((at(0), 100.0), (at(5), 110.0))) == (None, None)  # 2 points
    rising = tuple((at(m), 100.0 + 2.5 * m) for m in (0, 5, 10, 15))
    assert glucose_trend(rising) == ("rising_fast", 2.5)
    flat = tuple((at(m), 120.0) for m in (0, 5, 10))
    assert glucose_trend(flat) == ("steady", 0.0)


def test_a_reading_updates_value_band_and_trend():
    s = empty()
    for m, v in ((0, 150), (5, 160), (10, 172), (15, 186)):
        s = reduce(s, glucose(m, v))
    assert (s.glucose.value, s.glucose.status, s.glucose.time) == (186.0, "high", at(15))
    assert (s.glucose.trend, s.glucose.rate_mg_dl_min) == ("rising_fast", 2.4)


def test_late_reading_does_not_replace_the_latest_value():
    s = reduce(reduce(empty(), glucose(10, 120)), glucose(5, 60))
    assert s.glucose.value == 120.0 and s.glucose.time == at(10)
    assert (at(5), 60.0) in s.glucose.recent  # but it counts for the trend


def test_delta_reports_changes_and_transitions():
    s = reduce(empty(), glucose(0, 170))
    change = apply_readings(s, [glucose(5, 190)])
    assert change.changes["glucose.value"] == 190.0
    assert change.changes["glucose.status"] == "high"
    (t,) = [t for t in change.transitions if t.signal == TwinSignal.glucose]
    assert (t.from_status, t.to_status, t.value, t.time) == ("in_range", "high", 190.0, at(5))


def test_same_value_is_still_a_change_of_time_but_not_a_transition():
    s = reduce(empty(), glucose(0, 120))
    change = apply_readings(s, [glucose(5, 120)])
    assert set(change.changes) == {"glucose.time"}
    assert change.transitions == ()


def test_nothing_new_gives_no_delta():
    s = reduce(empty(), glucose(5, 120))
    assert apply_readings(s, [glucose(5, 120)]) is None


def test_every_band_crossing_in_a_batch_is_noted():
    s = reduce(empty(), glucose(0, 120))
    change = apply_readings(s, [glucose(5, 190), glucose(10, 150)])
    assert [(t.from_status, t.to_status) for t in change.transitions if t.signal == TwinSignal.glucose] == [
        ("in_range", "high"), ("high", "in_range")]


def test_signals_go_stale_and_recover():
    s = reduce(reduce(empty(), glucose(0, 120)), wear(0, "heart_rate", 70))
    stale = apply_readings(s, [], now=at(16))
    assert stale.state.glucose.status == "stale" and stale.state.heart_rate.status == "stale"
    assert {(str(t.signal), t.to_status) for t in stale.transitions} == {("glucose", "stale"), ("heart_rate", "stale")}
    back = apply_readings(stale.state, [glucose(20, 125)])
    assert back.state.glucose.status == "in_range"
    assert ("stale", "in_range") in [(t.from_status, t.to_status) for t in back.transitions]


def test_heart_rate_is_stale_after_ten_minutes_of_device_time():
    s = reduce(empty(), wear(0, "heart_rate", 70))
    assert mark_stale(s, at(10)).heart_rate.status == "normal"
    assert mark_stale(s, at(10.5)).heart_rate.status == "stale"


def test_activity_level_from_mets_or_intensity_code():
    assert reduce(empty(), wear(0, "mets", 1.2)).activity.status == "sedentary"
    assert reduce(empty(), wear(0, "mets", 4.0)).activity.status == "moderate"
    assert reduce(empty(), wear(0, "activity_level", 3)).activity.status == "vigorous"


def test_steps_add_up_within_the_local_day_and_reset_after_midnight():
    s = empty()
    for m, n in ((0, 100), (1, 50), (-30, 20)):  # the last one arrived late, same day
        s = reduce(s, wear(m, "steps", n))
    assert s.steps_today.value == 170.0
    s = reduce(s, Reading(datetime(2026, 10, 5, 5, 10, tzinfo=UTC), "steps", 30, None, "watch"))  # 00:10 Chicago
    assert s.steps_today.value == 30.0
    s = reduce(s, wear(2, "steps", 999))  # yesterday's reading after the reset: ignored
    assert s.steps_today.value == 30.0


def test_sleep_stage_then_awake_after_it_ends():
    s = reduce(empty(), Reading(at(0), "sleep", "deep", None, "watch", until=at(30)))
    assert (s.sleep.value, s.sleep.status) == ("deep", "deep")
    s = reduce(s, wear(30, "heart_rate", 60))  # at the boundary: still asleep
    assert s.sleep.status == "deep"
    s = reduce(s, wear(31, "heart_rate", 62))
    assert s.sleep.status == "awake" and s.sleep.until is None


def test_next_sleep_stage_at_the_same_time_wins_over_awake():
    s = reduce(empty(), Reading(at(0), "sleep", "deep", None, "watch", until=at(30)))
    change = apply_readings(s, [wear(30.5, "heart_rate", 60), Reading(at(30), "sleep", "rem", None, "watch", until=at(60))])
    assert change.state.sleep.status == "rem"


def test_spo2_band():
    assert reduce(empty(), wear(0, "spo2", 89)).spo2.status == "low"
    assert reduce(empty(), wear(0, "spo2", 93)).spo2.status == "borderline"
    assert reduce(empty(), wear(0, "spo2", 97)).spo2.status == "normal"


def test_snapshot_is_json_ready_and_hides_the_trend_buffer():
    s = reduce(empty(), glucose(0, 120))
    d = s.to_dict(RULES.tz)
    assert d["glucose"]["time"] == "2026-10-04T09:00:00-05:00"
    assert "recent" not in d["glucose"] and "clock" not in d


def test_clock_estimates_device_time_at_replay_speed():
    c = Clock(device_time=at(0), wall=T0)
    c = c.observe(at(60), T0 + timedelta(seconds=60))  # 60 s of wall time carried 60 min of readings
    c = c.observe(at(120), T0 + timedelta(seconds=120))
    assert 40 < c.rate < 61
    assert c.now(T0 + timedelta(seconds=121)) > at(120)
