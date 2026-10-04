import numpy as np
import pandas as pd

from twin.sources import nhanes


def test_clean_keeps_missing_and_restores_sas_zero():
    out = nhanes._clean(pd.Series([np.nan, 5.397605346934028e-79, 7.1]))
    assert np.isnan(out[0]) and out[1] == 0.0 and out[2] == 7.1


def test_blood_pressure_is_protocol_mean_ignoring_inaudible_diastolic():
    row = pd.Series({"BPXSY1": 130.0, "BPXSY2": 126.0, "BPXSY3": np.nan, "BPXDI1": 0.0, "BPXDI2": 80.0, "BPXDI3": 84.0})
    values = dict(nhanes.numeric_observations(row))
    assert values["8480-6"] == 128.0 and values["8462-4"] == 82.0


def test_smoking_status():
    assert nhanes.smoking_status(pd.Series({"SMQ020": 2.0}))[0] == "266919005"
    assert nhanes.smoking_status(pd.Series({"SMQ020": 1.0, "SMQ040": 3.0}))[0] == "8517006"
    assert nhanes.smoking_status(pd.Series({"SMQ020": 7.0})) is None


def test_t2d_onset_from_age_at_diagnosis():
    from datetime import date
    p = nhanes.Person(1, "G", "male", 60, None, date(2012, 2, 1), True, 50)
    (code, _, onset), = nhanes.conditions(p, pd.Series(dtype=float))
    assert code == "44054006" and onset.year == 2002
