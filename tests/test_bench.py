import numpy as np
import pandas as pd
import pytest

from twin.ml.bench import classical, data, metrics


def test_clarke_zones_follow_the_reference_grid():
    ref = np.array([100, 50, 60, 300, 250, 50, 150])
    pred = np.array([115, 60, 200, 40, 100, 100, 300])
    assert metrics.clarke_zones(ref, pred).tolist() == ["A", "A", "E", "E", "D", "D", "C"]


def test_only_short_interior_gaps_are_bridged():
    s = pd.Series([100.0, np.nan, 110.0, np.nan, np.nan, np.nan, 130.0, np.nan])
    out = data._bridge_short_gaps(s, limit=2)
    assert out[1] == 105.0  # one-step gap between two past readings
    assert out[3:6].isna().all()  # three-step gap stays missing
    assert np.isnan(out.iloc[-1])  # trailing gap: no future reading to bridge to


def test_arima_forecasts_from_the_filter_match_statsmodels():
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    rng = np.random.default_rng(0)
    y = 120 + np.cumsum(rng.normal(0, 2, 400))
    y[150:153] = np.nan
    res = classical._fit_one(y[:300], (2, 1, 1), (0, 0, 0, 0))
    every = classical._forecasts(SARIMAX(y, order=(2, 1, 1)), res.params, [3, 6, 12])
    for t in (200, 320):
        expected = SARIMAX(y[: t + 1], order=(2, 1, 1)).filter(res.params).forecast(12)
        assert every[t] == pytest.approx(expected[[2, 5, 11]])
