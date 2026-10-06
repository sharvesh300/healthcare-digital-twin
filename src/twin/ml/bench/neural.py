"""GRU and LSTM forecasters, tuned for Apple silicon (MPS).

One global model per architecture predicts the glucose change at 15, 30 and 60 minutes
together, from a 3-hour window of 5-minute steps plus the patient's static factors. The
loss is masked, so an origin still trains the horizons whose targets it has.

Apple-silicon specifics: every window is built once with NumPy stride tricks and moved to
the device a single time. Batches are index slices of device tensors, with no DataLoader
and no per-step host-to-device copies. With device "auto", the GRU trains on the GPU (MPS)
and the LSTM on the CPU performance cores, in its own process, at the same time. The
native MPS LSTM kernel in torch 2.13 leaks about 180 MB of driver memory per training step
and drives a 16 GB machine into swap. A hand-written LSTM on MPS avoids the leak, but at
140 ms per step it is twice as slow as the native CPU kernel (70 ms). The ARIMA / SARIMA
process pool uses the remaining cores.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

from twin.ml.bench.classical import Fitted
from twin.ml.bench.data import HORIZONS, MACROS, STATIC, Origins, Patient

LOOKBACK = 36  # 3 hours
STEP_FEATURES = ("glucose_in", "hr", "active_kcal", *MACROS, "tod_sin", "tod_cos")
DELTA_SCALE = 30.0  # mg/dL; targets are glucose changes divided by this


@dataclass
class Config:
    hidden: int = 64
    layers: int = 2
    dropout: float = 0.1
    lr: float = 2e-3
    weight_decay: float = 1e-4
    batch: int = 1024
    max_epochs: int = 60
    patience: int = 8


CPU_THREADS = 4  # the M4's performance cores


def pick_device(name: str, cell: str) -> torch.device:
    if name == "auto":
        name = "mps" if cell == "gru" and torch.backends.mps.is_available() else "cpu"
    return torch.device(name)


class Forecaster(nn.Module):
    def __init__(self, cell: str, n_step: int, n_static: int, cfg: Config):
        super().__init__()
        rnn = {"gru": nn.GRU, "lstm": nn.LSTM}[cell]
        self.rnn = rnn(n_step, cfg.hidden, cfg.layers, batch_first=True, dropout=cfg.dropout)
        self.head = nn.Sequential(
            nn.Linear(cfg.hidden + n_static, cfg.hidden), nn.GELU(), nn.Linear(cfg.hidden, len(HORIZONS))
        )

    def forward(self, x: torch.Tensor, s: torch.Tensor) -> torch.Tensor:
        out, _ = self.rnn(x)
        return self.head(torch.cat([out[:, -1], s], dim=1))


@dataclass
class Tensors:
    x: np.ndarray  # (n, LOOKBACK, n_step) float32
    s: np.ndarray  # (n, n_static)
    y: np.ndarray  # (n, 3) scaled delta, 0 where missing
    m: np.ndarray  # (n, 3) target mask


def build_tensors(patients: list[Patient], o: Origins) -> Tensors:
    """Per-step inputs: z-scored glucose / HR / activity (+ missing flags), log meal macros, time of day."""
    train_rows = {p.pid: p.split == "train" for p in patients}
    stats = {}
    for col in ("glucose_in", "hr", "active_kcal"):
        v = np.concatenate([p.frame[col].to_numpy()[train_rows[p.pid]] for p in patients])
        stats[col] = (np.nanmean(v), np.nanstd(v))
    static = np.array([[p.static[k] for k in STATIC] for p in patients], dtype=float)
    s_mean, s_std = np.nanmean(static, axis=0), np.nanstd(static, axis=0)

    n_step = len(STEP_FEATURES) + 2  # + HR and activity missing flags
    x = np.empty((len(o.pid), LOOKBACK, n_step), np.float32)
    s = np.empty((len(o.pid), len(STATIC)), np.float32)
    for k, p in enumerate(patients):
        rows = np.flatnonzero(o.pid == p.pid)
        if not len(rows):
            continue
        f = p.frame
        cols = []
        for col in STEP_FEATURES:
            v = f[col].to_numpy(dtype=float)
            if col in stats:
                v = (v - stats[col][0]) / stats[col][1]
            elif col in MACROS:
                v = np.log1p(v) / 3.0
            cols.append(v)
        cols.append(np.isnan(f["hr"].to_numpy()).astype(float))
        cols.append(np.isnan(f["active_kcal"].to_numpy()).astype(float))
        steps = np.nan_to_num(np.stack(cols, axis=1)).astype(np.float32)
        windows = np.lib.stride_tricks.sliding_window_view(steps, LOOKBACK, axis=0)  # (n-L+1, F, L)
        x[rows] = windows[o.idx[rows] - LOOKBACK + 1].transpose(0, 2, 1)
        s[rows] = np.nan_to_num((static[k] - s_mean) / s_std)
    delta = (o.target - o.glucose_now[:, None]) / DELTA_SCALE
    m = ~np.isnan(delta)
    return Tensors(x, s, np.nan_to_num(delta).astype(np.float32), m.astype(np.float32))


def _predict(model: nn.Module, x: torch.Tensor, s: torch.Tensor, batch: int) -> torch.Tensor:
    model.eval()
    with torch.inference_mode():
        return torch.cat([model(x[i : i + batch], s[i : i + batch]) for i in range(0, len(x), batch)])


def train(
    cell: str, data: Tensors, o: Origins, device: torch.device, seed: int, cfg: Config, log=print
) -> Fitted:
    torch.manual_seed(seed)
    np.random.seed(seed)
    on = lambda a: torch.from_numpy(np.ascontiguousarray(a)).to(device)  # noqa: E731
    tr, va = np.flatnonzero(o.split == "train"), np.flatnonzero(o.split == "valid")
    x_tr, s_tr, y_tr, m_tr = (on(a[tr]) for a in (data.x, data.s, data.y, data.m))
    x_va, s_va, y_va, m_va = (on(a[va]) for a in (data.x, data.s, data.y, data.m))

    model = Forecaster(cell, data.x.shape[2], data.s.shape[1], cfg).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, factor=0.5, patience=3)
    gen = torch.Generator(device="cpu").manual_seed(seed)

    t0 = time.perf_counter()
    best, best_state, stale, epochs = np.inf, None, 0, 0
    for epoch in range(cfg.max_epochs):
        model.train()
        order = torch.randperm(len(tr), generator=gen).to(device)
        for i in range(0, len(tr), cfg.batch):
            b = order[i : i + cfg.batch]
            err = (model(x_tr[b], s_tr[b]) - y_tr[b]) * m_tr[b]
            loss = err.pow(2).sum() / m_tr[b].sum()
            opt.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
        p_va = _predict(model, x_va, s_va, 8192)
        val = ((((p_va - y_va) * m_va) ** 2).sum(0) / m_va.sum(0)).sqrt().mean().item() * DELTA_SCALE
        sched.step(val)
        epochs = epoch + 1
        if val < best - 1e-3:
            best, best_state, stale = val, copy.deepcopy(model.state_dict()), 0
        else:
            stale += 1
            if stale >= cfg.patience:
                break
    fit_s = time.perf_counter() - t0
    model.load_state_dict(best_state)
    log(f"    {cell} seed {seed}: {epochs} epochs, valid RMSE {best:.2f} mg/dL (mean of horizons), {fit_s:.0f}s")

    t1 = time.perf_counter()
    pred = _predict(model, on(data.x), on(data.s), 8192).float().cpu().numpy() * DELTA_SCALE
    predict_s = time.perf_counter() - t1
    return Fitted(
        o.glucose_now[:, None] + pred,
        fit_s,
        {"seed": seed, "epochs": epochs, "valid_rmse": best, "predict_s": predict_s,
         "params": sum(p.numel() for p in model.parameters())},
    )


def train_seeds(cell: str, data: Tensors, o: Origins, device: str, seeds: int, cfg: Config) -> list[Fitted]:
    """All seeds of one architecture; runs in the main process (MPS) or a worker (CPU)."""
    dev = torch.device(device)
    torch.set_num_threads(CPU_THREADS if dev.type == "cpu" else 1)
    return [train(cell, data, o, dev, seed, cfg, log=lambda m: print(m, flush=True)) for seed in range(seeds)]
