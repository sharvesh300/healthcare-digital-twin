from datetime import time

import numpy as np
import pandas as pd
import pytest

from twin.sources import cgmacros

BIO = (
    "subject,Age,Gender,BMI,Body weight ,Height ,Self-identify ,A1c PDL (Lab),Fasting GLU - PDL (Lab),"
    "Insulin ,Triglycerides,Cholesterol,HDL,Non HDL ,LDL (Cal),VLDL (Cal),Cho/HDL Ratio,"
    "Collection time PDL (Lab),#1 Contour Fingerstick GLU,Time (t), #2 Contour Fingerstick GLU,Time (t),"
    "#3 Contour Fingerstick GLU,Time (t)\n"
    "3,59,F,26.9,157,64,Hispanic/Latino,6.5,118,17.4,154,190,74,116,800,400,2.6,7:25:00 AM,119,7:38,166,9:23,,\n"
    "12,52,M,30.2,200,68,\"Black, African American\",7.1,140,,,,,,,,,8:00:00 AM,,,,,,\n"
)


@pytest.fixture
def bio(tmp_path):
    path = tmp_path / "bio.csv"
    path.write_text(BIO)
    return cgmacros.read_bio(path)


def test_bio_units_and_measured_labs_only(bio):
    p = bio["003"]
    assert p.sex == "female" and p.age == 59
    assert p.labs["29463-7"] == pytest.approx(157 * 0.45359237, abs=0.01)  # lb -> kg
    assert p.labs["8302-2"] == pytest.approx(64 * 2.54)  # in -> cm
    assert p.hba1c == 6.5
    # derived columns (LDL 800 / VLDL 400 sentinels) are not carried as labs
    assert set(p.labs) == {"4548-4", "1558-6", "20448-7", "2093-3", "2085-9", "2571-8", "29463-7", "8302-2"}
    assert p.bmi == pytest.approx(26.9, abs=0.1)


def test_bio_missing_values_and_fingersticks(bio):
    assert bio["003"].lab_time == time(7, 25)
    assert bio["003"].fingersticks == [(time(7, 38), 119.0), (time(9, 23), 166.0)]
    p = bio["012"]
    assert "20448-7" not in p.labs and p.fingersticks == []
    assert p.race_ethnicity == "Black or African American"


def test_bio_schema_error(tmp_path):
    path = tmp_path / "bio.csv"
    path.write_text("subject,Age\n1,30\n")
    with pytest.raises(cgmacros.SchemaError):
        cgmacros.read_bio(path)


def _interpolated(native: pd.Series) -> pd.Series:
    grid = pd.date_range(native.index.min(), native.index.max(), freq="min")
    return native.reindex(grid).interpolate(method="time")


def test_native_samples_recovers_readings_including_flat_runs():
    t0 = pd.Timestamp("2020-05-01 10:00")
    values = [100, 104, 110, 110, 110, 110, 108, 120, 131, 131, 90]
    native = pd.Series(values, index=[t0 + pd.Timedelta(minutes=5 * i) for i in range(len(values))], dtype=float)
    recovered = cgmacros.native_samples(_interpolated(native), 5)
    pd.testing.assert_series_equal(recovered, native.astype("int64"), check_freq=False, check_names=False)


def test_native_samples_respects_gaps():
    t0 = pd.Timestamp("2020-05-01 10:00")
    a = pd.Series([90.0, 95.0, 100.0], index=[t0 + pd.Timedelta(minutes=15 * i) for i in range(3)])
    b = pd.Series([150.0, 140.0], index=[t0 + pd.Timedelta(hours=3, minutes=15 * i) for i in range(2)])
    series = pd.concat([_interpolated(a), pd.Series(np.nan, index=[t0 + pd.Timedelta(hours=2)]), _interpolated(b)])
    recovered = cgmacros.native_samples(series.sort_index(), 15)
    assert list(recovered.to_numpy()) == [90, 95, 100, 150, 140]


def test_sensor_csv_variants(tmp_path):
    path = tmp_path / "s.csv"
    path.write_text(
        "Unnamed: 0,Timestamp,Libre GL,Dexcom GL,HR,Calories (Activity),Intensity,Meal Type,Calories,Carbs,"
        "Protein,Fat,Fiber,Amount Consumed ,Image path\n"
        "0,2020-05-01 10:30:00,84.0,,56.0,1.05,0,,,,,,,,\n"
        "1,2020-05-01 10:31:00,84.5,,57.0,1.05,1,Snacks,110,20,3,2,1,100,photos/a.jpg\n"
        "2,2020-05-01 10:32:00,85.0,,58.0,1.05,2,,,,,,,,photos/b.jpg\n"
    )
    streams = cgmacros.parse_streams(cgmacros.read_sensor_csv(path))
    assert list(streams.fitbit["activity_level"]) == [0, 1, 2]
    assert streams.fitbit["mets"].isna().all()
    assert streams.meals.iloc[0]["meal_type"] == "snack"
    assert streams.meals.iloc[0]["pct_consumed"] == 100
    assert list(streams.photos) == ["photos/a.jpg", "photos/b.jpg"]
    assert streams.study_day_1.isoformat() == "2020-05-01"


def test_mets_are_divided_by_ten(tmp_path):
    path = tmp_path / "s.csv"
    path.write_text(
        "Timestamp,Libre GL,Dexcom GL,HR,Calories (Activity),METs,Meal Type,Calories,Carbs,Protein,Fat,Fiber,"
        "Image path\n2020-05-01 10:30:00,84,,56,1.0,13,,,,,,,\n"
    )
    assert cgmacros.parse_streams(cgmacros.read_sensor_csv(path)).fitbit["mets"].iloc[0] == pytest.approx(1.3)


@pytest.mark.parametrize("raw,expected", [("Breakfast", "breakfast"), ("snack 1", "snack"), ("Snacks", "snack"), ("", None)])
def test_meal_type(raw, expected):
    assert cgmacros.normalise_meal_type(raw) == expected
