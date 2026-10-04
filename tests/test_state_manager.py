import asyncio
from datetime import timedelta

import pytest
from conftest import T0

from twin.models import TwinSignal
from twin.streaming.manager import UnknownPatient
from twin.streaming.state import Reading


def g(minutes: float, value: float) -> Reading:
    return Reading(T0 + timedelta(minutes=minutes), "glucose", value, "mg/dL", "live cgm")


def steps(minutes: float, n: float) -> Reading:
    return Reading(T0 + timedelta(minutes=minutes), "steps", n, "{steps}", "live watch")


async def test_load_rebuilds_from_the_database_and_marks_old_signals_stale(twin, loader, wall):
    pid = loader.add([g(-60, 110)])  # an hour before the wall clock
    state = await twin.load(pid)
    assert state.version == 0 and not state.streaming
    assert (state.glucose.value, state.glucose.status) == (110.0, "stale")


async def test_unknown_patient(twin):
    from uuid import uuid4

    with pytest.raises(UnknownPatient):
        await twin.get(uuid4())


async def test_handle_applies_updates_and_publishes_with_sequential_versions(twin, loader, store):
    pid = loader.add([g(0, 170)])
    await twin.get(pid)
    async with twin.subscribe(pid) as sub:
        first = await twin.handle(pid, [g(5, 190)])
        second = await twin.handle(pid, [g(10, 200)])
        m1, m2 = await sub.get(), await sub.get()
    assert first and second
    assert (m1["type"], m1["version"], m2["version"]) == ("delta", 1, 2)
    assert m1["changes"]["glucose.status"] == "high" and m1["changes"]["streaming"] is True
    assert m1["transitions"][0] | {"time": None} == {"signal": "glucose", "time": None, "from": "in_range",
                                                     "to": "high", "value": 190.0}
    assert [(str(t.signal), t.to_status, v) for _, t, v in store.saved if t.signal == TwinSignal.glucose] == [
        ("glucose", "high", 1)]
    assert (await twin.get(pid)).version == 2


async def test_no_visible_change_publishes_nothing(twin, loader):
    pid = loader.add([g(5, 120)])
    await twin.get(pid)
    assert await twin.handle(pid, [g(10, 120)])  # streaming starts, the time moves
    async with twin.subscribe(pid) as sub:
        assert await twin.handle(pid, [g(10, 120)]) is None
        assert twin.version(pid) == 1
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(sub.get(), 0.05)


async def test_first_batch_for_an_unloaded_patient_is_not_counted_twice(twin, loader):
    pid = loader.add()
    new = [steps(0, 100), steps(1, 50)]
    loader.stored[pid] += new  # ingestion stored them before the manager saw them
    assert await twin.handle(pid, new) is None
    state = await twin.get(pid)
    assert state.steps_today.value == 150.0 and state.streaming


async def test_one_batch_is_one_delta(twin, loader):
    pid = loader.add([g(0, 120)])
    await twin.get(pid)
    async with twin.subscribe(pid) as sub:
        await twin.handle(pid, [g(5, 125), g(10, 130), g(15, 135)])
        message = await sub.get()
    assert message["version"] == 1 and message["changes"]["glucose.value"] == 135.0


async def test_tick_marks_stale_on_the_device_clock_and_ends_streaming(twin, loader, wall):
    pid = loader.add([g(0, 120)])
    await twin.get(pid)
    # A simulator at 60x: one wall second carries one device minute.
    for i in range(1, 6):
        wall.advance(1)
        await twin.handle(pid, [g(5 * i, 120 + i)])
    state = await twin.get(pid)
    assert state.glucose.status == "in_range" and state.streaming

    wall.advance(20)  # silence: ~20 device minutes at the learned rate
    async with twin.subscribe(pid) as sub:
        await twin.tick()
        message = await sub.get()
    assert message["changes"]["glucose.status"] == "stale"
    assert {"signal": "glucose", "from": "in_range", "to": "stale"}.items() <= message["transitions"][0].items()

    wall.advance(60)
    await twin.tick()
    assert not (await twin.get(pid)).streaming


async def test_slow_subscriber_gets_a_resync_marker(twin, loader):
    pid = loader.add([g(0, 100)])
    await twin.get(pid)
    async with twin.subscribe(pid) as sub:
        for i in range(1, 20):  # queue_size=8 in the fixture
            await twin.handle(pid, [g(5 * i, 100 + i)])
        assert (await sub.get())["type"] == "resync"


async def test_idle_states_are_evicted_and_reloaded(twin, loader, wall):
    pid = loader.add([g(0, 100)])
    await twin.get(pid)
    async with twin.subscribe(pid):
        wall.advance(11 * 60)
        await twin.tick()
        assert twin.version(pid) == 0  # watched: kept
    await twin.tick()
    assert twin.version(pid) is None
    loads = loader.loads
    await twin.get(pid)
    assert loader.loads == loads + 1
