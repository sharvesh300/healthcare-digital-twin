"""In-memory stand-ins for the live twin's database side (twin.streaming.store)."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from twin.streaming.bus import InProcessBus
from twin.streaming.manager import PatientTwinStateManager
from twin.streaming.state import Reading
from twin.streaming.store import IngestResult

T0 = datetime(2026, 10, 4, 14, 0, tzinfo=UTC)


class FakeLoader:
    def __init__(self):
        self.patients: dict[UUID, dict] = {}
        self.stored: dict[UUID, list[Reading]] = defaultdict(list)  # what the database holds
        self.loads = 0

    def add(self, readings: list[Reading] = ()) -> UUID:
        pid = uuid4()
        self.patients[pid] = {"patient_id": str(pid), "display_name": "Test Patient", "tags": []}
        self.stored[pid] = list(readings)
        return pid

    async def patient(self, patient_id):
        return self.patients.get(patient_id)

    async def readings(self, patient_id):
        self.loads += 1
        return list(self.stored[patient_id])

    async def recorded(self, patient_id, since, until, live=False):
        return [r for r in self.stored[patient_id] if since <= r.time <= until]

    async def series(self, patient_id, metrics, since, until):
        return {m: sorted((r.time, float(r.value)) for r in self.stored[patient_id]
                          if r.metric == m and since <= r.time <= until) for m in metrics}


class FakeStore:
    def __init__(self):
        self.saved = []

    async def save(self, patient_id, items, version):
        self.saved += [(patient_id, t, version) for t in items]

    async def history(self, patient_id, since, signal, limit):
        rows = [{"signal": str(t.signal), "time": t.time, "from": t.from_status, "to": t.to_status,
                 "value": t.value, "state_version": v} for p, t, v in self.saved if p == patient_id]
        return list(reversed(rows))[:limit]


class FakeIngestor:
    """Writes into FakeLoader.stored; device ids are assigned on pairing."""

    def __init__(self, loader: FakeLoader):
        self.loader = loader
        self.devices: dict[int, UUID] = {}

    async def pair(self, patient_id, kind):
        device_id = len(self.devices) + 1
        self.devices[device_id] = patient_id
        return {"device_id": device_id, "kind": str(kind), "model": f"Twin simulator Live {kind}"}

    async def write(self, events):
        result = IngestResult()
        for i, e in enumerate(events):
            pid = self.devices.get(e.device_id)
            if pid is None:
                result.rejected.append({"index": i, "reason": f"unknown device {e.device_id}"})
                continue
            if e.kind == "glucose":
                r = Reading(e.time, "glucose", float(e.glucose_mg_dl), "mg/dL", "live cgm")
            elif e.kind == "wearable":
                r = Reading(e.time, e.metric, e.value, None, "live watch")
            else:
                r = Reading(e.time, "sleep", str(e.stage), None, "live watch", e.until)
            if r in self.loader.stored[pid]:
                result.duplicates += 1
                continue
            self.loader.stored[pid].append(r)
            result.new[pid].append(r)
            result.accepted += 1
        return result


class WallClock:
    def __init__(self, now: datetime = T0):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def loader():
    return FakeLoader()


@pytest.fixture
def store():
    return FakeStore()


@pytest.fixture
def wall():
    return WallClock()


@pytest.fixture
def twin(loader, store, wall):
    return PatientTwinStateManager(loader, store, InProcessBus(queue_size=8), wall_clock=wall)
