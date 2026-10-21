"""
Recovery orchestration: ML forecast -> schedule forecast -> LP recovery -> BIM element states.

Activity risk on the model
  project_risk  = 0.5 x P(high risk) + 0.5 x min(1, forecast overrun / (2 x threshold))
  activity_risk = project_risk x exp(-total_float / tau)
Delay only reaches the completion date through critical or near-critical work,
so activities with little float carry most of the project's risk. Levels:
high >= 0.5, medium >= 0.25, otherwise low. Completed work is shown as complete.
"""
from __future__ import annotations

import math

from .bim import get_bim
from .config import load_config
from .optimizer import optimise, time_cost_curve
from .scheduling import DAYS_PER_MONTH, cpm, forecast, load_schedule
from .sustainability import impact


def project_risk(prob: float, overrun: float) -> float:
    thr = load_config()["training"]["high_risk_threshold_pct"]
    return 0.5 * max(0.0, min(1.0, prob)) + 0.5 * max(0.0, min(1.0, overrun / (2 * thr)))


def run_recovery(gate: str, spi, time_overrun_pct: float, high_risk_probability: float = 0.5,
                 ld_per_day=None, budget_pkr=None, deadline_day=None, rework: str | None = None,
                 with_curve: bool = True, elapsed_pct: float | None = None, simulate_risk: bool = True,
                 weather_lost_offsets: list[int] | None = None) -> dict:
    cfg = load_config()
    acts = load_schedule()
    frac = cfg["gates"][gate]["elapsed_fraction"] if elapsed_pct in (None, "") else max(0.01, min(0.95, float(elapsed_pct) / 100))
    fc = forecast(acts, frac, spi, float(time_overrun_pct))
    weather = apply_weather(acts, fc, weather_lost_offsets) if weather_lost_offsets else None
    ld = cfg["optimizer"]["default_ld_per_day_pkr"] if ld_per_day in (None, "") else float(ld_per_day)
    budget = float(budget_pkr) if budget_pkr not in (None, "", 0) else None
    deadline = fc["planned_finish"] if deadline_day in (None, "") else float(deadline_day)
    opt = optimise(acts, fc, ld, budget, deadline)
    ok = opt.get("status") == "Optimal"
    curve = time_cost_curve(acts, fc, ld, deadline) if ok and with_curve else []

    spi_u, t0, tau = fc["spi_used"], fc["t0"], cfg["optimizer"]["criticality_tau_days"]
    proj = project_risk(float(high_risk_probability), float(time_overrun_pct))
    base, f = fc["baseline"], fc["forecast"]
    rec = opt.get("recovered") if ok else None
    crash = opt.get("crash_days", {}) if ok else {}
    rows = []
    for a in acts:
        pct = fc["pct_complete"][a.id]
        bs, bf = base["es"][a.id], base["ef"][a.id]
        started = min(bs / spi_u, t0)                      # earned-schedule mapping of the start
        if pct >= 1.0:
            fs, ff = started, min(bf / spi_u, t0)
            rs, rf, status, tf, critical, risk = fs, ff, "complete", None, False, 0.0
        else:
            fs = started if pct > 0 else f["es"][a.id]
            ff = f["ef"][a.id]
            rs = started if pct > 0 else (rec["es"][a.id] if rec else fs)
            rf = rec["ef"][a.id] if rec else ff
            status = "in progress" if pct > 0 else "not started"
            tf, critical = f["tf"][a.id], a.id in f["critical"]
            risk = proj * math.exp(-tf / tau)
        level = "complete" if status == "complete" else ("high" if risk >= 0.5 else "medium" if risk >= 0.25 else "low")
        rows.append({
            "id": a.id, "name": a.name, "wbs": a.wbs, "trade": a.trade, "crash_method": a.crash_method,
            "baseline": [round(bs, 1), round(bf, 1)], "forecast": [round(fs, 1), round(ff, 1)],
            "recovered": [round(rs, 1), round(rf, 1)], "pct_complete": round(pct * 100, 1), "status": status,
            "total_float": None if tf is None else round(tf, 1), "critical": critical,
            "crash_days": round(crash.get(a.id, 0.0), 1), "risk_score": round(risk, 3), "risk_level": level,
        })

    quantities = None
    try:
        bim = get_bim()
        quantities = bim.quantities(acts) if bim else None
    except Exception:  # the recovery never depends on the BIM model
        quantities = None
    opt_public = {k: v for k, v in opt.items() if k not in ("recovered", "crash_days")}
    sim = None
    if ok and simulate_risk:
        from .inference import get_predictor
        from .simulation import simulate
        residuals = get_predictor().gates[gate]["meta"].get("time_residuals")
        sim = simulate(acts, fc, crash, deadline, float(time_overrun_pct), residuals)
    return {
        "gate": gate, "t0_day": round(t0, 1), "earned_schedule_day": round(fc["earned_schedule"], 1),
        "spi_used": spi_u, "duration_scale_k": round(fc["k"], 3),
        "planned_finish_day": round(fc["planned_finish"], 1), "forecast_finish_day": round(fc["forecast_finish"], 1),
        "deadline_day": round(deadline, 1), "project_risk": round(proj, 3),
        "months": {"planned": round(fc["planned_finish"] / DAYS_PER_MONTH, 1),
                   "forecast": round(fc["forecast_finish"] / DAYS_PER_MONTH, 1),
                   "recovered": round(opt.get("recovered_finish_day", fc["forecast_finish"]) / DAYS_PER_MONTH, 1)},
        "activities": rows, "optimisation": opt_public, "curve": curve, "simulation": sim,
        "elapsed_pct": round(frac * 100, 1), "weather": weather, "bim_connected": quantities is not None,
        "sustainability": impact(opt, quantities, rework), "bim_quantities": quantities,
    }


def apply_weather(acts, fc: dict, offsets: list[int]) -> dict:
    """Add each forecast lost-weather day (offset 0 = today = checkpoint) to every
    weather-sensitive remaining activity that is on site that day, then re-run CPM."""
    offs = sorted({int(o) for o in offsets if 0 <= int(o) <= 31})
    f, t0, active = fc["forecast"], fc["t0"], set(fc["active"])
    by_id = {a.id: a for a in acts}
    added = {}
    for a in acts:
        if a.id in active and a.is_weather_sensitive:
            n = sum(1 for o in offs if f["es"][a.id] <= t0 + o < f["ef"][a.id])
            if n:
                added[a.id] = n
    before = fc["forecast_finish"]
    if added:
        for i, n in added.items():
            fc["forecast_durations"][i] += n
        fc["forecast"] = cpm(acts, fc["forecast_durations"], t0=t0, active=active)
        fc["forecast_finish"] = fc["forecast"]["finish"]
    return {"lost_days_ahead": len(offs),
            "affected": [{"id": i, "name": by_id[i].name, "days": n} for i, n in added.items()],
            "finish_shift_days": round(fc["forecast_finish"] - before, 1)}


def element_properties(result: dict, prediction: dict | None = None, label: str = "") -> dict[str, dict]:
    """Per-element values written to Pset_REVIVE_Risk in the exported IFC."""
    bim = get_bim()
    if bim is None:
        raise ValueError("No BIM model is connected")
    mapping = bim.mapping(load_schedule())
    by_act = {r["id"]: r for r in result["activities"]}
    out = {}
    for guid, aid in mapping.items():
        if not aid or aid not in by_act:
            continue
        r = by_act[aid]
        props = {
            "Assessment": label or "REVIVE assessment",
            "ActivityId": r["id"], "ActivityName": r["name"], "Status": r["status"],
            "PlannedStart_day": float(r["baseline"][0]), "PlannedFinish_day": float(r["baseline"][1]),
            "ForecastFinish_day": float(r["forecast"][1]), "RecoveredFinish_day": float(r["recovered"][1]),
            "OnCriticalPath": bool(r["critical"]), "RiskScore": float(r["risk_score"]),
            "RiskLevel": r["risk_level"], "RecoveryCrash_days": float(r["crash_days"]),
        }
        if r["total_float"] is not None:
            props["TotalFloat_days"] = float(r["total_float"])
        if prediction:
            props["ProjectForecastOverrun_pct"] = float(prediction.get("time_overrun_pct", 0))
            props["ProjectHighRiskProbability"] = float(prediction.get("high_risk_probability", 0))
        out[guid] = props
    return out
