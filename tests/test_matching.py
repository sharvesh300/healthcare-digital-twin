from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from twin.pipeline.matching import day_offset, match
from twin.sources.cgmacros import Participant
from twin.sources.synthea import SyntheaPatient

TZ = ZoneInfo("America/Chicago")
LAST = datetime(2026, 8, 15, 15, 0, tzinfo=timezone.utc)


def participant(sid, sex, age, bmi):
    height = 170.0
    return Participant(sid, sex, age, None, {"29463-7": bmi * (height / 100) ** 2, "8302-2": height, "4548-4": 7.0}, None)


def synth(pid, sex, age, bmi, deceased=False):
    return SyntheaPatient(
        patient_id=pid, bundle_file=f"{pid}.json", sex=sex, birth_date=date(2026 - age, 1, 1), deceased=deceased,
        given_name="G", family_name="F", name_prefix=None, mrn=pid, address_city=None, address_state=None,
        address_postal=None, last_encounter_end=LAST, latest_bmi=bmi,
    )


def test_same_sex_age_window_nearest_bmi():
    cohort = [synth("m1", "male", 50, 30.0), synth("f-far-age", "female", 60, 30.0),
              synth("f-near", "female", 52, 31.0), synth("f-nearest", "female", 48, 30.2)]
    matches, unmatched = match([participant("001", "female", 50, 30.0)], cohort, 5, TZ)
    assert not unmatched
    assert matches[0].patient.patient_id == "f-nearest"
    assert matches[0].age_diff == -2


def test_no_reuse_and_most_constrained_first():
    # "002" can only use "a"; "001" could use either. Greedy by scarcity gives both a match.
    cohort = [synth("a", "female", 50, 30.0), synth("b", "female", 55, 35.0)]
    people = [participant("001", "female", 52, 30.0), participant("002", "female", 46, 30.0)]
    matches, unmatched = match(people, cohort, 5, TZ)
    assert not unmatched
    assert {m.participant.subject_id: m.patient.patient_id for m in matches} == {"001": "b", "002": "a"}


def test_deceased_and_out_of_window_excluded():
    cohort = [synth("dead", "male", 50, 30.0, deceased=True), synth("old", "male", 70, 30.0)]
    matches, unmatched = match([participant("001", "male", 50, 30.0)], cohort, 5, TZ)
    assert not matches and [p.subject_id for p in unmatched] == ["001"]


def test_day_offset_starts_day_after_last_encounter():
    m, _ = match([participant("001", "male", 50, 30.0)], [synth("x", "male", 50, 30.0)], 5, TZ)
    assert day_offset(m[0], date(2020, 5, 1), TZ) == (date(2026, 8, 16) - date(2020, 5, 1)).days
