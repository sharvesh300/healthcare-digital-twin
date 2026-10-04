import numpy as np
import pandas as pd

from twin.ml import features, forecast, population

T0 = pd.Timestamp("2026-05-01 06:00", tz="UTC")


def _series(n: int = 48, gap_at: int | None = None) -> pd.DataFrame:
    times = [T0 + pd.Timedelta(minutes=5 * i) for i in range(n)]
    df = pd.DataFrame({
        "patient_id": "p1", "time": times, "glucose_mg_dl": np.linspace(100, 194, n),
        "glucose_sources": "both", "glucose_censored": False, "steps": np.nan, "heart_rate": 70.0,
        "met_minutes": 5.0, "activity_level": np.nan, "insulin_fast_units": 0.0, "insulin_basal_units": 0.0,
        "oral_doses": 0,
    })
    return df.drop(index=gap_at) if gap_at is not None else df


def test_labels_are_future_values_and_missing_across_gaps():
    s = features.add_labels(_series(gap_at=10))
    first = s.iloc[0]
    assert first.glucose_t30 == s.loc[s.time == T0 + pd.Timedelta(minutes=30), "glucose_mg_dl"].iloc[0]
    # 30 min after 06:20 is 06:50 (index 10), which is missing -> no label, not the next value
    assert np.isnan(s.loc[s.time == T0 + pd.Timedelta(minutes=20), "glucose_t30"].iloc[0])


def test_forecast_features_respect_the_grid():
    f = forecast.build_features(_series(gap_at=20)).set_index("time")
    at = T0 + pd.Timedelta(minutes=5 * 21)
    assert np.isnan(f.loc[at, "glucose_lag5"])  # the gap is not bridged
    assert f.loc[at, "glucose_lag10"] == _series().glucose_mg_dl[19]
    assert f.loc[T0 + pd.Timedelta(minutes=60), "met_minutes_30"] == 30.0  # 6 buckets x 5 MET-min
    assert np.isnan(f.loc[T0 + pd.Timedelta(minutes=60), "steps_60"])  # no steps recorded -> NaN, not 0
    assert f.loc[T0, "target_t30"] == f.loc[T0 + pd.Timedelta(minutes=30), "glucose"]


def test_population_prepare():
    static = pd.DataFrame([{
        "cohort": "nhanes", "hba1c": 7.2, "sex": "male", "smoking_status": "Smokes tobacco daily",
        "steps_per_valid_day": 6500, "valid_step_days": 3, "diabetes_diagnosed": False,
        "diabetes_duration_years": 4.0, **{c: False for c in population.DRUGS + population.CONDITIONS},
    }, {"cohort": "cgmacros", "hba1c": 7.0}])
    df = population.prepare(static)
    row = df.iloc[0]
    assert len(df) == 1 and row.male == 1 and row.current_smoker == 1
    assert np.isnan(row.steps_per_valid_day)  # < 4 valid days is not a reliable daily average
    assert row.diabetes_duration_years == 0  # undiagnosed: no duration
