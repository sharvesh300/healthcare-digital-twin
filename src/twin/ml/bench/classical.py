"""Persistence, linear (ridge) and per-patient ARIMA / SARIMA forecasters.

ARIMA and SARIMA are univariate: they model the glucose series alone. Exogenous inputs
would need their future values (meals, heart rate) at forecast time, which are unknown.
Each patient gets its own model, fitted by maximum likelihood on that patient's train
segment. The fitted parameters are then run through the Kalman filter over the whole
series (gaps stay missing), and the h-step forecast at every origin is read from the
filtered state: y(t+h|t) = Z T^(h-1) a(t+1|t). That gives every test origin a forecast
from a single filter pass, with no refitting and no future data.
"""

from __future__ import annotations

import time
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from twin.ml.bench.data import HORIZONS, MACROS, STATIC, STEP_MIN, Origins, Patient

# ---------------------------------------------------------------- linear

LAGS = range(0, 13)  # glucose now and 5..60 min ago
MEAL_WINDOWS = ((0, 30), (30, 60), (60, 120), (120, 180), (180, 240))  # minutes before t
RIDGE_ALPHAS = np.logspace(-2, 4, 13)


def linear_features(p: Patient) -> pd.DataFrame:
    f = p.frame
    g = f["glucose_in"]
    out = pd.DataFrame(index=f.index)
    for k in LAGS:
        out[f"g_lag{STEP_MIN * k}"] = g.shift(k)
    out["d5"] = g - g.shift(1)
    out["d15"] = g - g.shift(3)
    out["d30"] = g - g.shift(6)
    hr = f["hr"]
    out["hr_15"] = hr.rolling(3, min_periods=1).mean()
    out["hr_60"] = hr.rolling(12, min_periods=1).mean()
    out["hr_missing"] = out["hr_15"].isna().astype(float)
    kcal = f["active_kcal"]
    out["kcal_15"] = kcal.rolling(3, min_periods=1).sum()
    out["kcal_60"] = kcal.rolling(12, min_periods=1).sum()
    out["kcal_missing"] = out["kcal_15"].isna().astype(float)
    for col in MACROS:
        x = np.log1p(f[col])
        for a, b in MEAL_WINDOWS:
            out[f"{col}_{a}_{b}"] = x.shift(a // STEP_MIN).rolling((b - a) // STEP_MIN, min_periods=1).sum()
    since = f["meal"].gt(0).astype(float)
    last = pd.Series(np.where(since > 0, np.arange(len(f)), np.nan), index=f.index).ffill()
    out["min_since_meal"] = np.clip((np.arange(len(f)) - last) * STEP_MIN, 0, 360).fillna(360)
    out["tod_sin"], out["tod_cos"] = f["tod_sin"], f["tod_cos"]
    for k in STATIC:
        out[k] = p.static[k]
    return out


def _matrix(patients: list[Patient], o: Origins) -> np.ndarray:
    frames = {p.pid: linear_features(p).to_numpy() for p in patients}
    x = np.empty((len(o.pid), next(iter(frames.values())).shape[1]))
    for pid, frame in frames.items():
        rows = o.pid == pid
        x[rows] = frame[o.idx[rows]]
    return x


@dataclass
class Fitted:
    pred: np.ndarray  # (n_origins, len(HORIZONS))
    fit_s: float
    info: dict


def fit_linear(patients: list[Patient], o: Origins) -> Fitted:
    t0 = time.perf_counter()
    x = _matrix(patients, o)
    train, valid = o.split == "train", o.split == "valid"
    fill = np.nanmean(x[train], axis=0)
    x = np.where(np.isnan(x), fill, x)
    scaler = StandardScaler().fit(x[train])
    x = scaler.transform(x)
    delta = o.target - o.glucose_now[:, None]
    pred = np.full_like(delta, np.nan)
    info = {}
    for j, h in enumerate(HORIZONS):
        ok_tr, ok_va = train & ~np.isnan(delta[:, j]), valid & ~np.isnan(delta[:, j])
        best = min(
            RIDGE_ALPHAS,
            key=lambda a: np.mean(
                (Ridge(alpha=a).fit(x[ok_tr], delta[ok_tr, j]).predict(x[ok_va]) - delta[ok_va, j]) ** 2
            ),
        )
        model = Ridge(alpha=best).fit(x[ok_tr], delta[ok_tr, j])
        pred[:, j] = o.glucose_now + model.predict(x)
        info[f"alpha@{h}"] = float(best)
    info["n_features"] = int(x.shape[1])
    return Fitted(pred, time.perf_counter() - t0, info)


# ---------------------------------------------------------------- ARIMA / SARIMA

ARIMA_ORDERS = [(p, 1, q) for p in (1, 2, 3) for q in (0, 1, 2)]
SEASON = 1440 // STEP_MIN  # one day of 5-minute steps
# One daily seasonal AR term. (1,0,1) was dropped: its AR and MA terms cancel out (about
# -0.39 / +0.38 on a test patient), and at a 291-dimensional state each fit costs minutes.
SEASONAL_ORDERS = [(1, 0, 0, SEASON)]


def _forecasts(model, params: np.ndarray, steps: list[int]) -> np.ndarray:
    """h-step forecasts from every time t, out of one Kalman filter pass.

    Returns (nobs, len(steps)); row t holds the forecasts made with data up to t.
    """
    ssm = model.ssm
    for flag in ("filtered_cov", "predicted_cov", "smoothing", "gain", "std_forecast", "forecast_cov"):
        setattr(ssm, f"memory_no_{flag}", True)
    res = model.filter(params)
    a = res.predicted_state[:, 1:]  # a(t+1|t) for t = 0..n-1
    T = ssm["transition", :, :, 0]
    Z = ssm["design", :, :, 0]
    c = ssm["state_intercept", :, 0]
    d = float(ssm["obs_intercept", 0, 0])
    out = np.empty((a.shape[1], len(steps)))
    state, h = a, 1
    for j, s in enumerate(steps):
        while h < s:
            state = T @ state + c[:, None]
            h += 1
        out[:, j] = d + (Z @ state)[0]
    return out


def _fit_one(y_train: np.ndarray, order, seasonal, start=None):
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    model = SARIMAX(y_train, order=order, seasonal_order=seasonal)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # low_memory skips the smoother (GBs of state covariances at s=288); cov_type='none'
        # skips the numerical Hessian. Only the parameters and the AIC are needed.
        res = model.fit(start_params=start, disp=False, maxiter=200, low_memory=True, cov_type="none")
    return res


def arima_patient(job: tuple[str, np.ndarray, np.ndarray, bool]) -> dict:
    """Fit ARIMA (and SARIMA) on one patient's train segment; forecast the whole series."""
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    pid, y, train_mask, seasonal = job
    y_train = y[: np.flatnonzero(train_mask).max() + 1]
    steps = [h // STEP_MIN for h in HORIZONS]
    out: dict = {"pid": pid}

    t0 = time.perf_counter()
    fits = {order: _fit_one(y_train, order, (0, 0, 0, 0)) for order in ARIMA_ORDERS}
    order = min(fits, key=lambda k: fits[k].aic)
    best = fits[order]
    out["arima"] = {
        "pred": _forecasts(SARIMAX(y, order=order), best.params, steps),
        "fit_s": time.perf_counter() - t0,
        "order": order,
        "aic": float(best.aic),
    }

    if seasonal:
        t0 = time.perf_counter()
        sfits = {}
        for so in SEASONAL_ORDERS:
            n_seasonal = so[0] + so[2]
            # Start from the ARIMA solution with no seasonal effect; ARMA terms first, sigma2 last.
            start = np.r_[best.params[:-1], np.zeros(n_seasonal), best.params[-1]]
            sfits[so] = _fit_one(y_train, order, so, start)
        so = min(sfits, key=lambda k: sfits[k].aic)
        sbest = sfits[so]
        out["sarima"] = {
            "pred": _forecasts(SARIMAX(y, order=order, seasonal_order=so), sbest.params, steps),
            "fit_s": time.perf_counter() - t0,
            "order": order,
            "seasonal_order": so,
            "aic": float(sbest.aic),
            "seasonal_params": {
                k: float(v) for k, v in zip(sbest.model.param_names, sbest.params) if ".S." in k
            },
        }
    return out


def _single_thread_worker() -> None:
    from threadpoolctl import threadpool_limits

    threadpool_limits(1)
    warnings.simplefilter("ignore")


def submit_arima(pool, patients: list[Patient], seasonal: bool):
    """Queue one job per patient (largest first, so the long SARIMA fits start early)."""
    jobs = sorted(
        ((p.pid, p.frame["glucose"].to_numpy(), p.split == "train", seasonal) for p in patients),
        key=lambda j: -len(j[1]),
    )
    return [pool.submit(arima_patient, job) for job in jobs]


def collect_arima(results: list[dict], o: Origins, key: str) -> Fitted:
    pred = np.full((len(o.pid), len(HORIZONS)), np.nan)
    fit_s, info = 0.0, {}
    for r in results:
        if key not in r:
            continue
        rows = o.pid == r["pid"]
        pred[rows] = r[key]["pred"][o.idx[rows]]
        fit_s += r[key]["fit_s"]
        info[r["pid"]] = {k: v for k, v in r[key].items() if k not in ("pred", "fit_s")}
    return Fitted(pred, fit_s, info)
