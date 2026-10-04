"""Short-horizon glucose forecaster (30 / 60 minutes ahead) on the fused CGM series.

Features at time t (5-minute grid, per patient):
  glucose now and its lags over the last hour, rates of change, 1-hour mean/SD,
  heart rate (30 min), METs (30/60 min), steps (60 min), insulin (fast 2 h, basal 24 h),
  oral glucose-lowering doses (12 h), time of day.
Model: gradient-boosted trees predicting the *change* in glucose. Missing channels are
allowed (HistGradientBoosting handles NaN), so cohorts without steps or doses still fit.

Evaluation: patient-grouped K-fold (no patient in both train and test fold), compared
with the persistence baseline (glucose stays where it is). The final model is refit on
all patients and saved for the simulation API.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import GroupKFold

from twin.config import Settings

HORIZONS = (30, 60)
LAGS = range(1, 13)  # 5..60 minutes


def build_features(series: pd.DataFrame) -> pd.DataFrame:
    """Feature matrix on each patient's own 5-minute grid (gaps stay NaN)."""
    out = []
    for pid, g in series.sort_values("time").groupby("patient_id", sort=False):
        g = g.set_index("time").asfreq("5min")
        g["patient_id"] = pid
        glu = g["glucose_mg_dl"].astype(float)
        f = pd.DataFrame(index=g.index)
        f["patient_id"] = pid
        f["glucose"] = glu
        for k in LAGS:
            f[f"glucose_lag{5 * k}"] = glu.shift(k)
        f["roc_5"] = glu - glu.shift(1)
        f["roc_15"] = (glu - glu.shift(3)) / 3
        f["roc_30"] = (glu - glu.shift(6)) / 6
        f["mean_60"] = glu.rolling(12, min_periods=6).mean()
        f["sd_60"] = glu.rolling(12, min_periods=6).std()
        f["heart_rate_30"] = g["heart_rate"].astype(float).rolling(6, min_periods=1).mean()
        mets = g["met_minutes"].astype(float)
        f["met_minutes_30"] = mets.rolling(6, min_periods=1).sum()
        f["met_minutes_60"] = mets.rolling(12, min_periods=1).sum()
        f["steps_60"] = g["steps"].astype(float).rolling(12, min_periods=1).sum()
        f["insulin_fast_2h"] = g["insulin_fast_units"].astype(float).fillna(0).rolling(24, min_periods=1).sum()
        f["insulin_basal_24h"] = g["insulin_basal_units"].astype(float).fillna(0).rolling(288, min_periods=1).sum()
        f["oral_doses_12h"] = g["oral_doses"].astype(float).fillna(0).rolling(144, min_periods=1).sum()
        local = f.index.tz_convert("America/Chicago")
        minute = local.hour * 60 + local.minute
        f["tod_sin"] = np.sin(2 * np.pi * minute / 1440)
        f["tod_cos"] = np.cos(2 * np.pi * minute / 1440)
        for h in HORIZONS:
            f[f"target_t{h}"] = glu.shift(-h // 5)
        out.append(f.reset_index())
    return pd.concat(out, ignore_index=True)



def feature_columns(frame: pd.DataFrame) -> list[str]:
    return [c for c in frame.columns if c not in ("patient_id", "time") and not c.startswith("target_")]


@dataclass
class HorizonResult:
    horizon: int
    n_samples: int
    n_patients: int
    rmse_model: float
    rmse_persistence: float
    mae_model: float
    mae_persistence: float
    mard_model: float
    mard_persistence: float


def _metrics(y, pred):
    err = pred - y
    return float(np.sqrt(np.mean(err**2))), float(np.mean(np.abs(err))), float(100 * np.mean(np.abs(err) / y))


def _model() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
                                         l2_regularization=1.0, random_state=0)


def train(series: pd.DataFrame, cfg: Settings, log=print) -> list[HorizonResult]:
    frame = build_features(series)
    # Channels absent from every patient in this data (e.g. steps for CGMacros) carry no
    # information and break histogram binning; they are left out and the model records it.
    cols = [c for c in feature_columns(frame) if frame[c].notna().any()]
    dropped = sorted(set(feature_columns(frame)) - set(cols))
    if dropped:
        log(f"features with no data in this cohort (not used): {dropped}")
    results = []
    models = {}
    for h in HORIZONS:
        data = frame.dropna(subset=["glucose", f"target_t{h}"])
        X, y, groups = data[cols], data[f"target_t{h}"].to_numpy(), data["patient_id"].to_numpy()
        n_patients = len(np.unique(groups))
        preds = np.empty_like(y)
        for train_idx, test_idx in GroupKFold(n_splits=min(5, n_patients)).split(X, y, groups):
            m = _model().fit(X.iloc[train_idx], y[train_idx] - X["glucose"].iloc[train_idx])
            preds[test_idx] = X["glucose"].iloc[test_idx].to_numpy() + m.predict(X.iloc[test_idx])
        rm, am, mm = _metrics(y, preds)
        rp, ap, mp = _metrics(y, X["glucose"].to_numpy())
        results.append(HorizonResult(h, len(y), n_patients, rm, rp, am, ap, mm, mp))
        log(f"+{h} min: n={len(y):,} ({n_patients} patients)  RMSE {rm:.1f} vs persistence {rp:.1f} mg/dL, "
            f"MARD {mm:.1f}% vs {mp:.1f}%")
        models[h] = _model().fit(X, y - X["glucose"])

    out = cfg.data_dir / "models"
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump({"models": models, "features": cols, "horizons": HORIZONS}, out / "glucose_forecaster.joblib")
    (out / "glucose_forecaster_metrics.json").write_text(json.dumps([r.__dict__ for r in results], indent=2))
    return results


def load(cfg: Settings) -> dict:
    return joblib.load(cfg.data_dir / "models" / "glucose_forecaster.joblib")


def predict(bundle: dict, features: pd.DataFrame) -> dict[int, np.ndarray]:
    """Absolute glucose forecasts per horizon for prepared feature rows."""
    X = features[bundle["features"]]
    return {h: X["glucose"].to_numpy() + m.predict(X) for h, m in bundle["models"].items()}
