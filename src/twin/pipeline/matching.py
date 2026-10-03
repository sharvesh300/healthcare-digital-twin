"""Pair each real CGMacros participant with a Synthea diabetic.

Rule: same sex, |age difference| <= max_age_diff (Synthea age taken at its last
encounter, i.e. "now" in the EHR timeline), then the nearest latest BMI. Assignment
is greedy without replacement, most-constrained participant first, so scarce
candidates go to the participants who need them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from twin.sources.cgmacros import Participant
from twin.sources.synthea import SyntheaPatient


@dataclass(frozen=True)
class Match:
    participant: Participant
    patient: SyntheaPatient
    age_diff: int
    bmi_diff: float


def candidates(p: Participant, cohort: list[SyntheaPatient], max_age_diff: int, tz: ZoneInfo) -> list[SyntheaPatient]:
    return [
        s
        for s in cohort
        if not s.deceased
        and s.latest_bmi is not None
        and s.sex == p.sex
        and abs(s.age_on(s.last_encounter_local_date(tz)) - p.age) <= max_age_diff
    ]


def match(
    participants: list[Participant], cohort: list[SyntheaPatient], max_age_diff: int, tz: ZoneInfo
) -> tuple[list[Match], list[Participant]]:
    pools = {p.subject_id: candidates(p, cohort, max_age_diff, tz) for p in participants}
    order = sorted(participants, key=lambda p: (len(pools[p.subject_id]), p.subject_id))

    used: set[str] = set()
    matches, unmatched = [], []
    for p in order:
        pool = [s for s in pools[p.subject_id] if s.patient_id not in used]
        if not pool or p.bmi is None:
            unmatched.append(p)
            continue

        def key(s: SyntheaPatient):
            age = s.age_on(s.last_encounter_local_date(tz))
            return (abs(s.latest_bmi - p.bmi), abs(age - p.age), s.patient_id)

        best = min(pool, key=key)
        used.add(best.patient_id)
        matches.append(
            Match(
                participant=p,
                patient=best,
                age_diff=best.age_on(best.last_encounter_local_date(tz)) - p.age,
                bmi_diff=round(best.latest_bmi - p.bmi, 1),
            )
        )
    matches.sort(key=lambda m: m.participant.subject_id)
    return matches, unmatched


def day_offset(m: Match, study_day_1: date, tz: ZoneInfo) -> int:
    """Days to add to source time so the sensor window starts the day after the
    patient's last EHR encounter."""
    start = m.patient.last_encounter_local_date(tz) + timedelta(days=1)
    return (start - study_day_1).days
