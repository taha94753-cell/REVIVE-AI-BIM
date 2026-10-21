"""
Monte Carlo finish-date risk: how likely is the project to finish by the target,
now and with the optimised recovery plan?

Two sources of uncertainty are sampled together (default 2,000 runs):
  1. Forecast error of the ML model. Each run adds one cross-validation residual
     (actual - out-of-fold forecast, resampled with replacement) to the forecast
     overrun, so the spread is the model's measured error, not an invented one.
  2. Activity-level variation. Each remaining activity duration is multiplied by a
     triangular factor (config: simulation.activity_spread, default 0.92 / 1.00 / 1.12,
     skewed late as construction durations usually are).
Every run is pushed through the same CPM network, with and without the crash days
chosen by the LP (crash days scale with the sampled duration).
"""
from __future__ import annotations

import numpy as np

from .config import load_config
from .scheduling import DAYS_PER_MONTH, Activity, topo_order


def _finish(order, active, preds, t0, dur: np.ndarray, idx: dict) -> np.ndarray:
    n = dur.shape[0]
    ef = {}
    for a in order:
        start = np.full(n, t0)
        for p in preds[a.id]:
            if p in active:
                start = np.maximum(start, ef[p])
        ef[a.id] = start + dur[:, idx[a.id]]
    return np.max(np.column_stack(list(ef.values())), axis=1) if ef else np.full(n, t0)


def simulate(acts: list[Activity], fc: dict, crash_days: dict, deadline: float, overrun_pct: float,
             residuals: list[float] | None = None) -> dict:
    cfg = load_config()["simulation"]
    n, rng = int(cfg["samples"]), np.random.default_rng(int(cfg["seed"]))
    lo, mode, hi = cfg["activity_spread"]
    active = set(fc["active"])
    order = [a for a in topo_order(acts) if a.id in active]
    if not order:
        return None
    idx = {a.id: j for j, a in enumerate(order)}
    preds = {a.id: a.preds for a in order}
    t0, planned, k = fc["t0"], fc["planned_finish"], fc["k"]
    d_fc = np.array([fc["forecast_durations"][a.id] for a in order])
    unit = d_fc / k                                  # remaining durations before ML scaling
    span = (fc["forecast_finish"] - t0) / k          # remaining CPM length at unit scale

    if residuals:
        err = rng.choice(np.asarray(residuals, dtype=float), size=n, replace=True)
    else:
        err = rng.normal(0, 8.0, size=n)
    target = planned * (1 + (overrun_pct + err) / 100.0)
    k_s = np.maximum(0.3, (target - t0) / max(span, 1e-6))
    noise = rng.triangular(lo, mode, hi, size=(n, len(order)))
    dur = unit[None, :] * k_s[:, None] * noise
    crash = np.array([crash_days.get(a.id, 0.0) for a in order])
    dur_rec = np.maximum(0.0, dur - crash[None, :] * dur / np.maximum(d_fc[None, :], 1e-6))

    before = _finish(order, active, preds, t0, dur, idx)
    after = _finish(order, active, preds, t0, dur_rec, idx)
    m_lo = min(before.min(), after.min(), deadline) / DAYS_PER_MONTH
    m_hi = max(np.percentile(before, 99), deadline) / DAYS_PER_MONTH
    edges = np.linspace(np.floor(m_lo), np.ceil(m_hi), 41)
    hb, _ = np.histogram(before / DAYS_PER_MONTH, bins=edges)
    ha, _ = np.histogram(after / DAYS_PER_MONTH, bins=edges)
    q = lambda arr, p: round(float(np.percentile(arr, p)), 1)
    return {
        "samples": n,
        "p_on_time_before": round(float((before <= deadline).mean()), 3),
        "p_on_time_after": round(float((after <= deadline).mean()), 3),
        "p50_before_day": q(before, 50), "p80_before_day": q(before, 80),
        "p50_after_day": q(after, 50), "p80_after_day": q(after, 80),
        "deadline_day": round(float(deadline), 1),
        "hist": {"edges_months": np.round(edges, 2).tolist(), "before": (hb / n).round(4).tolist(),
                 "after": (ha / n).round(4).tolist()},
        "method": f"{n} Monte Carlo runs: cross-validation forecast error resampled, "
                  f"activity durations x triangular({lo}, {mode}, {hi}).",
    }
