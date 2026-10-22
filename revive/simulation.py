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

What drives the finish (criticality index, ported from the REVIVE web app): in every
run the critical path is traced back from the last activity to finish, through the
predecessor that set each start. An activity's criticality is the share of runs it
sits on that path. 100% means it drives the finish in every plausible future; 40%
means a slip there matters in four futures out of ten.
"""
from __future__ import annotations

import numpy as np

from .config import load_config
from .scheduling import DAYS_PER_MONTH, Activity, topo_order


def _forward(order, active, preds, t0, dur: np.ndarray, idx: dict):
    """Early finishes per run, and for each activity the index (into order) of the predecessor that set its
    start in that run (-1 = it started at t0)."""
    n = dur.shape[0]
    ef = np.zeros((n, len(order)))
    driver = np.full((n, len(order)), -1, dtype=int)
    for a in order:
        j = idx[a.id]
        start = np.full(n, float(t0))
        for p in preds[a.id]:
            if p in active:
                k = idx[p]
                later = ef[:, k] > start
                start = np.where(later, ef[:, k], start)
                driver[:, j] = np.where(later, k, driver[:, j])
        ef[:, j] = start + dur[:, j]
    return ef, driver


def _finish(order, active, preds, t0, dur: np.ndarray, idx: dict) -> np.ndarray:
    if not order:
        return np.full(dur.shape[0], t0)
    ef, _ = _forward(order, active, preds, t0, dur, idx)
    return ef.max(axis=1)


def criticality(order, active, preds, t0, dur: np.ndarray, idx: dict) -> np.ndarray:
    """Share of runs in which each activity (in `order`) is on the critical path."""
    ef, driver = _forward(order, active, preds, t0, dur, idx)
    n = dur.shape[0]
    on = np.zeros((n, len(order)), dtype=bool)
    cur = ef.argmax(axis=1)
    rows = np.arange(n)
    for _ in range(len(order)):            # each step moves one activity back; a path is at most len(order) long
        live = cur >= 0
        if not live.any():
            break
        on[rows[live], cur[live]] = True
        nxt = np.full(n, -1)
        nxt[live] = driver[rows[live], cur[live]]
        cur = nxt
    return on.mean(axis=0)


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
    crit = criticality(order, active, preds, t0, dur, idx)
    ranked = sorted(range(len(order)), key=lambda j: -crit[j])
    drivers = [{"id": order[j].id, "name": order[j].name, "criticality": round(float(crit[j]), 3),
                "crash_days": round(float(crash_days.get(order[j].id, 0.0)), 1)}
               for j in ranked if crit[j] >= 0.05][:10]
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
        "drivers": drivers,
        "hist": {"edges_months": np.round(edges, 2).tolist(), "before": (hb / n).round(4).tolist(),
                 "after": (ha / n).round(4).tolist()},
        "method": f"{n} Monte Carlo runs: cross-validation forecast error resampled, "
                  f"activity durations x triangular({lo}, {mode}, {hi}).",
    }
