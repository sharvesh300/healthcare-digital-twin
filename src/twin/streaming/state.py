"""The live state of one patient's twin, and the pure rules that update it.

A `PatientTwinState` is an immutable value. `reduce(state, reading)` returns the next state;
`apply_readings(state, readings)` folds a batch and reports what changed (`StateDelta`):
the changed fields as flat paths ("glucose.value") and the status transitions
(glucose in_range -> high, sleep light -> deep, heart rate -> stale). No I/O here: the
manager (twin.streaming.manager) loads, stores and publishes.

Times are device times (twin time). Staleness is judged on the device clock, so a stream
replayed at 60x goes stale after 15 s of silence, not 15 min (see `Clock`).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from twin.models.base import TwinSignal


@dataclass(frozen=True)
class Reading:
    """One sensor reading as the twin sees it, whatever device or table it came from."""

    time: datetime
    metric: str  # "glucose", "sleep" or a ref.wearable_metric code
    value: float | str  # mg/dL, the metric's value, or the sleep stage
    unit: str | None = None
    source: str | None = None  # device model
    until: datetime | None = None  # sleep: end of the stage


# ── rules ────────────────────────────────────────────────────────────


def _incl(limit: float) -> float:
    """Upper limit that includes `limit` itself (bands compare value < limit)."""
    return math.nextafter(limit, math.inf)


@dataclass(frozen=True)
class Rules:
    """Display bands and freshness limits. Not alert or treatment thresholds."""

    tz: ZoneInfo = ZoneInfo("America/Chicago")  # for "today" (steps)
    # Glucose bands: international CGM consensus (Battelino 2019), as in ts.glucose_daily.
    glucose_bands: tuple[tuple[float, str], ...] = ((54, "very_low"), (70, "low"), (_incl(180), "in_range"),
                                                    (_incl(250), "high"))
    glucose_above: str = "very_high"
    # Trend: least-squares slope over the window, mg/dL per minute.
    trend_window: timedelta = timedelta(minutes=15)
    trend_min_points: int = 3
    trend_min_span: timedelta = timedelta(minutes=10)
    trend_steps: tuple[tuple[float, str], ...] = ((-2, "falling_fast"), (-1, "falling"), (1, "steady"),
                                                  (2, "rising"))
    trend_above: str = "rising_fast"
    heart_rate_bands: tuple[tuple[float, str], ...] = ((50, "low"), (_incl(100), "normal"))
    heart_rate_above: str = "elevated"
    spo2_bands: tuple[tuple[float, str], ...] = ((90, "low"), (95, "borderline"))
    spo2_above: str = "normal"
    mets_bands: tuple[tuple[float, str], ...] = ((1.5, "sedentary"), (3, "light"), (6, "moderate"))
    mets_above: str = "vigorous"
    activity_levels: tuple[str, ...] = ("sedentary", "light", "moderate", "vigorous")  # activity_level 0-3
    # A signal with no reading for this long (device time) is marked stale.
    stale_after: dict[str, timedelta] = field(default_factory=lambda: {
        "glucose": timedelta(minutes=15), "heart_rate": timedelta(minutes=10)})


RULES = Rules()


def band(value: float, bands: tuple[tuple[float, str], ...], above: str) -> str:
    """The name of the first band whose upper limit (exclusive) is above value."""
    for limit, name in bands:
        if value < limit:
            return name
    return above


def glucose_trend(recent: tuple[tuple[datetime, float], ...], rules: Rules = RULES) -> tuple[str | None, float | None]:
    """(trend, slope mg/dL/min) over the last `trend_window` of readings; (None, None) if too few."""
    if not recent:
        return None, None
    end = recent[-1][0]
    points = [(t, v) for t, v in recent if t >= end - rules.trend_window]
    if len(points) < rules.trend_min_points or end - points[0][0] < rules.trend_min_span:
        return None, None
    xs = [(t - end).total_seconds() / 60 for t, _ in points]
    ys = [v for _, v in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sum((x - mx) ** 2 for x in xs)
    return band(slope, rules.trend_steps, rules.trend_above), round(slope, 2)


# ── state ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Signal:
    """The latest value of one channel. status is a band/level/stage, "stale", or None."""

    value: float | str | None = None
    unit: str | None = None
    time: datetime | None = None
    source: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class Glucose(Signal):
    trend: str | None = None
    rate_mg_dl_min: float | None = None
    recent: tuple[tuple[datetime, float], ...] = ()  # readings in the trend window; not published


@dataclass(frozen=True)
class Sleep(Signal):
    until: datetime | None = None


@dataclass(frozen=True)
class Clock:
    """Maps wall-clock time to device time. A simulator replaying at 60x advances the device
    clock 60 s per wall second; `rate` is estimated from successive batches."""

    device_time: datetime
    wall: datetime
    rate: float = 1.0

    def now(self, wall: datetime) -> datetime:
        return self.device_time + (wall - self.wall) * self.rate

    def observe(self, device_time: datetime, wall: datetime) -> Clock:
        dt_wall = (wall - self.wall).total_seconds()
        rate = self.rate
        if dt_wall >= 0.5 and device_time > self.device_time:
            seen = (device_time - self.device_time).total_seconds() / dt_wall
            rate = min(max(0.5 * rate + 0.5 * seen, 0.01), 100_000.0)
        return Clock(max(device_time, self.device_time), wall, rate)


# Wearable metrics that are a plain latest-value signal (no status rules).
PLAIN_METRICS = ("respiration_rate", "hrv_rmssd", "skin_temp", "stress", "eda", "active_kcal")
STATUS_SIGNALS = {  # state field -> transition signal
    "glucose": TwinSignal.glucose, "heart_rate": TwinSignal.heart_rate, "activity": TwinSignal.activity,
    "sleep": TwinSignal.sleep, "spo2": TwinSignal.spo2,
}


@dataclass(frozen=True)
class PatientTwinState:
    patient_id: UUID
    version: int = 0
    as_of: datetime | None = None  # wall clock of the last published change
    streaming: bool = False  # live readings are arriving
    clock: Clock | None = None
    glucose: Glucose = Glucose()
    heart_rate: Signal = Signal()
    activity: Signal = Signal()
    steps_today: Signal = Signal()
    sleep: Sleep = Sleep()
    spo2: Signal = Signal()
    respiration_rate: Signal = Signal()
    hrv_rmssd: Signal = Signal()
    skin_temp: Signal = Signal()
    stress: Signal = Signal()
    eda: Signal = Signal()
    active_kcal: Signal = Signal()

    def to_dict(self, tz: ZoneInfo | None = None) -> dict[str, Any]:
        """JSON-ready snapshot (times as ISO strings in tz)."""
        out: dict[str, Any] = {"patient_id": str(self.patient_id), "version": self.version,
                               "as_of": _json(self.as_of, tz), "streaming": self.streaming}
        for name in SIGNAL_FIELDS:
            out[name] = {k: _json(v, tz) for k, v in asdict(getattr(self, name)).items() if k != "recent"}
        return out


SIGNAL_FIELDS = tuple(f.name for f in fields(PatientTwinState)
                      if f.name not in ("patient_id", "version", "as_of", "streaming", "clock"))


def _json(value: Any, tz: ZoneInfo | None) -> Any:
    if isinstance(value, datetime):
        return (value.astimezone(tz) if tz else value).isoformat()
    return value


def _newer(signal: Signal, reading: Reading) -> bool:
    return signal.time is None or reading.time >= signal.time


def _latest(signal: Signal, reading: Reading, value: float | str, status: str | None) -> Signal:
    return replace(signal, value=value, unit=reading.unit, time=reading.time, source=reading.source, status=status)


def _local_day(t: datetime, rules: Rules) -> date:
    return t.astimezone(rules.tz).date()


def reduce(state: PatientTwinState, r: Reading, rules: Rules = RULES) -> PatientTwinState:
    """The state after one reading. Readings older than a signal's latest update only the
    accumulators (glucose trend window, steps today), never the latest value."""
    s = state
    if r.metric == "glucose":
        g = s.glucose
        value = float(r.value)
        anchor = max(r.time, g.time) if g.time else r.time
        recent = tuple(sorted({*g.recent, (r.time, value)}))
        recent = tuple(p for p in recent if p[0] >= anchor - rules.trend_window)
        trend, rate = glucose_trend(recent, rules)
        if _newer(g, r):
            g = _latest(g, r, value, band(value, rules.glucose_bands, rules.glucose_above))
        s = replace(s, glucose=replace(g, recent=recent, trend=trend, rate_mg_dl_min=rate))
    elif r.metric == "heart_rate":
        if _newer(s.heart_rate, r):
            value = float(r.value)
            s = replace(s, heart_rate=_latest(s.heart_rate, r, value,
                                              band(value, rules.heart_rate_bands, rules.heart_rate_above)))
    elif r.metric in ("mets", "activity_level"):
        if _newer(s.activity, r):
            value = float(r.value)
            level = (band(value, rules.mets_bands, rules.mets_above) if r.metric == "mets"
                     else rules.activity_levels[min(max(int(value), 0), 3)])
            s = replace(s, activity=_latest(s.activity, r, value, level))
    elif r.metric == "steps":
        st = s.steps_today
        day = _local_day(r.time, rules)
        current = _local_day(st.time, rules) if st.time else None
        if current is None or day > current:
            s = replace(s, steps_today=_latest(st, r, float(r.value), None))
        elif day == current:  # same day: count it, even if it arrived late
            s = replace(s, steps_today=replace(st, value=float(st.value or 0) + float(r.value),
                                               time=max(st.time, r.time), source=r.source))
    elif r.metric == "sleep":
        if _newer(s.sleep, r):
            s = replace(s, sleep=replace(_latest(s.sleep, r, str(r.value), str(r.value)), until=r.until))
    elif r.metric == "spo2":
        if _newer(s.spo2, r):
            value = float(r.value)
            s = replace(s, spo2=_latest(s.spo2, r, value, band(value, rules.spo2_bands, rules.spo2_above)))
    elif r.metric in PLAIN_METRICS:
        signal = getattr(s, r.metric)
        if _newer(signal, r):
            s = replace(s, **{r.metric: _latest(signal, r, float(r.value), None)})
    # The sleep stage ends at `until`; a later reading with no new stage means the patient is up.
    if s.sleep.until is not None and r.time > s.sleep.until and s.sleep.status != "awake":
        s = replace(s, sleep=replace(s.sleep, value="awake", status="awake", until=None))
    return s


def mark_stale(state: PatientTwinState, now: datetime, rules: Rules = RULES) -> PatientTwinState:
    """Mark signals with no reading for longer than their limit (device time `now`)."""
    s = state
    for name, limit in rules.stale_after.items():
        signal = getattr(s, name)
        if signal.time is not None and signal.status != "stale" and now - signal.time > limit:
            changes: dict[str, Any] = {"status": "stale"}
            if isinstance(signal, Glucose):
                changes.update(trend=None, rate_mg_dl_min=None)
            s = replace(s, **{name: replace(signal, **changes)})
    return s


# ── deltas ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Transition:
    signal: TwinSignal
    time: datetime
    from_status: str | None
    to_status: str
    value: float | None

    def to_dict(self, tz: ZoneInfo | None = None) -> dict[str, Any]:
        return {"signal": str(self.signal), "time": _json(self.time, tz), "from": self.from_status,
                "to": self.to_status, "value": self.value}


@dataclass(frozen=True)
class StateDelta:
    state: PatientTwinState  # the state after the change (version not yet bumped)
    changes: dict[str, Any]  # flat path -> new JSON value
    transitions: tuple[Transition, ...]
    time: datetime | None  # device time of the latest reading in the change


def _flat(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(_flat(v, f"{prefix}{k}."))
        else:
            out[f"{prefix}{k}"] = v
    return out


def diff(old: PatientTwinState, new: PatientTwinState, tz: ZoneInfo | None = None) -> dict[str, Any]:
    """Changed fields as flat paths (JSON values, times in tz), excluding bookkeeping (version, as_of)."""
    a, b = _flat(old.to_dict(tz)), _flat(new.to_dict(tz))
    return {k: v for k, v in b.items() if a.get(k) != v and k not in ("version", "as_of")}


def transitions(old: PatientTwinState, new: PatientTwinState, time: datetime) -> list[Transition]:
    """Status changes between two states; `time` is the device time of the reading (or the
    staleness check) that caused them."""
    out = []
    for name, signal in STATUS_SIGNALS.items():
        before, after = getattr(old, name), getattr(new, name)
        if after.status is not None and before.status != after.status:
            value = after.value if isinstance(after.value, (int, float)) else None
            out.append(Transition(signal, time, before.status, after.status, value))
    if new.glucose.trend is not None and old.glucose.trend != new.glucose.trend:
        out.append(Transition(TwinSignal.glucose_trend, time, old.glucose.trend, new.glucose.trend,
                              new.glucose.rate_mg_dl_min))
    return out


def apply_readings(state: PatientTwinState, readings: list[Reading], rules: Rules = RULES,
                   now: datetime | None = None) -> StateDelta | None:
    """Fold readings (in time order) into the state, then mark stale signals as of `now`
    (device time; default: the latest reading). None if nothing visible changed."""
    s, found = state, []
    for r in sorted(readings, key=lambda r: (r.time, r.metric != "sleep")):
        nxt = reduce(s, r, rules)
        found += transitions(s, nxt, r.time)
        s = nxt
    latest = max((r.time for r in readings), default=None)
    at = now or latest
    if at is not None:
        nxt = mark_stale(s, at, rules)
        found += transitions(s, nxt, at)
        s = nxt
    return delta(state, s, found, latest or at, rules.tz)


def delta(old: PatientTwinState, new: PatientTwinState, found: list[Transition],
          time: datetime | None, tz: ZoneInfo | None = None) -> StateDelta | None:
    changes = diff(old, new, tz)
    if not changes:
        return None
    return StateDelta(new, changes, tuple(found), time)
