from datetime import date, datetime, timezone

import pytest

from twin.pipeline.bigideas import Candidate, match
from twin.sources import bigideas
from twin.sources.synthea import SyntheaPatient


def _write(tmp_path, sid="001"):
    (tmp_path / sid).mkdir()
    (tmp_path / "Demographics.csv").write_text("﻿ID,Gender,HbA1c\n1,FEMALE,5.9\n")
    (tmp_path / sid / f"Dexcom_{sid}.csv").write_text(
        "Index,Timestamp (YYYY-MM-DDThh:mm:ss),Event Type,Event Subtype,Patient Info,Device Info,Source Device ID,"
        "Glucose Value (mg/dL),Insulin Value (u)\n"
        "1,,FirstName,,2019,,,,\n"
        "13,2020-02-13 17:23:32,EGV,,,,iPhone G6,61.0,\n"
        "14,2020-02-13 17:28:32,EGV,,,,iPhone G6,Low,\n"
        "15,2020-02-13 17:33:32,EGV,,,,iPhone G6,58.0,\n")
    (tmp_path / sid / f"HR_{sid}.csv").write_text("﻿datetime, hr\n2/13/20 15:29,94\n2/13/20 15:29,96\n2/13/20 15:30,80\n")
    (tmp_path / sid / f"IBI_{sid}.csv").write_text(
        "datetime, ibi\n2020-02-13 15:33:22.059,0.828\n2020-02-13 15:33:22.934,0.875\n2020-02-13 15:34:00.000,2.9\n")
    (tmp_path / sid / f"TEMP_{sid}.csv").write_text(
        "datetime, temp\n2020-02-13 15:28:50.000,30.0\n2020-02-13 15:28:50.250,31.0\n2020-02-13 15:29:00.000,32.0\n")


def test_readers(tmp_path):
    _write(tmp_path)
    assert bigideas.read_demographics(tmp_path)[0] == bigideas.Participant("001", "female", 5.9)
    g = bigideas.read_dexcom(bigideas.path(tmp_path, "001", "Dexcom"))
    assert list(g) == [61.0, 40.0, 58.0]  # "Low" -> 40 (sensor floor)
    hr = bigideas.read_heart_rate(bigideas.path(tmp_path, "001", "HR"))
    assert list(hr) == [95.0, 80.0]
    ibi = bigideas.read_ibi(bigideas.path(tmp_path, "001", "IBI"))
    assert list(ibi) == [828.0, 875.0]  # 2900 ms is outside the plausible range
    temp = bigideas.read_minute_mean(bigideas.path(tmp_path, "001", "TEMP"), "temp", chunksize=2)
    assert list(temp) == [30.5, 32.0]


def _cand(pid, sex, group, a1c, age=55):
    p = SyntheaPatient(pid, f"{pid}.json", sex, date(1970, 1, 1), False, "G", "F", None, pid, None, None, None,
                       datetime(2026, 9, 1, tzinfo=timezone.utc), 28.0)
    return Candidate(p, group, a1c, age)


def test_matching_by_sex_group_and_nearest_hba1c():
    people = [bigideas.Participant("001", "female", 6.0), bigideas.Participant("002", "female", 5.5)]
    cands = [_cand("pre-a", "female", "prediabetes", 5.8), _cand("pre-b", "female", "prediabetes", 6.1),
             _cand("none-a", "female", "neither", None), _cand("male", "male", "prediabetes", 6.0)]
    m = {x.participant.subject_id: x.candidate.patient.patient_id for x in match(people, cands)}
    assert m == {"001": "pre-b", "002": "none-a"}


@pytest.mark.parametrize("n_candidates", [0])
def test_unmatched_when_no_candidate(n_candidates):
    assert match([bigideas.Participant("001", "male", 6.2)], []) == []
