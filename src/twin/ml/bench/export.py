"""`train-glucose-forecaster`: train the GRU ensemble and export it as a self-describing bundle.

    data/models/glucose_forecast/
      CURRENT                      one line: the run directory the API loads
      gru-<date>-<git sha>/
        weights.safetensors        every seed's weights, keys prefixed seed0. / seed1. / ...
        meta.json                  model card and preprocessing contract (FORMAT_VERSION)

The weights are plain tensors (safetensors: no pickle, so loading runs no code). The same
`Forecaster` class trains and serves. `load_bundle` refuses a bundle whose format, checksum
or feature contract differs from this code, and never guesses past a mismatch.

Prediction bands are split-conformal: the 10th and 90th percentiles of the ensemble's
validation residuals per horizon, added to the point forecast (an 80 % band). The bundle
records the band's coverage on the test segment.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import torch

from twin.ml.bench import metrics
from twin.ml.bench.classical import Fitted
from twin.ml.bench.data import HORIZONS, MAX_FILL_STEPS, STATIC, STEP_MIN, Origins
from twin.ml.bench.neural import (
    DELTA_SCALE,
    LOOKBACK,
    MACRO_SCALE,
    STEP_INPUTS,
    Config,
    Forecaster,
    Scaling,
)

FORMAT_VERSION = 1
BAND_LEVEL = 0.8
WEIGHTS = "weights.safetensors"
META = "meta.json"
CURRENT = "CURRENT"


class BundleError(RuntimeError):
    """The bundle can't be served by this code: missing, corrupted or a different contract."""


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _git_dirty() -> bool:
    """True when the bundle was trained from uncommitted code (git_sha alone would not identify it)."""
    try:
        return bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no", "src"],
                                            text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        return False


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _per_horizon(values) -> dict[str, float]:
    return {str(h): round(float(v), 3) for h, v in zip(HORIZONS, values)}


def evaluate(runs: list[Fitted], o: Origins) -> tuple[np.ndarray, dict, dict]:
    """Ensemble forecast, band offsets from the validation residuals, and test metrics."""
    pred = np.mean([r.pred for r in runs], axis=0)
    valid, test = o.split == "valid", o.split == "test"
    q = (1 - BAND_LEVEL) / 2
    low, high, model, persistence = [], [], {}, {}
    for j, h in enumerate(HORIZONS):
        ok_v = valid & ~np.isnan(o.target[:, j]) & ~np.isnan(pred[:, j])
        resid = o.target[ok_v, j] - pred[ok_v, j]
        low.append(np.quantile(resid, q))
        high.append(np.quantile(resid, 1 - q))
        ok = test & ~np.isnan(o.target[:, j]) & ~np.isnan(pred[:, j])
        y, p, now = o.target[ok, j], pred[ok, j], o.glucose_now[ok]
        s = metrics.scores(y, p, now)
        inside = (y >= p + low[-1]) & (y <= p + high[-1])
        model[str(h)] = {k: round(s[k], 3) for k in ("rmse", "mae", "mard_pct", "r2", "skill", "clarke_a_pct",
                                                       "clarke_ab_pct")} | {"n": s["n"],
                                                                            "band_coverage": round(float(inside.mean()), 3)}
        sp = metrics.scores(y, now, now)
        persistence[str(h)] = {k: round(sp[k], 3) for k in ("rmse", "mae", "mard_pct")}
    band = {"level": BAND_LEVEL, "method": "split conformal, validation residuals of the ensemble",
            "low": _per_horizon(low), "high": _per_horizon(high)}
    return pred, band, {"model": model, "persistence": persistence}


def build_meta(version: str, cfg: Config, scaling: Scaling, runs: list[Fitted], band: dict, evaluation: dict,
               training: dict) -> dict:
    return {
        "format_version": FORMAT_VERSION,
        "model": {
            "name": "gru",
            "version": version,
            "architecture": {"cell": "gru", "hidden": cfg.hidden, "layers": cfg.layers, "dropout": cfg.dropout},
            "seeds": [r.info["seed"] for r in runs],
            "ensemble": "mean of seed predictions",
        },
        "inputs": {
            "glucose_source": "Dexcom native readings",
            "step_minutes": STEP_MIN,
            "lookback_steps": LOOKBACK,
            "max_bridged_gap_min": MAX_FILL_STEPS * STEP_MIN,
            "step_features": list(STEP_INPUTS),
            "static_features": list(STATIC),
            "scaling": {
                **{col: {"mean": mean, "std": sd} for col, (mean, sd) in scaling.stats.items()},
                "macros": f"log1p(x) / {MACRO_SCALE:g}",
                "static": {"mean": scaling.static_mean, "std": scaling.static_std},
                "missing": "NaN -> 0 after scaling",
            },
        },
        "outputs": {
            "horizons_min": list(HORIZONS),
            "target": f"glucose change from the origin, mg/dL / {DELTA_SCALE:g}",
            "band": band,
        },
        "training": {
            **training,
            "epochs": [r.info["epochs"] for r in runs],
            "created": datetime.now(UTC).isoformat(timespec="seconds"),
            "git_sha": _git_sha(),
            "git_dirty": _git_dirty(),
            "python": platform.python_version(),
            "torch": torch.__version__,
        },
        "evaluation": evaluation,
    }


def save_bundle(root: Path, meta: dict, states: list[dict], make_current: bool = True) -> Path:
    from safetensors.torch import save_file

    out = root / meta["model"]["version"]
    out.mkdir(parents=True, exist_ok=False)
    tensors = {f"seed{i}.{k}": v.detach().cpu().contiguous() for i, state in enumerate(states) for k, v in state.items()}
    save_file(tensors, out / WEIGHTS, metadata={"format_version": str(FORMAT_VERSION)})
    meta = {**meta, "checksums": {WEIGHTS: _sha256(out / WEIGHTS)}}
    (out / META).write_text(json.dumps(meta, indent=2) + "\n")
    if make_current:
        (root / CURRENT).write_text(out.name + "\n")
    return out


@dataclass
class Bundle:
    """A loaded, verified bundle: the seed models (CPU, eval mode) and their contract."""

    path: Path
    meta: dict
    scaling: Scaling
    models: list[Forecaster]

    @property
    def horizons(self) -> list[int]:
        return self.meta["outputs"]["horizons_min"]

    def band(self) -> tuple[np.ndarray, np.ndarray]:
        band = self.meta["outputs"]["band"]
        return (np.array([band["low"][str(h)] for h in self.horizons]),
                np.array([band["high"][str(h)] for h in self.horizons]))

    def predict(self, x: np.ndarray, s: np.ndarray, glucose_now: np.ndarray) -> np.ndarray:
        """(n, horizons) mg/dL: the mean of the seed models' forecasts."""
        xt, st = torch.from_numpy(np.asarray(x, np.float32)), torch.from_numpy(np.asarray(s, np.float32))
        with torch.inference_mode():
            delta = torch.stack([m(xt, st) for m in self.models]).mean(0).numpy() * DELTA_SCALE
        return np.asarray(glucose_now, float)[:, None] + delta


def _check_contract(meta: dict) -> None:
    if meta.get("format_version") != FORMAT_VERSION:
        raise BundleError(f"bundle format {meta.get('format_version')}, this code reads format {FORMAT_VERSION}")
    inputs = meta["inputs"]
    expected = {"step_features": list(STEP_INPUTS), "static_features": list(STATIC), "lookback_steps": LOOKBACK,
                "step_minutes": STEP_MIN, "max_bridged_gap_min": MAX_FILL_STEPS * STEP_MIN}
    for key, want in expected.items():
        if inputs.get(key) != want:
            raise BundleError(f"bundle {key} {inputs.get(key)!r} differs from this code's {want!r}")
    if meta["outputs"]["target"] != f"glucose change from the origin, mg/dL / {DELTA_SCALE:g}":
        raise BundleError(f"bundle target {meta['outputs']['target']!r} differs from this code's")


def load_bundle(root: Path) -> Bundle:
    from safetensors.torch import load_file

    pointer = root / CURRENT
    if not pointer.exists():
        raise BundleError(f"no exported glucose forecaster in {root}; run `twin train-glucose-forecaster`")
    path = root / pointer.read_text().strip()
    try:
        meta = json.loads((path / META).read_text())
    except FileNotFoundError as e:
        raise BundleError(f"{CURRENT} points to {path.name}, which has no {META}") from e
    _check_contract(meta)
    if _sha256(path / WEIGHTS) != meta["checksums"][WEIGHTS]:
        raise BundleError(f"{path / WEIGHTS} does not match the checksum in {META}")

    tensors = load_file(path / WEIGHTS)
    arch = meta["model"]["architecture"]
    cfg = Config(hidden=arch["hidden"], layers=arch["layers"], dropout=arch["dropout"])
    models = []
    for i, _ in enumerate(meta["model"]["seeds"]):
        prefix = f"seed{i}."
        state = {k.removeprefix(prefix): v for k, v in tensors.items() if k.startswith(prefix)}
        model = Forecaster(arch["cell"], len(STEP_INPUTS), len(STATIC), cfg, n_out=len(meta["outputs"]["horizons_min"]))
        model.load_state_dict(state, strict=True)
        models.append(model.eval())
    scale = meta["inputs"]["scaling"]
    scaling = Scaling({col: (scale[col]["mean"], scale[col]["std"]) for col in ("glucose_in", "hr", "active_kcal")},
                      scale["static"]["mean"], scale["static"]["std"])
    return Bundle(path, meta, scaling, models)


def train_and_export(cgmacros_dir: Path, root: Path, seeds: int = 3, device: str = "auto", log=print) -> Path:
    from twin.ml.bench.data import build_origins, load_cohort
    from twin.ml.bench.neural import build_tensors, pick_device, train_seeds

    log(f"loading CGMacros from {cgmacros_dir}")
    patients = load_cohort(cgmacros_dir)
    o = build_origins(patients, LOOKBACK)
    tensors = build_tensors(patients, o)
    dev = pick_device(device, "gru")
    cfg = Config()
    log(f"  {len(patients)} participants; origins: "
        + ", ".join(f"{s} {np.sum(o.split == s):,}" for s in ("train", "valid", "test"))
        + f"; training {seeds} GRU seeds on {dev}")
    runs = train_seeds("gru", tensors, o, str(dev), seeds, cfg)
    _, band, evaluation = evaluate(runs, o)

    version = f"gru-{datetime.now(UTC):%Y%m%d}-{_git_sha()}"
    if (root / version).exists():
        version += f"-{datetime.now(UTC):%H%M%S}"
    training = {"dataset": "CGMacros raw files, real data only", "participants": len(patients),
                "split": "per participant, chronological 60/15/25, purged", "device": str(dev)}
    meta = build_meta(version, cfg, tensors.scaling, runs, band, evaluation, training)
    out = save_bundle(root, meta, [r.state for r in runs])

    load_bundle(root)  # the bundle just written must load and verify
    for h, m in evaluation["model"].items():
        p = evaluation["persistence"][h]
        log(f"  +{h} min: RMSE {m['rmse']:.2f} (persistence {p['rmse']:.2f}), MARD {m['mard_pct']:.1f} %, "
            f"band coverage {100 * m['band_coverage']:.0f} %")
    log(f"exported {out} (CURRENT -> {out.name})")
    return out

