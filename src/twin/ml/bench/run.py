"""`bench-glucose`: benchmark glucose forecasters on real CGMacros data at 15/30/60 minutes.

Every model is scored on the same test origins (the last 25 % of each participant's
timeline). Results go to data/benchmarks/<run_id>/: metrics.csv (pooled), per_patient.csv,
by_group.csv, predictions.parquet, config.json and REPORT.md.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from twin.ml.bench import classical, metrics
from twin.ml.bench.data import HORIZONS, STATIC, Origins, build_origins, load_cohort
from twin.ml.bench.neural import LOOKBACK, STEP_FEATURES

MODELS = ("persistence", "linear", "arima", "sarima", "gru", "lstm")


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def run(
    cgmacros_dir: Path,
    out_dir: Path,
    models: list[str],
    seeds: int = 3,
    device: str = "auto",
    workers: int | None = None,
    log=print,
) -> pd.DataFrame:
    started = time.perf_counter()
    log(f"loading CGMacros from {cgmacros_dir}")
    patients = load_cohort(cgmacros_dir)
    o = build_origins(patients, LOOKBACK)
    groups = pd.Series({p.pid: p.group for p in patients}).value_counts().to_dict()
    log(f"  {len(patients)} participants {groups}; origins: "
        + ", ".join(f"{s} {np.sum(o.split == s):,}" for s in ("train", "valid", "test")))

    fitted: dict[str, list[classical.Fitted]] = {}
    timings: dict[str, dict] = {}
    fitted["persistence"] = [classical.Fitted(np.repeat(o.glucose_now[:, None], len(HORIZONS), 1), 0.0, {})]

    # Apple silicon layout: GRU on the GPU in this process, LSTM on the CPU performance cores
    # in a worker process, ARIMA/SARIMA fits on single-threaded processes on the other cores.
    os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    neural = [m for m in ("gru", "lstm") if m in models]
    devices: dict[str, str] = {}
    cpu_nn: dict = {}
    if neural:
        from twin.ml.bench import neural as nn_mod

        devices = {cell: str(nn_mod.pick_device(device, cell)) for cell in neural}
        cfg_nn = nn_mod.Config()
        tensors = nn_mod.build_tensors(patients, o)
        log(f"GRU/LSTM: {tensors.x.shape[2]} step features x {LOOKBACK} steps + {len(STATIC)} static, "
            f"{seeds} seeds; devices {devices}")
        cpu_cells = [c for c in neural if devices[c] == "cpu"]
        if cpu_cells:
            nn_pool = ProcessPoolExecutor(len(cpu_cells))
            cpu_nn = {c: nn_pool.submit(nn_mod.train_seeds, c, tensors, o, "cpu", seeds, cfg_nn) for c in cpu_cells}

    pool, futures = None, []
    want_arima = {"arima", "sarima"} & set(models)
    if want_arima:
        busy = 1 + nn_mod.CPU_THREADS * len(cpu_nn) if neural else 1
        n = workers or max(1, (os.cpu_count() or 2) - busy)
        log(f"ARIMA/SARIMA: {len(patients)} per-patient fits on {n} processes (background)")
        pool = ProcessPoolExecutor(n, initializer=classical._single_thread_worker)
        futures = classical.submit_arima(pool, patients, seasonal="sarima" in models)

    if "linear" in models:
        log("linear (ridge on lags, activity, meals, static factors)")
        fitted["linear"] = [classical.fit_linear(patients, o)]

    for cell in neural:
        if devices[cell] != "cpu":
            fitted[cell] = nn_mod.train_seeds(cell, tensors, o, devices[cell], seeds, cfg_nn)
    for cell, fut in cpu_nn.items():
        fitted[cell] = fut.result()
    if cpu_nn:
        nn_pool.shutdown()
    timings["devices"] = devices

    if futures:
        results = []
        for i, fut in enumerate(futures, 1):
            results.append(fut.result())
            if i % 5 == 0 or i == len(futures):
                log(f"  ARIMA/SARIMA patients done: {i}/{len(futures)}")
        pool.shutdown()
        for key in sorted(want_arima):
            fitted[key] = [classical.collect_arima(results, o, key)]

    table, per_patient, by_group, preds = _score(fitted, o)
    elapsed = time.perf_counter() - started

    out_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_dir / "metrics.csv", index=False)
    per_patient.to_csv(out_dir / "per_patient.csv", index=False)
    by_group.to_csv(out_dir / "by_group.csv", index=False)
    preds.to_parquet(out_dir / "predictions.parquet", index=False)
    for name, runs in fitted.items():
        timings[name] = {"fit_s": round(sum(r.fit_s for r in runs) / len(runs), 2)}
    config = {
        "run_id": out_dir.name,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "machine": f"{platform.machine()} {platform.processor()} {os.cpu_count()} cores",
        "dataset": "CGMacros (raw PhysioNet files, real data only)",
        "participants": len(patients),
        "groups": groups,
        "horizons_min": list(HORIZONS),
        "lookback_steps": LOOKBACK,
        "step_features": [*STEP_FEATURES, "hr_missing", "kcal_missing"],
        "static_features": list(STATIC),
        "seeds": seeds,
        "elapsed_s": round(elapsed, 1),
        "timings": timings,
        "model_info": {k: [_jsonable(r.info) for r in v] for k, v in fitted.items()},
    }
    (out_dir / "config.json").write_text(json.dumps(config, indent=2, default=str))
    (out_dir / "REPORT.md").write_text(_report(config, table, by_group))
    log(f"done in {elapsed / 60:.1f} min -> {out_dir}")
    return table


def _jsonable(info: dict) -> dict:
    return json.loads(json.dumps(info, default=lambda v: v.tolist() if hasattr(v, "tolist") else str(v)))


def _score(fitted: dict[str, list[classical.Fitted]], o: Origins):
    test = o.split == "test"
    # Common origins: every model has a forecast and the target is observed.
    common = np.ones((len(o.pid), len(HORIZONS)), bool)
    for runs in fitted.values():
        for r in runs:
            common &= ~np.isnan(r.pred)
    common &= ~np.isnan(o.target) & test[:, None]

    rows, patient_rows, group_rows, pred_frames = [], [], [], []
    for name, runs in fitted.items():
        for j, h in enumerate(HORIZONS):
            ok = common[:, j]
            y, base = o.target[ok, j], o.glucose_now[ok]
            per_seed = [metrics.scores(y, r.pred[ok, j], base) for r in runs]
            row = {"model": name, "horizon_min": h}
            row.update({k: float(np.mean([s[k] for s in per_seed])) for k in per_seed[0]})
            row["rmse_sd_seeds"] = float(np.std([s["rmse"] for s in per_seed])) if len(runs) > 1 else 0.0
            row["n"] = int(ok.sum())
            pp = []
            for pid in np.unique(o.pid[ok]):
                sel = ok & (o.pid == pid)
                yp, bp = o.target[sel, j], o.glucose_now[sel]
                r = np.mean([metrics.scores(yp, run.pred[sel, j], bp)["rmse"] for run in runs])
                rp = float(np.sqrt(np.mean((bp - yp) ** 2)))
                pp.append(r)
                patient_rows.append({"model": name, "horizon_min": h, "pid": pid, "n": int(sel.sum()),
                                     "rmse": r, "skill": 1 - r / rp})
            row["rmse_patient_median"] = float(np.median(pp))
            rows.append(row)
            for g in np.unique(o.group[ok]):
                sel = ok & (o.group == g)
                s = [metrics.scores(o.target[sel, j], run.pred[sel, j], o.glucose_now[sel]) for run in runs]
                group_rows.append({"model": name, "horizon_min": h, "group": g,
                                   "patients": len(np.unique(o.pid[sel])), "n": int(sel.sum()),
                                   **{k: float(np.mean([x[k] for x in s])) for k in ("rmse", "mae", "mard_pct", "skill")}})
            pred_frames.append(pd.DataFrame({
                "model": name, "horizon_min": h, "pid": o.pid[ok], "time": o.time[ok],
                "glucose_now": o.glucose_now[ok], "target": o.target[ok, j],
                "pred": np.mean([r.pred[ok, j] for r in runs], axis=0),
            }))
    table = pd.DataFrame(rows).sort_values(["horizon_min", "rmse"])
    return table, pd.DataFrame(patient_rows), pd.DataFrame(group_rows), pd.concat(pred_frames, ignore_index=True)


def _md(df: pd.DataFrame) -> str:
    head = "| " + " | ".join(df.columns) + " |\n|" + "---|" * len(df.columns) + "\n"
    return head + "\n".join("| " + " | ".join(str(v) for v in r) + " |" for r in df.itertuples(index=False))


def _report(cfg: dict, table: pd.DataFrame, by_group: pd.DataFrame) -> str:
    lines = [
        f"# Glucose forecasting benchmark: `{cfg['run_id']}`",
        "",
        f"Created {cfg['created']} · git `{cfg['git_sha']}` · {cfg['machine']} · "
        f"neural devices `{cfg['timings'].get('devices', {})}` · total {cfg['elapsed_s'] / 60:.1f} min",
        "",
        f"**Data:** {cfg['dataset']}. {cfg['participants']} participants {cfg['groups']}. "
        "No Synthea EHR and no generated wearable channels.",
        f"**Inputs:** Dexcom glucose history, Fitbit HR and activity kcal, logged meal macros, time of day; "
        f"static {', '.join(cfg['static_features'])}. ARIMA/SARIMA use glucose only.",
        "**Split:** per participant, chronological 60/15/25 % (train/valid/test), purged so a target never "
        "crosses a split. Metrics are on the test segment, on origins common to all models.",
        "",
        "Skill = 1 − RMSE / RMSE(persistence). Clarke A+B = % of forecasts in Clarke zones A or B. "
        "Neural rows are the mean over seeds.",
        "",
    ]
    cols = ["model", "rmse", "rmse_sd_seeds", "rmse_patient_median", "mae", "mard_pct", "r2", "bias", "skill",
            "clarke_a_pct", "clarke_ab_pct", "n"]
    for h in HORIZONS:
        t = table[table.horizon_min == h].sort_values("rmse")[cols].copy()
        for c in cols[1:-1]:
            t[c] = t[c].map(lambda v: f"{v:.3f}" if c in ("skill", "r2") else f"{v:.2f}")
        lines += [f"## +{h} min", "", _md(t), ""]
    g = by_group.copy()
    g["rmse"] = g["rmse"].map("{:.2f}".format)
    g["skill"] = g["skill"].map("{:.3f}".format)
    pivot = g.pivot_table(index=["group", "model"], columns="horizon_min", values="rmse", aggfunc="first")
    pivot.columns = [f"RMSE +{c}" for c in pivot.columns]
    lines += ["## RMSE by HbA1c group", "", _md(pivot.reset_index()), ""]
    t = pd.DataFrame([{"model": k, "fit_s": v["fit_s"]} for k, v in cfg["timings"].items() if "fit_s" in v])
    lines += ["## Fit time (s, summed over patients for ARIMA/SARIMA, per seed for neural)", "", _md(t), ""]
    return "\n".join(lines)
