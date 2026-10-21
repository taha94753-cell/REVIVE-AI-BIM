"""
Recovery optimiser — linear programme (time-cost trade-off / CPM crashing).

Sets and data (remaining activities only, from the ML-driven forecast)
  i in A            remaining activities, (i, j) in P  finish-to-start links
  d_i               forecast remaining duration of i (days)
  c_i               crash cost per day recovered on i (PKR/day)
  u_i               maximum crashable days on i  (= crash fraction x d_i)
  t0                checkpoint (today) in project days
  D                 contract completion (deadline) in project days
  LD                liquidated damages per day late (PKR/day)
  B                 optional recovery budget cap (PKR)

Decision variables
  S_i >= t0         start of activity i
  0 <= y_i <= u_i   days crashed on activity i
  T                 project finish;  L >= 0  days late beyond D

Model
  minimise   Z = sum_i c_i y_i  +  LD * L
  subject to S_j >= S_i + d_i - y_i      for every (i, j) in P    (precedence)
             T   >= S_i + d_i - y_i      for every i              (finish)
             L   >= T - D                                           (lateness)
             sum_i c_i y_i <= B                                     (budget, optional)

Because Z trades crash cost against LD exposure, the optimum only buys a day of
acceleration when it is cheaper than paying for that day late — the rule a
planner applies by hand, solved exactly. Solver: CBC via PuLP (open source).
"""
from __future__ import annotations

import pulp

from .config import load_config
from .scheduling import Activity, cpm


def _var(prob, name, low=None, up=None):
    """Create a continuous variable on both PuLP 2.x (LpVariable) and PuLP 3+/4 (add_variable)."""
    if hasattr(prob, "add_variable"):
        return prob.add_variable(name, low, up)
    return pulp.LpVariable(name, lowBound=low, upBound=up)


def _solver():
    """Silent CBC on PuLP 2.x; default bundled solver on newer PuLP releases."""
    if hasattr(pulp, "PULP_CBC_CMD"):
        return pulp.PULP_CBC_CMD(msg=False)
    try:
        return pulp.getSolver("PULP_CBC_CMD", msg=False)
    except Exception:
        return None


def _solve(acts, fc, deadline, ld_per_day, budget=None, hard_finish=None):
    active = set(fc["active"])
    by_id = {a.id: a for a in acts if a.id in active}
    d = fc["forecast_durations"]
    t0 = fc["t0"]
    prob = pulp.LpProblem("revive_recovery", pulp.LpMinimize)
    S = {i: _var(prob, f"S_{i}", t0) for i in by_id}
    y = {i: _var(prob, f"y_{i}", 0, by_id[i].crash_fraction * d[i]) for i in by_id}
    T = _var(prob, "T", t0)
    L = _var(prob, "L", 0)
    crash_cost = pulp.lpSum(by_id[i].crash_cost_per_day * y[i] for i in by_id)
    prob += crash_cost + ld_per_day * L + 1e-3 * T
    for j, a in by_id.items():
        for i in a.preds:
            if i in by_id:
                prob += S[j] >= S[i] + d[i] - y[i], f"prec_{i}_{j}"
    for i in by_id:
        prob += T >= S[i] + d[i] - y[i], f"fin_{i}"
    prob += L >= T - deadline, "late"
    if budget is not None and budget > 0:
        prob += crash_cost <= budget, "budget"
    if hard_finish is not None:
        prob += T <= hard_finish, "target"
    status = prob.solve(_solver())
    return pulp.LpStatus[status], {i: max(0.0, y[i].value() or 0.0) for i in by_id}, prob


def optimise(acts: list[Activity], fc: dict, ld_per_day: float | None = None, budget: float | None = None,
             deadline: float | None = None) -> dict:
    cfg = load_config()["optimizer"]
    ld = cfg["default_ld_per_day_pkr"] if ld_per_day is None else float(ld_per_day)
    deadline = fc["planned_finish"] if deadline is None else float(deadline)
    status, crash, _ = _solve(acts, fc, deadline, ld, budget)
    if status != "Optimal":
        return {"status": status, "message": "No feasible recovery plan under these limits. "
                                              "Raise the budget or allow a later target date."}
    active = set(fc["active"])
    d = fc["forecast_durations"]
    new_dur = {i: d[i] - crash[i] for i in active}
    rec = cpm(acts, new_dur, t0=fc["t0"], active=active)
    by_id = {a.id: a for a in acts}
    crash_cost = sum(by_id[i].crash_cost_per_day * crash[i] for i in active)
    late_before = max(0.0, fc["forecast_finish"] - deadline)
    late_after = max(0.0, rec["finish"] - deadline)
    plan = sorted(
        [{"id": i, "name": by_id[i].name, "trade": by_id[i].trade, "method": by_id[i].crash_method,
          "forecast_days": round(d[i], 1), "crashed_days": round(crash[i], 1),
          "cost_pkr": round(by_id[i].crash_cost_per_day * crash[i]),
          "cost_per_day_pkr": by_id[i].crash_cost_per_day,
          "on_critical_path": i in rec["critical"]}
         for i in active if crash[i] > 0.05],
        key=lambda r: -r["crashed_days"])
    return {
        "status": "Optimal",
        "deadline_day": round(deadline, 1), "ld_per_day_pkr": ld, "budget_pkr": budget,
        "forecast_finish_day": round(fc["forecast_finish"], 1), "recovered_finish_day": round(rec["finish"], 1),
        "days_recovered": round(fc["forecast_finish"] - rec["finish"], 1),
        "days_late_before": round(late_before, 1), "days_late_after": round(late_after, 1),
        "crash_cost_pkr": round(crash_cost),
        "ld_before_pkr": round(late_before * ld), "ld_after_pkr": round(late_after * ld),
        "net_saving_pkr": round(late_before * ld - (late_after * ld + crash_cost)),
        "plan": plan, "recovered": rec, "crash_days": {i: round(v, 2) for i, v in crash.items()},
        "formulation": FORMULATION,
    }


def time_cost_curve(acts: list[Activity], fc: dict, ld_per_day: float, deadline: float,
                    points: int | None = None) -> list[dict]:
    """Minimum crash cost for a range of target finish dates (parametric LP)."""
    points = points or load_config()["optimizer"]["curve_points"]
    active = set(fc["active"])
    by_id = {a.id: a for a in acts}
    d = fc["forecast_durations"]
    fastest = cpm(acts, {i: d[i] * (1 - by_id[i].crash_fraction) for i in active}, t0=fc["t0"], active=active)["finish"]
    slowest = fc["forecast_finish"]
    out = []
    for k in range(points):
        target = slowest - (slowest - fastest) * k / max(points - 1, 1)
        status, crash, _ = _solve(acts, fc, deadline, 0.0, None, hard_finish=target + 1e-6)
        if status != "Optimal":
            continue
        cost = sum(by_id[i].crash_cost_per_day * crash[i] for i in active)
        ld = max(0.0, target - deadline) * ld_per_day
        out.append({"finish_day": round(target, 1), "crash_cost_pkr": round(cost), "ld_pkr": round(ld),
                    "total_pkr": round(cost + ld)})
    return out


FORMULATION = {
    "objective": "min Z = sum(c_i * y_i) + LD * L",
    "constraints": [
        "S_j >= S_i + d_i - y_i  for each finish-to-start link (i, j)",
        "T >= S_i + d_i - y_i  for each activity i",
        "L >= T - D,  L >= 0",
        "0 <= y_i <= u_i,  S_i >= t0",
        "sum(c_i * y_i) <= B  (when a budget cap is set)",
    ],
    "solver": "CBC (COIN-OR) through PuLP",
}
