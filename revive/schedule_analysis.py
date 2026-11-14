"""
Schedule analysis: what the baseline schedule and its progress updates say on their own.

Reads the baseline network (CPM) plus whatever the schedule file carried (schedule_import.read_loading):
budget and actual cost per activity, resource assignments, % complete. It never uses the ML model.

What it reports
  * S-curves    cumulative planned work on early dates and on late dates (the "banana"). Work is
                weighted by budget cost when at least half of the activities carry a budget
                (schedule_analysis.min_cost_coverage), otherwise by duration. The basis is always stated.
  * Earned value at each progress update (status date = actual time AT):
                PV = planned work at AT (early curve), EV = sum(weight x % complete), AC = actual cost.
                SPI = EV / PV, SV = EV - PV, SPI(t) = ES / AT with ES from the earned-schedule method.
                CPI = EV / AC, CV = EV - AC, EAC = BAC / CPI, TCPI = (BAC - EV) / (BAC - AC).
                CPI needs a cost-loaded schedule AND actual cost. Without them it is None, with the reason.
  * Resources   units per period per resource, spread evenly over each activity's early dates.
                Without resource loading: activity-days in hand per trade.
  * Cash flow   planned cost per period on early and late dates (cost-loaded schedules only).
  * Quality     open ends, logic density, critical share, high float, long activities. Thresholds are in
                config.yaml (after the DCMA 14-point assessment; marked VERIFY).

Progress updates (the schedule is not static)
  The baseline stays fixed. A later export of the same programme is matched to it by activity id and
  kept as a dated snapshot: % complete and actual cost per activity. Each snapshot gives one status
  point, so SPI and CPI can be followed over time, and the latest one also feeds the current delay
  analysis (projects.progress). Activities added, removed or re-timed since the baseline are counted,
  because a revised programme may need a new baseline rather than an update.
"""
from __future__ import annotations

import math
from datetime import date, datetime

from .config import load_config
from .delay import earned_schedule
from .scheduling import DAYS_PER_MONTH, cpm

MAX_UPDATES = 60
DEFAULTS = {"working_days_per_month": 26, "min_cost_coverage": 0.5, "max_periods": 120, "top_resources": 6,
            "high_float_days": 44, "long_activity_days": 44, "open_ends_max_pct": 5, "high_float_max_pct": 5,
            "long_activity_max_pct": 5, "critical_share_watch_pct": 40,
            "gate_windows": {"G25": [20, 32], "G50": [44, 58]}}


def settings() -> dict:
    return {**DEFAULTS, **(load_config().get("schedule_analysis") or {})}


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _r(v, n=2):
    return None if v is None or (isinstance(v, float) and not math.isfinite(v)) else round(float(v), n)


# ------------------------------------------------------------------ weights and curves
def weights(acts, loading: dict | None) -> tuple[dict, str, float]:
    """Weight of each activity in the progress measure: budget cost when the schedule is cost-loaded, else duration."""
    la = (loading or {}).get("activities") or {}
    budget = {a.id: max(0.0, float((la.get(a.id) or {}).get("budget") or 0)) for a in acts}
    work = [a for a in acts if a.duration > 0]
    total = sum(budget.values())
    if total > 0 and work and sum(budget[a.id] > 0 for a in work) / len(work) >= settings()["min_cost_coverage"]:
        return budget, "cost", total
    dur = {a.id: max(a.duration, 0.0) for a in acts}
    return dur, "duration", sum(dur.values())


def _share(acts, w, start: dict, t: float) -> float:
    """Cumulative weighted share of work planned by time t, each activity progressing linearly from start[id]."""
    total = sum(w.values()) or 1.0
    s = 0.0
    for a in acts:
        if w[a.id] <= 0:
            continue
        s += w[a.id] * (_clamp((t - start[a.id]) / a.duration) if a.duration > 0 else float(t >= start[a.id]))
    return s / total


def _breakpoints(base) -> list[float]:
    return sorted({0.0, float(base["finish"]), *map(float, base["es"].values()), *map(float, base["ef"].values()),
                   *map(float, base["ls"].values()), *map(float, base["lf"].values())})


def periods(planned: float, contract_months: float | None = None) -> tuple[list[float], str]:
    """Period edges in schedule days. One period is a contract month when the contract duration is known."""
    cfg = settings()
    if contract_months and contract_months >= 1:
        n, unit = int(math.ceil(contract_months - 1e-9)), "month"
    else:
        n, unit = int(math.ceil(planned / cfg["working_days_per_month"])) or 1, "month"
    n = max(1, min(int(cfg["max_periods"]), n))
    step = planned / n if planned > 0 else 1.0
    return [round(i * step, 4) for i in range(n)] + [float(planned)], unit


# ------------------------------------------------------------------ one status point
def status(acts, base, w, basis: str, bac: float, pct: dict, actual: dict, elapsed_pct: float) -> dict:
    planned = float(base["finish"])
    at = _clamp(elapsed_pct / 100.0, 0, 3) * planned
    total = sum(w.values()) or 1.0
    ts = _breakpoints(base)
    curve = (ts, [_share(acts, w, base["es"], t) for t in ts])
    pv = _share(acts, w, base["es"], at)
    ev = 0.0
    for a in acts:
        p = pct.get(a.id)
        if p is None:      # not reported: assumed to follow the plan, as in the current delay analysis
            done = _clamp((at - base["es"][a.id]) / a.duration) if a.duration > 0 else float(at >= base["es"][a.id])
        else:
            done = _clamp(float(p) / 100.0)
        ev += w[a.id] * done
    ev /= total
    es = earned_schedule(curve, ev)
    out = {"elapsed_pct": _r(elapsed_pct, 1), "at": _r(at), "pv_pct": _r(100 * pv), "ev_pct": _r(100 * ev),
           "spi": _r(ev / pv, 3) if pv > 0 else None, "es": _r(es), "sv_days": _r(es - at),
           "spi_t": _r(es / at, 3) if at > 0 else None, "cpi": None, "cpi_reason": None,
           "reported": sum(v is not None for v in (pct.get(a.id) for a in acts))}
    ac = sum(float(v or 0) for v in actual.values())
    if basis != "cost":
        out["cpi_reason"] = ("The schedule is not cost-loaded (fewer than half of its activities carry a budget), "
                             "so earned value in money and CPI cannot be measured from it.")
    elif ac <= 0:
        out["cpi_reason"] = "The update carries no actual cost, so CPI cannot be measured from it."
    else:
        evc, pvc = ev * bac, pv * bac
        cpi = evc / ac
        out.update({"cpi": _r(cpi, 3), "pv": _r(pvc, 0), "ev": _r(evc, 0), "ac": _r(ac, 0), "sv": _r(evc - pvc, 0),
                    "cv": _r(evc - ac, 0), "bac": _r(bac, 0), "eac": _r(bac / cpi, 0) if cpi > 0 else None,
                    "vac": _r(bac - bac / cpi, 0) if cpi > 0 else None,
                    "tcpi": _r((bac - evc) / (bac - ac), 3) if bac - ac > 0 else None})
    return out


# ------------------------------------------------------------------ resources, cash flow, quality
def _spread(start: float, dur: float, edges: list[float]) -> list[float]:
    """Share of an activity falling in each period (linear over its duration; a milestone lands in one period)."""
    n = len(edges) - 1
    out = [0.0] * n
    if dur <= 0:
        i = max(0, min(n - 1, sum(start >= e for e in edges[1:-1])))
        out[i] = 1.0
        return out
    for i in range(n):
        out[i] = max(0.0, min(start + dur, edges[i + 1]) - max(start, edges[i])) / dur
    return out


def resources(acts, base, loading: dict | None, edges: list[float]) -> dict:
    la = (loading or {}).get("activities") or {}
    n = len(edges) - 1
    series: dict[str, list[float]] = {}
    kinds: dict[str, str] = {}
    materials: dict[str, float] = {}
    for a in acts:
        spread = None
        for r in (la.get(a.id) or {}).get("resources") or []:
            units = float(r.get("units") or 0)
            if units <= 0:
                continue
            if r.get("type") == "material":
                materials[r["name"]] = materials.get(r["name"], 0.0) + units
                continue
            spread = spread or _spread(base["es"][a.id], a.duration, edges)
            row = series.setdefault(r["name"], [0.0] * n)
            kinds[r["name"]] = r.get("type") or "other"
            for i in range(n):
                row[i] += units * spread[i]
    basis, unit = "resource assignments", "hours"
    if not series:        # no resource loading: work in hand per trade, in activity-days
        basis, unit = "trade (no resource loading in the schedule)", "activity-days"
        for a in acts:
            if a.duration <= 0:
                continue
            row = series.setdefault(a.trade or "Unassigned", [0.0] * n)
            for i, s in enumerate(_spread(base["es"][a.id], a.duration, edges)):
                row[i] += a.duration * s
    ranked = sorted(series.items(), key=lambda kv: -sum(kv[1]))
    top = int(settings()["top_resources"])
    rows = [{"name": k, "type": kinds.get(k, "trade"), "total": _r(sum(v), 1), "by_period": [_r(x, 1) for x in v],
             "peak": _r(max(v), 1), "peak_period": v.index(max(v)) + 1} for k, v in ranked[:top]]
    if ranked[top:]:
        rest = [sum(v[i] for _, v in ranked[top:]) for i in range(n)]
        rows.append({"name": f"{len(ranked) - top} others", "type": "other", "total": _r(sum(rest), 1),
                     "by_period": [_r(x, 1) for x in rest], "peak": _r(max(rest), 1), "peak_period": rest.index(max(rest)) + 1})
    totals = [sum(v[i] for _, v in ranked) for i in range(n)]
    mean = sum(totals) / n if n else 0.0
    return {"basis": basis, "unit": unit, "rows": rows, "total_by_period": [_r(x, 1) for x in totals],
            "peak": _r(max(totals), 1) if totals else 0, "peak_period": totals.index(max(totals)) + 1 if totals else None,
            "peak_to_average": _r(max(totals) / mean, 2) if mean > 0 else None,
            "materials": [{"name": k, "units": _r(v, 1)} for k, v in sorted(materials.items(), key=lambda kv: -kv[1])[:8]]}


def cash_flow(acts, base, w, bac: float, edges: list[float]) -> dict:
    early = [bac * (_share(acts, w, base["es"], edges[i + 1]) - _share(acts, w, base["es"], edges[i])) for i in range(len(edges) - 1)]
    late = [bac * (_share(acts, w, base["ls"], edges[i + 1]) - _share(acts, w, base["ls"], edges[i])) for i in range(len(edges) - 1)]
    return {"early": [_r(x, 0) for x in early], "late": [_r(x, 0) for x in late],
            "peak": _r(max(early), 0) if early else 0, "peak_period": early.index(max(early)) + 1 if early else None}


def quality(acts, base) -> dict:
    cfg = settings()
    n = len(acts) or 1
    succ = {a.id: 0 for a in acts}
    links = 0
    for a in acts:
        for p in a.preds:
            if p in succ:
                succ[p] += 1
                links += 1
    no_pred = [a.id for a in acts if not a.preds]
    no_succ = [a.id for a in acts if succ[a.id] == 0]
    open_ends = max(0, len(no_pred) - 1) + max(0, len(no_succ) - 1)      # one start and one finish are expected
    work = [a for a in acts if a.duration > 0]
    high_float = [a.id for a in work if base["tf"][a.id] > cfg["high_float_days"]]
    long_acts = [a.id for a in work if a.duration > cfg["long_activity_days"]]
    crit = [a for a in work if a.id in set(base["critical"])]
    pct = lambda k, of=None: round(100.0 * k / (of or n), 1)
    tf = [base["tf"][a.id] for a in work]
    checks = [
        {"key": "open_ends", "label": "Open ends", "value": open_ends, "pct": pct(open_ends),
         "ok": pct(open_ends) <= cfg["open_ends_max_pct"],
         "note": "Activities with no predecessor or no successor, beyond the one start and one finish. "
                 "Each one breaks the logic that carries a delay to the finish date.", "ids": (no_pred[1:] + no_succ[1:])[:8]},
        {"key": "high_float", "label": f"Float above {cfg['high_float_days']} days", "value": len(high_float),
         "pct": pct(len(high_float), len(work) or 1), "ok": pct(len(high_float), len(work) or 1) <= cfg["high_float_max_pct"],
         "note": "Very high float usually means a missing link, not real freedom.", "ids": high_float[:8]},
        {"key": "long_activities", "label": f"Activities longer than {cfg['long_activity_days']} days", "value": len(long_acts),
         "pct": pct(len(long_acts), len(work) or 1), "ok": pct(len(long_acts), len(work) or 1) <= cfg["long_activity_max_pct"],
         "note": "Long activities hide progress: split them so % complete can be judged.", "ids": long_acts[:8]},
        {"key": "critical_share", "label": "Critical activities", "value": len(crit), "pct": pct(len(crit), len(work) or 1),
         "ok": pct(len(crit), len(work) or 1) <= cfg["critical_share_watch_pct"],
         "note": "A large critical share leaves little room to absorb a slip.", "ids": [a.id for a in crit][:8]},
    ]
    return {"activities": len(acts), "milestones": len(acts) - len(work), "links": links,
            "links_per_activity": round(links / n, 2), "planned_days": _r(base["finish"], 1),
            "critical_days_share_pct": pct(sum(a.duration for a in crit), sum(a.duration for a in work) or 1),
            "float": {"zero": sum(v < 1e-6 for v in tf), "up_to_10": sum(1e-6 <= v <= 10 for v in tf),
                      "up_to_30": sum(10 < v <= 30 for v in tf), "above_30": sum(v > 30 for v in tf)},
            "checks": checks}


# ------------------------------------------------------------------ progress updates
def compare(base_acts, upd_acts) -> dict:
    """What changed in the programme itself between the baseline and an updated export."""
    b, u = {a.id: a for a in base_acts}, {a.id: a for a in upd_acts}
    added, removed = [i for i in u if i not in b], [i for i in b if i not in u]
    retimed = [i for i in u if i in b and abs(u[i].duration - b[i].duration) > 0.01]
    relinked = [i for i in u if i in b and set(u[i].preds) != set(b[i].preds)]
    return {"matched": len(u) - len(added), "added": len(added), "removed": len(removed), "retimed": len(retimed),
            "relinked": len(relinked), "added_ids": added[:8], "removed_ids": removed[:8], "retimed_ids": retimed[:8],
            "revised": bool(added or removed or retimed or relinked)}


def _days(a: str | None, b: str | None) -> int | None:
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except (TypeError, ValueError):
        return None


def elapsed_pct(project: dict, as_of: str | None, base_loading: dict | None, upd_loading: dict | None,
                planned_days: float) -> float | None:
    """Share of contract time elapsed at the status date: contract start and duration first, else the file's own dates."""
    det, inputs = project.get("details") or {}, project.get("inputs") or {}
    months = float(det.get("planned_months") or inputs.get("planned_months") or 0)
    gone = _days(project.get("start_date"), as_of)
    if gone is not None and months > 0:
        return _clamp(100.0 * gone / (months * DAYS_PER_MONTH), 0, 300)
    for src in (base_loading, upd_loading):
        span, gone = _days((src or {}).get("start"), (src or {}).get("finish")), _days((src or {}).get("start"), as_of)
        if span and span > 0 and gone is not None:
            return _clamp(100.0 * gone / span, 0, 300)
    return None


def snapshot(base_acts, upd_acts, upd_loading: dict, as_of: str, elapsed: float, file_name: str, fmt: str) -> dict:
    ids = {a.id for a in base_acts}
    la = upd_loading.get("activities") or {}
    return {"as_of": as_of, "elapsed_pct": round(float(elapsed), 1), "uploaded_at": datetime.now().isoformat(timespec="seconds"),
            "file": str(file_name)[:120], "format": fmt,
            "pct": {i: (None if (la.get(i) or {}).get("pct") is None else round(float(la[i]["pct"]), 1)) for i in ids if i in la},
            "actual": {i: round(float((la.get(i) or {}).get("actual_cost") or 0), 2) for i in ids
                       if (la.get(i) or {}).get("actual_cost")},
            "compare": compare(base_acts, upd_acts)}


def progress_from(snap: dict) -> dict | None:
    """The shape projects.progress expects, so the current delay analysis runs on the latest update."""
    acts = {i: v for i, v in (snap.get("pct") or {}).items() if v is not None}
    return {"as_of": snap["as_of"], "elapsed_pct": snap["elapsed_pct"], "activities": acts} if acts else None


# ------------------------------------------------------------------ the whole analysis
def analyse(project: dict, acts) -> dict:
    """Call inside projects.scope(project) with its schedule already loaded."""
    cfg = settings()
    base = cpm(acts)
    planned = float(base["finish"])
    loading = project.get("loading")
    w, basis, bac = weights(acts, loading)
    det, inputs = project.get("details") or {}, project.get("inputs") or {}
    months = float(det.get("planned_months") or inputs.get("planned_months") or 0) or None
    edges, unit = periods(planned, months)
    ts = _breakpoints(base)
    span = planned or 1.0
    updates = project.get("schedule_updates") or []
    history = []
    for i, u in enumerate(updates):
        st = status(acts, base, w, basis, bac, u.get("pct") or {}, u.get("actual") or {}, u.get("elapsed_pct") or 0)
        history.append({"index": i, "as_of": u.get("as_of"), "file": u.get("file"), "format": u.get("format"),
                        "uploaded_at": u.get("uploaded_at"), "compare": u.get("compare"), **st})
    latest = history[-1] if history else None
    suggested = None
    if latest and latest.get("spi") is not None:
        for gate, (lo, hi) in cfg["gate_windows"].items():
            if lo <= latest["elapsed_pct"] <= hi:
                k = gate[1:]
                suggested = {"gate": gate, "as_of": latest["as_of"], "inputs": {f"spi_{k}": _r(_clamp(latest["spi"], 0.2, 1.5), 2)}}
                if latest.get("cpi") is not None:
                    suggested["inputs"][f"cpi_{k}"] = _r(_clamp(latest["cpi"], 0.2, 1.5), 2)
    notes = []
    if basis == "duration":
        notes.append("Progress is weighted by activity duration because the schedule is not cost-loaded. "
                     "Upload a cost-loaded P6 or MS Project file to get earned value in money, CPI and cash flow.")
    if latest and (latest.get("compare") or {}).get("revised"):
        c = latest["compare"]
        notes.append(f"The latest update differs from the baseline programme: {c['added']} activities added, "
                     f"{c['removed']} removed, {c['retimed']} re-timed, {c['relinked']} re-linked. Progress is measured "
                     "against the baseline; if the programme was formally revised, upload it as a new baseline.")
    return {
        "basis": basis, "bac": _r(bac, 0) if basis == "cost" else None, "planned_days": _r(planned, 1),
        "period_unit": unit, "periods": len(edges) - 1,
        "curve": {"t_pct": [_r(100 * t / span, 2) for t in ts],
                  "early_pct": [_r(100 * _share(acts, w, base["es"], t), 2) for t in ts],
                  "late_pct": [_r(100 * _share(acts, w, base["ls"], t), 2) for t in ts]},
        "cash_flow": cash_flow(acts, base, w, bac, edges) if basis == "cost" else None,
        "resources": resources(acts, base, loading, edges),
        "quality": quality(acts, base),
        "status": latest, "history": history, "suggested_inputs": suggested, "notes": notes,
        "has_loading": bool((loading or {}).get("activities")), "max_updates": MAX_UPDATES,
    }
