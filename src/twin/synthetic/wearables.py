"""Rule-based wearable generator (version twin-wearables-1). SYNTHETIC DATA.

Fills channels the real devices did not record, in a Garmin-like shape:
  sleep stages, SpO2, respiration rate, stress score, nightly HRV (RMSSD).

Design rules
  * Driven by the patient's own record so the twin stays coherent: age, sex, BMI, sleep
    apnoea and COPD (from the conditions), and the patient's REAL minute heart rate. The main
    sleep window is placed where real heart rate is lowest; stress follows real heart rate.
  * Never overwrites real data: HRV is generated only for patients without real inter-beat
    intervals; nothing here replaces CGM, heart rate or activity.
  * Never linked to glucose, so no sleep/SpO2 -> glucose effect can be "discovered" in it.
  * Deterministic: one random stream per patient (seeded from the patient id + version).

Parameters are rounded literature-typical values, not fitted to data:
  awake SpO2 ~96-98 % falling with age, BMI and COPD; sleep ~1 point lower; oxygen
  desaturation index ~2/h without apnoea and 12 / 22 / 35 per hour for mild / moderate /
  severe apnoea (severity from BMI); sleep 7.2 h falling with age; deep sleep share
  falling with age; respiration 12-20/min; nightly RMSSD ~45 ms at 40 falling with age.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from twin.models.base import SleepStage

VERSION = "twin-wearables-1"
AWAKE, LIGHT, DEEP, REM = SleepStage.awake, SleepStage.light, SleepStage.deep, SleepStage.rem
STAGE_RESP = {LIGHT: 14.2, DEEP: 13.2, REM: 15.0}
DESAT_WEIGHT = {LIGHT: 1.0, DEEP: 0.6, REM: 1.5}


@dataclass(frozen=True)
class Profile:
    patient_id: str
    age: int
    sex: str
    bmi: float | None
    sleep_apnea: bool
    copd: bool
    dysglycaemia: bool  # T2D or prediabetes (lower HRV)
    has_real_hrv: bool


@dataclass
class Generated:
    sleep: list[tuple[datetime, datetime, SleepStage]] = field(default_factory=list)
    samples: dict[str, pd.Series] = field(default_factory=dict)  # metric code -> values by time


def _rng(profile: Profile) -> np.random.Generator:
    seed = int(hashlib.sha256(f"{VERSION}/{profile.patient_id}".encode()).hexdigest()[:16], 16)
    return np.random.default_rng(seed)


def _odi(profile: Profile) -> float:
    """Oxygen desaturation events per hour of sleep."""
    if not profile.sleep_apnea:
        return 2.0
    bmi = profile.bmi or 28
    return 35.0 if bmi >= 35 else 22.0 if bmi >= 30 else 12.0


def _stages(rng: np.random.Generator, minutes: int, profile: Profile) -> np.ndarray:
    """Minute-by-minute stages for one sleep period: ~90-min cycles, deep sleep front-loaded
    and declining with age, REM growing through the night, awakenings."""
    deep_base = float(np.clip(0.35 - 0.004 * (profile.age - 20), 0.12, 0.35))
    stages = np.empty(minutes, dtype=object)
    pos, cycle = 0, 0
    while pos < minutes:
        length = int(np.clip(rng.normal(90, 10), 70, 110))
        deep = deep_base * max(0.0, 1 - 0.25 * cycle)
        rem = 0.25 * min(1.0, 0.4 + 0.3 * cycle)
        light_each = (1 - deep - rem) / 2
        for stage, share in ((LIGHT, light_each), (DEEP, deep), (LIGHT, light_each), (REM, rem)):
            n = int(round(share * length))
            stages[pos:pos + n] = stage
            pos += n
        cycle += 1
    stages[pos:] = LIGHT
    stages[stages == None] = LIGHT  # noqa: E711 (rounding gaps)
    onset = int(rng.integers(5, 21))
    stages[:onset] = AWAKE
    n_wake = rng.poisson(1.5 + 2.5 * profile.sleep_apnea + 0.02 * max(profile.age - 40, 0))
    for _ in range(n_wake):
        at, dur = int(rng.integers(onset, minutes)), int(rng.integers(2, 9))
        stages[at:at + dur] = AWAKE
    return stages[:minutes]


def _segments(start: pd.Timestamp, stages: np.ndarray) -> list[tuple[datetime, datetime, SleepStage]]:
    out, seg_start = [], 0
    for i in range(1, len(stages) + 1):
        if i == len(stages) or stages[i] != stages[seg_start]:
            out.append(((start + pd.Timedelta(minutes=seg_start)).to_pydatetime(),
                        (start + pd.Timedelta(minutes=i)).to_pydatetime(), stages[seg_start]))
            seg_start = i
    return out


def _sleep_start(rng, night: date, hours: float, tz: ZoneInfo, heart_rate: pd.Series | None, age: int) -> pd.Timestamp:
    """Bedtime: the 15-min step between 21:00 and 01:30 where real heart rate over the sleep
    window is lowest (needs >= 50 % coverage); otherwise an age-based rule."""
    base = pd.Timestamp(datetime.combine(night, time(21, 0)), tz=tz)
    candidates = [base + pd.Timedelta(minutes=15 * k) for k in range(19)]
    if heart_rate is not None and not heart_rate.empty:
        scored = []
        for c in candidates:
            window = heart_rate[c: c + pd.Timedelta(hours=hours)]
            if len(window) >= 0.5 * hours * 60:
                scored.append((float(window.mean()), c))
        if scored:
            return min(scored)[1]
    rule = base + pd.Timedelta(minutes=105 - max(age - 40, 0) + rng.normal(0, 40))
    return rule.floor("min")


def generate(profile: Profile, start: date, end: date, tz: ZoneInfo,
             heart_rate: pd.Series | None = None, active: pd.Series | None = None) -> Generated:
    """Synthetic channels for the nights/days in [start, end], in the patient's local tz.
    heart_rate: real per-minute HR (tz-aware index); active: per-minute bool (exercising)."""
    rng = _rng(profile)
    out = Generated()
    bmi = profile.bmi or 28.0
    spo2_awake = (97.4 - 0.04 * max(profile.age - 40, 0) - 0.06 * max(bmi - 30, 0)
                  - 2.5 * profile.copd + rng.normal(0, 0.4))
    hrv_patient = rng.normal(0, 0.15)
    hr = heart_rate.sort_index() if heart_rate is not None else None
    lo = pd.Timestamp(datetime.combine(start, time(0)), tz=tz)
    hi = pd.Timestamp(datetime.combine(end, time(23, 59)), tz=tz)
    if hr is not None and not hr.empty:  # restrict to the real recording window
        lo, hi = max(lo, hr.index.min().floor("min")), min(hi, hr.index.max().ceil("min"))

    sleep_minutes: dict[pd.Timestamp, SleepStage] = {}
    spo2, resp, stress, hrv = {}, {}, {}, {}
    night = start - timedelta(days=1)
    while night <= end:
        hours = float(np.clip(rng.normal(7.2 - 0.015 * (profile.age - 40) - 0.3 * profile.sleep_apnea, 0.6), 4.5, 9.5))
        s = _sleep_start(rng, night, hours, tz, hr, profile.age)
        minutes = int(hours * 60)
        if s >= lo and s + pd.Timedelta(minutes=minutes) <= hi:
            stages = _stages(rng, minutes, profile)
            out.sleep += _segments(s, stages)
            times = [s + pd.Timedelta(minutes=i) for i in range(minutes)]
            asleep = [t for t, st in zip(times, stages) if st != AWAKE]
            for t, st in zip(times, stages):
                sleep_minutes[t] = st
            # SpO2 every sleeping minute, with desaturation events. An event pulls SpO2 down *to*
            # a nadir (overlapping events do not add up) and recovers within ~3 minutes.
            sleep_base = spo2_awake - 0.8
            base = {t: sleep_base - (0.3 if sleep_minutes[t] == REM else 0) + rng.normal(0, 0.5) for t in asleep}
            if asleep:
                weights = np.array([DESAT_WEIGHT[sleep_minutes[t]] for t in asleep])
                n_events = min(rng.poisson(_odi(profile) * len(asleep) / 60), len(asleep) // 3)
                severe = _odi(profile) >= 35
                for idx in rng.choice(len(asleep), size=n_events, replace=False, p=weights / weights.sum()):
                    depth = rng.uniform(3, 6) + (2 if severe else 0)
                    for k, factor in enumerate((0.6, 1.0, 0.4)):
                        if idx + k < len(asleep):
                            t = asleep[idx + k]
                            base[t] = min(base[t], sleep_base - depth * factor + rng.normal(0, 0.3))
                            resp[t] = -2.5  # marker: lower breathing during the event
            for t, v in base.items():
                spo2[t] = v
            # Nightly HRV at wake time, only when no real inter-beat data exist
            if not profile.has_real_hrv:
                ln = np.log(45) - 0.017 * (profile.age - 40) - 0.12 * profile.dysglycaemia - 0.10 * profile.sleep_apnea \
                    + hrv_patient + rng.normal(0, 0.12)
                hrv[times[-1]] = float(np.exp(ln))
        night += timedelta(days=1)

    # Awake hours: SpO2 spot checks every 15 min, respiration each worn minute, stress every 3 min.
    rest_hr = None
    if hr is not None and not hr.empty:
        awake_hr = hr[[t not in sleep_minutes for t in hr.index]]
        rest_hr = float(np.percentile(awake_hr, 5)) if len(awake_hr) else float(hr.min())
    minutes_range = hr.index if hr is not None and not hr.empty else pd.date_range(lo, hi, freq="min")
    for t in minutes_range:
        stage = sleep_minutes.get(t)
        h = float(hr[t]) if hr is not None and t in hr.index else None
        if stage is None or stage == AWAKE:
            r = 15.5 + (0.06 * (h - rest_hr) if h is not None and rest_hr is not None else 0) + rng.normal(0, 1.0)
            resp[t] = r
            if t.minute % 15 == 0:
                spo2[t] = spo2_awake + rng.normal(0, 0.6)
            exercising = bool(active[t]) if active is not None and t in active.index else False
            if t.minute % 3 == 0 and h is not None and rest_hr is not None and not exercising:
                stress[t] = 12 + 2.0 * (h - rest_hr) + rng.normal(0, 6)
        else:
            dip = resp.get(t, 0.0)  # -2.5 during a desaturation event
            resp[t] = STAGE_RESP[stage] + dip + rng.normal(0, 0.6)

    out.samples = {
        "spo2": pd.Series(spo2).sort_index().clip(70, 100).round(),
        "respiration_rate": pd.Series(resp).sort_index().clip(8, 30).round(1),
        "stress": pd.Series(stress, dtype=float).sort_index().clip(0, 99).round(),
        "hrv_rmssd": pd.Series(hrv, dtype=float).sort_index().round(1),
    }
    return out
