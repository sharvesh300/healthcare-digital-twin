from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from twin.ml.bench import neural
from twin.ml.bench.neural import Scaling
from twin.prediction import assemble, model, rules
from twin.prediction.store import MACROS, ForecastInputs, real_age

TZ = ZoneInfo("America/Chicago")
HORIZONS = [15, 30, 45, 60]
SCALING = Scaling({"glucose_in": (140.0, 40.0), "hr": (80.0, 15.0), "active_kcal": (9.0, 6.0)},
                  [48.0, 0.4, 31.0, 6.1, 120.0], [12.0, 0.5, 6.6, 0.9, 30.0])
STATIC = {"age": 50.0, "male": 0.0, "bmi": 28.0, "hba1c": 6.6, "fasting_glucose": 130.0}


class StubBundle:
    """Predicts a fixed change per horizon; records the windows it was given."""

    def __init__(self, delta=(5.0, 10.0, 15.0, 20.0)):
        self.delta, self.horizons, self.scaling, self.seen = np.array(delta), HORIZONS, SCALING, []
        self.meta = {"model": {"version": "gru-test"}, "training": {"participants": 45},
                     "outputs": {"band": {"level": 0.8}},
                     "evaluation": {"model": {str(h): {"rmse": 10.0, "band_coverage": 0.84} for h in HORIZONS}}}

    def predict(self, x, s, now):
        self.seen.append((x.copy(), s.copy()))
        return now[:, None] + self.delta

    def band(self):
        return np.full(4, -10.0), np.full(4, 12.0)


def _inputs(hours=6.0, end_value=150.0, source="cgmacros", gap=None, at_shift=timedelta(0), after_values=None):
    end = pd.Timestamp("2026-09-30 14:32", tz=TZ)
    t = pd.date_range(end - pd.Timedelta(hours=hours), end, freq="5min")
    g = pd.Series(np.linspace(end_value - 20, end_value, len(t)), index=t)
    if gap is not None:
        g = g[(g.index < gap[0]) | (g.index > gap[1])]
    minutes = pd.date_range(end - pd.Timedelta(hours=4), end, freq="min")
    after_t = pd.date_range(end + pd.Timedelta(minutes=5), periods=12, freq="5min")
    after = pd.Series(after_values if after_values is not None else np.full(12, 160.0), index=after_t)
    meals = pd.DataFrame({"meal_type": ["lunch"], **{k: [40.0] for k in MACROS}},
                         index=pd.DatetimeIndex([end - pd.Timedelta(minutes=50)]))
    return ForecastInputs(uuid4(), source, (end + at_shift).to_pydatetime(), g, after,
                          pd.Series(75.0, index=minutes), pd.Series(1.0, index=minutes), meals, dict(STATIC))


# ── rules ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("value, band", [(53.9, "very_low"), (54, "low"), (69.9, "low"), (70, "in_range"),
                                         (180, "in_range"), (180.1, "high"), (250, "high"), (250.1, "very_high")])
def test_bands_match_the_live_twin(value, band):
    assert rules.glucose_band(value) == band


def test_spike_by_total_rise_and_by_rate():
    by_rise = rules.horizon_warnings(100, [rules.Point(15, 120), rules.Point(30, 140), rules.Point(45, 152)])
    assert [[w.kind for w in found] for found in by_rise] == [[], [], ["spike"]]
    by_rate = rules.horizon_warnings(100, [rules.Point(15, 131)])  # 31 mg/dL in 15 min > 2 mg/dL/min
    assert [w.kind for w in by_rate[0]] == ["spike"]


def test_range_warnings_and_possible_crossings():
    found = rules.horizon_warnings(170, [rules.Point(15, 175, 160, 190), rules.Point(30, 200, 180, 220),
                                         rules.Point(45, 260, 240, 280)])
    # 170 -> 260 by +45 is a 90 mg/dL rise: very high and a spike
    assert [[w.kind for w in f] for f in found] == [["possible_high"], ["high"], ["very_high", "spike"]]
    low = rules.horizon_warnings(80, [rules.Point(15, 72, 60, 84), rules.Point(30, 50, 40, 60)])
    assert [[w.kind for w in f] for f in low] == [["possible_low"], ["very_low"]]


def test_summary_keeps_the_earliest_of_each_kind_most_severe_first():
    found = rules.horizon_warnings(150, [rules.Point(15, 190), rules.Point(30, 230), rules.Point(45, 260)])
    summary = rules.summary(found)
    # 150 -> 190 in 15 min is 2.7 mg/dL/min: the spike starts at +15
    assert [(w.kind, w.horizon_min) for w in summary] == [("very_high", 45), ("high", 15), ("spike", 15)]


# ── assembly ────────────────────────────────────────────────────────


def test_forecast_response_shape_times_and_warnings():
    inputs = _inputs(end_value=150)
    bundle = StubBundle(delta=(10, 25, 40, 60))
    out = assemble.forecast(inputs, TZ, lambda: bundle)
    assert out["unavailable"] is None
    assert out["model"]["name"] == "gru" and out["model"]["test_rmse"]["60"] == 10.0
    origin = out["origin"]
    assert origin["glucose"] == 150 and origin["band"] == "in_range" and origin["trend"] == "steady"
    assert [f["horizon_min"] for f in out["forecast"]] == HORIZONS
    assert [f["time"] - origin["time"] for f in out["forecast"]] == [timedelta(minutes=h) for h in HORIZONS]
    last = out["forecast"][-1]
    assert (last["glucose"], last["low"], last["high"], last["change"], last["band"]) == (210, 200, 222, 60, "high")
    assert {w["kind"] for w in out["warnings"]} == {"high", "spike", "possible_high"}
    assert out["history"][-1]["v"] == 150 and len(out["history"]) == 36  # 3 h of 5-minute readings
    assert out["inputs"]["meals"][0]["carbs_g"] == 40 and out["inputs"]["missing"] == []


def test_readings_after_the_origin_never_reach_the_model():
    a, b = StubBundle(), StubBundle()
    assemble.forecast(_inputs(after_values=np.full(12, 90.0)), TZ, lambda: a)
    out = assemble.forecast(_inputs(after_values=np.full(12, 300.0)), TZ, lambda: b)
    assert np.array_equal(a.seen[0][0], b.seen[0][0])
    assert out["actual"][0]["v"] == 300  # drawn as what happened, not used as input


def test_the_gru_window_is_the_training_window():
    inputs, bundle = _inputs(), StubBundle()
    assemble.forecast(inputs, TZ, lambda: bundle)
    frame, idx = model.input_frame(inputs, TZ)
    assert bundle.seen[0][0][0] == pytest.approx(neural.window(frame, idx, SCALING))
    assert bundle.seen[0][1][0] == pytest.approx(neural.static_vector(STATIC, SCALING))


@pytest.mark.parametrize("inputs, reason", [
    (lambda: _inputs(at_shift=timedelta(minutes=40)), "40 minutes before"),
    (lambda: _inputs(gap=(pd.Timestamp("2026-09-30 12:40", tz=TZ), pd.Timestamp("2026-09-30 13:30", tz=TZ))),
     "gap longer than 30 minutes"),
])
def test_unavailable_keeps_the_history_and_gives_no_forecast(inputs, reason):
    out = assemble.forecast(inputs(), TZ, StubBundle)
    assert reason in out["unavailable"]["reason"]
    assert out["forecast"] == [] and out["warnings"] == [] and out["history"]


def test_no_cgm_is_unavailable():
    empty = pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
    inputs = ForecastInputs(uuid4(), "cgmacros", pd.Timestamp("2026-09-30", tz=TZ).to_pydatetime(), empty, empty)
    out = assemble.forecast(inputs, TZ, StubBundle)
    assert out["unavailable"] == {"reason": "no CGM readings for this twin"} and out["origin"] is None


def test_twins_without_a_meal_log_get_the_glucose_only_arima():
    rng = np.random.default_rng(0)
    inputs = _inputs(hours=24, source="bigideas")
    inputs.glucose = inputs.glucose + rng.normal(0, 2, len(inputs.glucose))
    out = assemble.forecast(inputs, TZ, lambda: pytest.fail("the GRU must not be loaded"))
    assert out["model"]["name"] == "arima" and out["inputs"]["glucose_only"]
    assert all(f["low"] < f["glucose"] < f["high"] for f in out["forecast"])


def test_real_age_undoes_the_synthea_match():
    # Twin born 1972-05-25 is 54 on 2026-09-25; matched with match_age_diff -5 -> participant aged 59.
    assert real_age(date(1972, 5, 25), -5, date(2026, 9, 25)) == 59
    assert real_age(date(1972, 5, 25), None, date(2026, 5, 24)) == 53


RAW = Path("data/raw/cgmacros")


@pytest.mark.skipif(not (RAW / "bio.csv").exists(), reason="needs the CGMacros files")
def test_inputs_from_twin_time_rows_build_the_training_frame():
    """Rows as load-sensors stores them (shifted to twin time) give the frame training used."""
    from twin.ml.bench import data
    from twin.sources import cgmacros

    info = cgmacros.read_bio(RAW / "bio.csv")["003"]
    p = data.load_patient(RAW, info)
    streams = cgmacros.parse_streams(cgmacros.read_sensor_csv(cgmacros.sensor_csv_path(RAW, "003")))
    shift = lambda s: s.set_axis(cgmacros.shift(s.index, 400, "America/Chicago"))  # noqa: E731
    k = int(np.flatnonzero((p.split == "test") & p.frame["glucose"].notna().to_numpy())[50])
    t_src = p.frame.index[k]
    native = shift(streams.glucose["Dexcom GL"].astype(float))
    at = cgmacros.shift(pd.DatetimeIndex([t_src + pd.Timedelta(minutes=2)]), 400, "America/Chicago")[0]
    keep = lambda s: s[(s.index > at - pd.Timedelta(days=3)) & (s.index <= at)]  # noqa: E731
    fit = streams.fitbit
    inputs = ForecastInputs(uuid4(), "cgmacros", at.to_pydatetime(), keep(native), keep(native).iloc[:0],
                            keep(shift(fit["heart_rate"])), keep(shift(fit["active_kcal"])), keep(shift(streams.meals)),
                            dict(p.static))
    frame, idx = model.input_frame(inputs, TZ)
    assert neural.window(frame, idx, SCALING) == pytest.approx(neural.window(p.frame, k, SCALING), abs=1e-5)
    assert SimpleNamespace(v=frame["glucose"].iloc[idx]).v == p.frame["glucose"].iloc[k]
