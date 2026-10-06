"""Forecast accuracy metrics, including the Clarke error grid."""

from __future__ import annotations

import numpy as np


def clarke_zones(ref: np.ndarray, pred: np.ndarray) -> np.ndarray:
    """Clarke error grid zone ('A'..'E') per (reference, prediction) pair in mg/dL."""
    x, y = np.asarray(ref, float), np.asarray(pred, float)
    zone = np.full(x.shape, "B", dtype="<U1")
    d = ((x >= 240) & (y >= 70) & (y <= 180)) | ((x <= 175 / 3) & (y >= 70) & (y <= 180)) | (
        (x >= 175 / 3) & (x <= 70) & (y >= 1.2 * x)
    )
    c = ((x >= 70) & (x <= 290) & (y >= x + 110)) | ((x >= 130) & (x <= 180) & (y <= 7 / 5 * x - 182))
    e = ((x >= 180) & (y <= 70)) | ((x <= 70) & (y >= 180))
    a = ((x <= 70) & (y <= 70)) | ((y >= 0.8 * x) & (y <= 1.2 * x))
    # Later assignments win: A over E over C over D, as in the reference implementation.
    zone[d] = "D"
    zone[c] = "C"
    zone[e] = "E"
    zone[a] = "A"
    return zone


def scores(y: np.ndarray, p: np.ndarray, persistence: np.ndarray) -> dict[str, float]:
    err = p - y
    rmse = float(np.sqrt(np.mean(err**2)))
    rmse_p = float(np.sqrt(np.mean((persistence - y) ** 2)))
    zones = clarke_zones(y, p)
    return {
        "n": int(len(y)),
        "rmse": rmse,
        "mae": float(np.mean(np.abs(err))),
        "mard_pct": float(100 * np.mean(np.abs(err) / y)),
        "bias": float(np.mean(err)),
        "r2": float(1 - np.sum(err**2) / np.sum((y - y.mean()) ** 2)),
        "skill": 1 - rmse / rmse_p,
        "clarke_a_pct": float(100 * np.mean(zones == "A")),
        "clarke_ab_pct": float(100 * np.mean((zones == "A") | (zones == "B"))),
    }
