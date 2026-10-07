"""The forecasters behind the Predict tab, and their inputs.

* GRU: the exported ensemble (twin.ml.bench.export, `twin train-glucose-forecaster`) for
  twins whose source has what it was trained on (Dexcom, Fitbit and a meal log: CGMacros).
* ARIMA fallback for the other twins (BIG IDEAs: no meal log, no Fitbit): glucose only,
  fitted per request on the twin's own last 3 days, with order (3,1,2), the one AIC picked
  most often in the benchmark. Its 80 % band is the model's own forecast interval.

Inputs are built with the training code (bench/data.build_frame, bench/neural.window), on
naive local wall time like the CGMacros files.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from twin.ml.bench import data as bench_data
from twin.prediction.store import ForecastInputs

GRU_SOURCES = frozenset({"cgmacros"})
ARIMA_ORDER = (3, 1, 2)
ARIMA_HORIZONS = (15, 30, 45, 60)
# Benchmark (data/benchmarks/cgmacros-real): per-participant ARIMA on CGMacros, test RMSE.
ARIMA_BENCHMARK_RMSE = {"15": 10.3, "30": 17.4, "45": None, "60": 25.8}
MIN_ARIMA_HISTORY = 72  # 6 hours of 5-minute readings


ML_EXTRA = "the forecasters need the ml extra: `uv sync --extra ml`"


class Unavailable(Exception):
    """The data can't support a forecast at this origin; the message says why."""


class ModelUnavailable(RuntimeError):
    """The model itself can't run: bundle not exported or failing its checks, or the ml extra missing."""


@dataclass
class ModelForecast:
    horizons: list[int]
    glucose: np.ndarray
    low: np.ndarray
    high: np.ndarray
    model: dict


@lru_cache(maxsize=4)
def gru_bundle(root: Path):
    """The exported GRU ensemble, loaded and verified once per process. Failures aren't cached,
    so a bundle exported while the API runs is picked up by the next request."""
    try:
        from twin.ml.bench.export import BundleError, load_bundle
    except ImportError as e:
        raise ModelUnavailable(f"{ML_EXTRA} ({e.name} is missing)") from e
    try:
        return load_bundle(root)
    except BundleError as e:
        raise ModelUnavailable(f"glucose forecaster unavailable: {e}") from e


def _local(s: pd.Series, tz: ZoneInfo) -> pd.Series:
    return s.set_axis(s.index.tz_convert(tz).tz_localize(None)) if len(s) else s


def input_frame(inputs: ForecastInputs, tz: ZoneInfo) -> tuple[pd.DataFrame, int]:
    """The 5-minute frame (bench_data.build_frame) and the origin row: the last reading."""
    glucose = _local(inputs.glucose, tz)
    if glucose.empty:
        raise Unavailable("no CGM readings for this twin")
    nothing = pd.Series([np.nan], index=glucose.index[:1])
    hr = _local(inputs.heart_rate, tz) if len(inputs.heart_rate) else nothing
    kcal = _local(inputs.active_kcal, tz) if len(inputs.active_kcal) else nothing
    meals = inputs.meals.set_axis(inputs.meals.index.tz_convert(tz).tz_localize(None)) if len(inputs.meals) \
        else pd.DataFrame(columns=list(bench_data.MACROS), index=pd.DatetimeIndex([]), dtype=float)
    frame = bench_data.build_frame(glucose, hr, kcal, meals)
    idx = int(np.flatnonzero(frame["glucose"].notna().to_numpy())[-1])
    return frame, idx


def gru_forecast(bundle, frame: pd.DataFrame, idx: int, static: dict[str, float]) -> ModelForecast:
    from twin.ml.bench.neural import LOOKBACK, static_vector, window

    recent = frame["glucose_in"].iloc[max(0, idx + 1 - LOOKBACK): idx + 1]
    if len(recent) < LOOKBACK or recent.isna().any():
        raise Unavailable("the last 3 hours of CGM have a gap longer than 30 minutes")
    x = window(frame, idx, bundle.scaling)[None]
    s = static_vector(static, bundle.scaling)[None]
    now = float(frame["glucose"].iloc[idx])
    point = bundle.predict(x, s, np.array([now]))[0]
    lo, hi = bundle.band()
    meta = bundle.meta
    test = meta["evaluation"]["model"]
    return ModelForecast(
        list(bundle.horizons), point, point + lo, point + hi,
        {"name": "gru", "label": "GRU · glucose, meals, activity", "version": meta["model"]["version"],
         "trained_on": f"{meta['training']['participants']} CGMacros participants",
         "horizons": list(bundle.horizons), "band_level": meta["outputs"]["band"]["level"],
         "test_rmse": {h: test[h]["rmse"] for h in test},
         "band_coverage": {h: test[h]["band_coverage"] for h in test}},
    )


def arima_forecast(frame: pd.DataFrame, idx: int) -> ModelForecast:
    try:
        from statsmodels.tsa.statespace.sarimax import SARIMAX
    except ImportError as e:
        raise ModelUnavailable(f"{ML_EXTRA} ({e.name} is missing)") from e

    y = frame["glucose"].to_numpy(dtype=float)[: idx + 1]
    if np.sum(~np.isnan(y)) < MIN_ARIMA_HISTORY:
        raise Unavailable("less than 6 hours of CGM in the last 3 days")
    steps = max(ARIMA_HORIZONS) // bench_data.STEP_MIN
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = SARIMAX(y, order=ARIMA_ORDER).fit(disp=False, maxiter=100)
        fc = res.get_forecast(steps)
        mean, ci = np.asarray(fc.predicted_mean), np.asarray(fc.conf_int(alpha=0.2))
    rows = [h // bench_data.STEP_MIN - 1 for h in ARIMA_HORIZONS]
    return ModelForecast(
        list(ARIMA_HORIZONS), mean[rows], ci[rows, 0], ci[rows, 1],
        {"name": "arima", "label": "ARIMA · glucose only", "version": f"ARIMA{ARIMA_ORDER}, fitted on this twin's last 3 days",
         "trained_on": "this twin's own CGM", "horizons": list(ARIMA_HORIZONS), "band_level": 0.8,
         "test_rmse": ARIMA_BENCHMARK_RMSE, "band_coverage": None},
    )
