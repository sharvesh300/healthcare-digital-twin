"""Warnings on a glucose forecast: spikes and the forecast leaving the target range.

Pure rules. The glucose bands are the live twin's (twin.streaming.state.RULES, international
CGM consensus: 54 / 70 / 180 / 250 mg/dL), so the Predict tab and the Live tab agree.
These are display flags on a model estimate, not clinical alerts.

Per horizon, on the point forecast:
  very_high (> 250, danger), high (> 180), low (< 70), very_low (< 54, danger);
  spike: a rise of >= SPIKE_RISE from now by that horizon, or >= SPIKE_RATE mg/dL/min since the
  previous point (now, for the first horizon).
Only the 80 % band crosses a line while the point forecast stays in range:
  possible_high (band top > 180), possible_low (band bottom < 70), severity info.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from twin.streaming.state import RULES, band

SPIKE_RISE = 50.0  # mg/dL above the current glucose
SPIKE_RATE = 2.0  # mg/dL per minute between consecutive points (the live twin's "rising_fast")
HIGH, LOW = 180.0, 70.0
SEVERITY = {"danger": 0, "warning": 1, "info": 2}
RANGE_WARNINGS = {"very_high": "danger", "high": "warning", "low": "warning", "very_low": "danger"}


def glucose_band(value: float) -> str:
    return band(value, RULES.glucose_bands, RULES.glucose_above)


@dataclass(frozen=True)
class Point:
    horizon_min: int
    glucose: float
    low: float | None = None  # 80 % band
    high: float | None = None


@dataclass(frozen=True)
class Warning:
    kind: str
    severity: str  # danger | warning | info
    horizon_min: int
    glucose: float
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


def _range_message(kind: str, p: Point) -> str:
    line = {"very_high": "above 250", "high": "above 180", "low": "below 70", "very_low": "below 54"}[kind]
    return f"Forecast {p.glucose:.0f} mg/dL at +{p.horizon_min} min, {line}"


def horizon_warnings(now: float, points: list[Point]) -> list[list[Warning]]:
    """The warnings at each horizon, in the order of `points`."""
    out: list[list[Warning]] = []
    prev_t, prev_v = 0, now
    for p in points:
        found: list[Warning] = []
        b = glucose_band(p.glucose)
        if b in RANGE_WARNINGS:
            found.append(Warning(b, RANGE_WARNINGS[b], p.horizon_min, p.glucose, _range_message(b, p)))
        else:
            if p.high is not None and p.high > HIGH:
                found.append(Warning("possible_high", "info", p.horizon_min, p.glucose,
                                     f"Could pass 180 mg/dL by +{p.horizon_min} min (80 % range up to {p.high:.0f})"))
            if p.low is not None and p.low < LOW:
                found.append(Warning("possible_low", "info", p.horizon_min, p.glucose,
                                     f"Could fall below 70 mg/dL by +{p.horizon_min} min (80 % range down to {p.low:.0f})"))
        rise = p.glucose - now
        rate = (p.glucose - prev_v) / (p.horizon_min - prev_t)
        if rise >= SPIKE_RISE or rate >= SPIKE_RATE:
            found.append(Warning("spike", "warning", p.horizon_min, p.glucose,
                                 f"Rising about {rise:.0f} mg/dL within {p.horizon_min} min"))
        out.append(found)
        prev_t, prev_v = p.horizon_min, p.glucose
    return out


def summary(per_horizon: list[list[Warning]]) -> list[Warning]:
    """One warning per kind, at its earliest horizon; most severe first, then soonest."""
    first: dict[str, Warning] = {}
    for found in per_horizon:
        for w in found:
            first.setdefault(w.kind, w)
    return sorted(first.values(), key=lambda w: (SEVERITY[w.severity], w.horizon_min))
