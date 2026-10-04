"""Population HbA1c models on NHANES 2011-2014 adults with diabetes (real, cross-sectional).

1. Prediction: gradient-boosted trees, HbA1c from demographics, body size, BP, kidney
   function, lipids, diabetes duration, daily steps, medication classes and conditions.
   5-fold CV against the mean-only baseline. Saved for the simulation API.
2. Adjusted associations: ordinary least squares on the same covariates (complete cases),
   with bootstrap 95 % intervals. These are associations in observational data. Drug
   classes are confounded by indication: people on insulin have higher HbA1c because
   sicker people get insulin, not because insulin raises HbA1c.
"""

from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import KFold

from twin.config import Settings

DRUGS = ["on_metformin", "on_sulfonylurea", "on_dpp4i", "on_sglt2i", "on_glp1ra", "on_tzd", "on_insulin",
         "on_statin", "on_acei_arb"]
CONDITIONS = ["has_hypertension", "has_dyslipidemia", "has_ckd", "has_retinopathy", "has_cardiovascular"]
FEATURES = ["age", "male", "bmi", "sbp", "dbp", "egfr", "triglycerides", "hdl", "diabetes_diagnosed",
            "diabetes_duration_years", "steps_per_valid_day", "current_smoker", *DRUGS, *CONDITIONS]
# OLS: steps per 1,000/day; other continuous terms in natural units.
OLS_TERMS = ["steps_k", "age", "male", "bmi", "sbp", "egfr", "diabetes_duration_years", "diabetes_diagnosed",
             *DRUGS, *CONDITIONS]


def prepare(static: pd.DataFrame) -> pd.DataFrame:
    df = static[(static.cohort == "nhanes") & static.hba1c.notna()].copy()
    df["male"] = (df.sex == "male").astype(float)
    df["current_smoker"] = df.smoking_status.isin(["Smokes tobacco daily", "Occasional tobacco smoker"]).astype(float)
    # Steps only from people with >= 4 valid days (the usual reliability threshold).
    df["steps_per_valid_day"] = df.steps_per_valid_day.where(df.valid_step_days >= 4)
    df["steps_k"] = df.steps_per_valid_day / 1000
    for c in [*DRUGS, *CONDITIONS, "diabetes_diagnosed"]:
        df[c] = df[c].astype(float)
    # Undiagnosed (lab-detected) people have no diagnosis year: duration 0.
    df["diabetes_duration_years"] = df.diabetes_duration_years.where(df.diabetes_diagnosed == 1, 0.0)
    return df


def _gbm() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                         l2_regularization=1.0, random_state=0)


def _ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    A = np.column_stack([np.ones(len(X)), X])
    return np.linalg.lstsq(A, y, rcond=None)[0]


def train(static: pd.DataFrame, cfg: Settings, log=print, n_boot: int = 500) -> dict:
    df = prepare(static)
    X, y = df[FEATURES].astype(float), df.hba1c.astype(float).to_numpy()

    preds = np.empty_like(y)
    for tr, te in KFold(n_splits=5, shuffle=True, random_state=0).split(X):
        preds[te] = _gbm().fit(X.iloc[tr], y[tr]).predict(X.iloc[te])
    rmse = float(np.sqrt(np.mean((preds - y) ** 2)))
    rmse_mean = float(np.sqrt(np.mean((y - y.mean()) ** 2)))
    r2 = 1 - rmse**2 / rmse_mean**2
    log(f"HbA1c model (NHANES, n={len(y)}): CV RMSE {rmse:.2f} % vs mean-only {rmse_mean:.2f} %, R² {r2:.2f}")
    model = _gbm().fit(X, y)

    cc = df.dropna(subset=OLS_TERMS + ["hba1c"])
    Xo, yo = cc[OLS_TERMS].astype(float).to_numpy(), cc.hba1c.astype(float).to_numpy()
    coef = _ols(Xo, yo)
    rng = np.random.default_rng(0)
    boots = np.array([_ols(Xo[idx], yo[idx]) for idx in (rng.integers(0, len(yo), len(yo)) for _ in range(n_boot))])
    lo, hi = np.percentile(boots, [2.5, 97.5], axis=0)
    assoc = pd.DataFrame({"term": ["intercept", *OLS_TERMS], "coef": coef, "ci_low": lo, "ci_high": hi})
    log(f"adjusted associations (OLS, complete cases n={len(yo)}):")
    for r in assoc.iloc[1:].itertuples():
        flag = "" if r.ci_low <= 0 <= r.ci_high else " *"
        log(f"  {r.term:26} {r.coef:+.3f}  [{r.ci_low:+.3f}, {r.ci_high:+.3f}]{flag}")

    out = cfg.data_dir / "models"
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "features": FEATURES}, out / "hba1c_population.joblib")
    assoc.to_csv(out / "hba1c_associations.csv", index=False)
    metrics = {"n": len(y), "cv_rmse": rmse, "mean_only_rmse": rmse_mean, "r2": r2, "ols_n": len(yo)}
    (out / "hba1c_population_metrics.json").write_text(json.dumps(metrics, indent=2))
    return metrics


def load(cfg: Settings) -> dict:
    return joblib.load(cfg.data_dir / "models" / "hba1c_population.joblib")
