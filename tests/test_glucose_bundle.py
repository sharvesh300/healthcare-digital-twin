import json

import numpy as np
import pandas as pd
import pytest
import torch

from twin.ml.bench import data, export, neural
from twin.ml.bench.data import HORIZONS, Patient


def _patient(pid: str, seed: int) -> Patient:
    """Two days of synthetic Dexcom, Fitbit and meals, built like a real participant."""
    rng = np.random.default_rng(seed)
    t = pd.date_range("2026-05-01 06:04", periods=576, freq="5min")
    glucose = pd.Series(120 + 30 * np.sin(np.arange(576) / 20) + rng.normal(0, 3, 576), index=t)
    minutes = pd.date_range(t[0], t[-1], freq="min")
    hr = pd.Series(70 + rng.normal(0, 5, len(minutes)), index=minutes)
    kcal = pd.Series(np.abs(rng.normal(1.2, 0.3, len(minutes))), index=minutes)
    meals = pd.DataFrame({"energy_kcal": [500.0, 700.0], "carbs_g": [60.0, 80.0], "protein_g": [20.0, 30.0],
                          "fat_g": [15.0, 25.0], "fiber_g": [5.0, 8.0]},
                         index=pd.to_datetime(["2026-05-01 12:10", "2026-05-02 18:40"]))
    frame = data.build_frame(glucose, hr, kcal, meals)
    static = {"age": 40.0 + seed, "male": float(seed % 2), "bmi": 27.0, "hba1c": 6.0, "fasting_glucose": 110.0}
    return Patient(pid, "prediabetes", frame, static, data.chronological_split(frame.index))


@pytest.fixture(scope="module")
def trained():
    patients = [_patient("a", 1), _patient("b", 2), _patient("c", 3)]
    o = data.build_origins(patients, neural.LOOKBACK)
    tensors = neural.build_tensors(patients, o)
    cfg = neural.Config(hidden=8, layers=1, dropout=0.0, max_epochs=1)
    runs = [neural.train("gru", tensors, o, torch.device("cpu"), seed, cfg, log=lambda m: None) for seed in (0, 1)]
    _, band, evaluation = export.evaluate(runs, o)
    meta = export.build_meta("gru-test", cfg, tensors.scaling, runs, band, evaluation, {"participants": 3})
    return patients, o, tensors, runs, meta


def test_exported_bundle_reproduces_the_trained_ensemble(trained, tmp_path):
    patients, o, tensors, runs, meta = trained
    export.save_bundle(tmp_path, meta, [r.state for r in runs])
    bundle = export.load_bundle(tmp_path)
    assert bundle.horizons == list(HORIZONS)
    got = bundle.predict(tensors.x[:50], tensors.s[:50], o.glucose_now[:50])
    want = np.mean([r.pred[:50] for r in runs], axis=0)
    assert got == pytest.approx(want, abs=1e-3)


def test_serving_window_matches_training_window(trained):
    patients, o, tensors, _, _ = trained
    p = patients[1]
    k = np.flatnonzero(o.pid == p.pid)[10]
    assert neural.window(p.frame, o.idx[k], tensors.scaling) == pytest.approx(tensors.x[k])
    assert neural.static_vector(p.static, tensors.scaling) == pytest.approx(tensors.s[k])


def test_band_is_an_80_percent_interval_per_horizon(trained):
    *_, meta = trained
    band = meta["outputs"]["band"]
    assert band["level"] == 0.8
    assert all(band["low"][str(h)] < band["high"][str(h)] for h in HORIZONS)


@pytest.mark.parametrize("change, message", [
    (lambda m: m.update(format_version=2), "format 2"),
    (lambda m: m["inputs"].update(step_features=["glucose_in"]), "step_features"),
    (lambda m: m["inputs"].update(lookback_steps=24), "lookback_steps"),
])
def test_a_different_contract_refuses_to_load(trained, tmp_path, change, message):
    *_, runs, meta = trained
    out = export.save_bundle(tmp_path, meta, [r.state for r in runs])
    stored = json.loads((out / export.META).read_text())
    change(stored)
    (out / export.META).write_text(json.dumps(stored))
    with pytest.raises(export.BundleError, match=message):
        export.load_bundle(tmp_path)


def test_corrupted_weights_or_no_bundle_refuse_to_load(trained, tmp_path):
    with pytest.raises(export.BundleError, match="train-glucose-forecaster"):
        export.load_bundle(tmp_path)
    *_, runs, meta = trained
    out = export.save_bundle(tmp_path, meta, [r.state for r in runs])
    weights = out / export.WEIGHTS
    weights.write_bytes(weights.read_bytes()[:-1] + b"\x00")
    with pytest.raises(export.BundleError, match="checksum"):
        export.load_bundle(tmp_path)
