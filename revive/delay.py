"""
Current delay analysis: how late the project is NOW, measured from the baseline schedule and the
latest site data. It does not use the machine-learning model, so it is an independent cross-check
on the forecast.

Method (each step can be defended in the viva)
  1. Planned progress curve PV(t): cumulative share of planned work against time from the CPM
     early-start baseline. Work in each activity is weighted by its duration (the schedule carries
     no cost loading) and is assumed to progress linearly. PV(t) is piecewise linear, so it is exact
     between activity start/finish dates.
  2. Status at the status date (actual time AT = elapsed share x planned duration):
       * from site reports: EV = SPI x PV(AT)   (or EV = value certified, if SPI is not given)
       * from activity progress, when the planner enters it: EV = sum(duration x % complete) / sum(duration)
     Earned Schedule ES is the time at which the plan reached EV (Lipke 2003): ES = PV^-1(EV).
     Schedule variance in time SV(t) = ES - AT; SPI(t) = ES / AT.
  3. Schedule update: the remaining work (planned duration x share not done) is re-networked from
     AT with the baseline logic (retained logic). Delay to date = updated finish - planned finish.
     With site reports only, progress is mapped onto the baseline sequence, so this equals AT - ES;
     with activity progress it also captures out-of-sequence work.
  4. Where it is going, three ways, side by side: if the remaining work goes to plan
     (planned finish + delay to date), if the current pace continues (ES method: planned duration / SPI(t)),
     and the REVIVE machine-learning forecast.
  5. Contemporaneous windows: between consecutive site updates, the change in SV(t) is the slip in
     that window. Slip is apportioned to the events reported in the same window: weather days are
     counted as days (neutral risk); the rest is shared by event count between client-side events
     (late IPCs, variations, design changes/RFIs) and contractor-side events (material stoppages,
     falling labour or subcontractor ratings). Windows with both are flagged as concurrent.
     This is an indicative apportionment to flag delay worth a notice, NOT a forensic delay analysis
     (SCL Protocol / AACE 29R-03); a planner must verify any claim.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from .config import load_config
from .scheduling import DAYS_PER_MONTH, cpm, load_schedule

EVENT_CLASS = {
    "late_payments": ("client", "IPCs paid late"),
    "variations": ("client", "variation orders"),
    "rfis": ("client", "design changes or RFIs"),
    "weather_days": ("neutral", "weather days lost"),
    "material_events": ("contractor", "material stoppages"),
    "labour": ("contractor", "labour rating fell"),
    "subcontractor": ("contractor", "subcontractor rating fell"),
}
CATEGORY_LABEL = {"client": "Client-side events", "neutral": "Weather (neutral)",
                  "contractor": "Contractor-side events", "unexplained": "No event reported"}
DEFAULT_BANDS = [{"name": "On programme", "max_pct": 2, "color": "#3DD68C"},
                 {"name": "Minor slip", "max_pct": 5, "color": "#F2C94C"},
                 {"name": "Significant slip", "max_pct": 10, "color": "#FF8A3D"},
                 {"name": "Critical slip", "max_pct": 100000, "color": "#FF4D5E"}]


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _num(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ planned progress curve
def planned_curve(acts, base) -> tuple[list[float], list[float]]:
    """Breakpoints t and cumulative planned share PV(t) in [0, 1] (early-start baseline, duration-weighted)."""
    total = sum(max(a.duration, 0.0) for a in acts) or 1.0
    ts = sorted({0.0, float(base["finish"]), *map(float, base["es"].values()), *map(float, base["ef"].values())})

    def pv(t):
        s = 0.0
        for a in acts:
            d = max(a.duration, 0.0)
            if d > 0:
                s += d * _clamp((t - base["es"][a.id]) / d)
        return s / total
    return ts, [round(pv(t), 6) for t in ts]


def pv_at(curve, t: float) -> float:
    ts, pv = curve
    if t <= ts[0]:
        return pv[0]
    for i in range(1, len(ts)):
        if t <= ts[i]:
            span = ts[i] - ts[i - 1]
            return pv[i - 1] + (pv[i] - pv[i - 1]) * ((t - ts[i - 1]) / span if span > 0 else 1)
    return pv[-1]


def earned_schedule(curve, ev: float) -> float:
    """ES = time at which the plan reached EV (first crossing; flat stretches resolve to their start)."""
    ts, pv = curve
    ev = _clamp(ev)
    if ev <= pv[0]:
        return ts[0]
    for i in range(1, len(ts)):
        if pv[i] >= ev - 1e-12:
            rise = pv[i] - pv[i - 1]
            return ts[i - 1] + (ts[i] - ts[i - 1]) * ((ev - pv[i - 1]) / rise if rise > 0 else 1)
    return ts[-1]


# ------------------------------------------------------------------ one status point
def status_point(curve, planned: float, elapsed_pct: float, spi=None, cert=None, ev_share=None) -> dict | None:
    at = _clamp(elapsed_pct / 100.0, 0, 3) * planned
    pv = pv_at(curve, at)
    if ev_share is not None:
        ev, basis = _clamp(ev_share), "activity progress"
    elif spi is not None:
        ev, basis = _clamp(spi * pv), "SPI reported from site"
    elif cert is not None:
        ev, basis = _clamp(cert / 100.0), "value certified"
    else:
        return None
    es = earned_schedule(curve, ev)
    return {"at": round(at, 2), "pv": round(pv, 4), "ev": round(ev, 4), "es": round(es, 2),
            "sv_t": round(es - at, 2), "spi_t": round(es / at, 3) if at > 0 else None, "basis": basis,
            "elapsed_pct": round(elapsed_pct, 1)}


def _band(delay_days: float, planned: float) -> dict:
    bands = (load_config().get("delay") or {}).get("bands") or DEFAULT_BANDS
    pct = 100.0 * max(0.0, delay_days) / max(planned, 1e-9)
    for b in bands:
        if pct <= b["max_pct"]:
            return {**b, "pct_of_duration": round(pct, 1)}
    return {**bands[-1], "pct_of_duration": round(pct, 1)}


# ------------------------------------------------------------------ schedule update from the status date
def schedule_update(acts, base, at: float, es: float, activity_pct: dict | None = None) -> dict:
    """Retained-logic CPM of the remaining work from the status date AT."""
    pct = {}
    for a in acts:
        if activity_pct is not None and a.id in activity_pct:
            pct[a.id] = _clamp(activity_pct[a.id] / 100.0)
        elif activity_pct is not None:
            # not entered by the planner: assume it is where the plan says it should be at the status date
            d = a.duration
            pct[a.id] = (1.0 if at >= base["ef"][a.id] else 0.0) if d <= 0 else _clamp((at - base["es"][a.id]) / d)
        else:
            d = a.duration
            pct[a.id] = 1.0 if base["ef"][a.id] <= es else (0.0 if base["es"][a.id] >= es or d <= 0
                                                             else _clamp((es - base["es"][a.id]) / d))
    remaining = {a.id: a.duration * (1 - pct[a.id]) for a in acts}
    active = {a.id for a in acts if pct[a.id] < 1.0 - 1e-9}
    upd = cpm(acts, remaining, t0=at, active=active)
    return {"pct": pct, "remaining": remaining, "active": active, "cpm": upd,
            "finish": upd["finish"] if active else at}


def activity_rows(acts, base, at, pct, upd, limit: int = 14) -> list[dict]:
    rows = []
    for a in acts:
        d = max(a.duration, 0.0)
        planned = _clamp((at - base["es"][a.id]) / d) if d > 0 else (1.0 if at >= base["es"][a.id] else 0.0)
        done = pct[a.id]
        behind = (planned - done) * d
        if planned <= 0 and done <= 0:
            continue
        crit = a.id in upd["cpm"]["critical"] if a.id in upd["active"] else False
        tf = upd["cpm"]["tf"].get(a.id) if a.id in upd["active"] else None
        status = "complete" if done >= 0.999 else "in progress" if done > 0 else "not started"
        rows.append({"id": a.id, "name": a.name, "trade": a.trade, "duration": round(d, 1),
                     "planned_pct": round(planned * 100, 1), "actual_pct": round(done * 100, 1),
                     "behind_days": round(behind, 1), "critical": crit, "total_float": None if tf is None else round(tf, 1),
                     "status": status, "late": behind > 0.5})
    rows.sort(key=lambda r: (not (r["critical"] and r["late"]), -r["behind_days"]))
    return rows[:limit]


# ------------------------------------------------------------------ windows over the site-update history
def _events_between(prev: dict | None, cur: dict) -> dict:
    out = {}
    pc = (prev or {}).get("counts") or {}
    for k, v in (cur.get("counts") or {}).items():
        dv = (v or 0) - (pc.get(k, 0) or 0)
        if dv > 1e-6:
            out[k] = round(dv, 1)
    if prev:
        for r in ("labour", "subcontractor"):
            if (cur.get(r) or 3) < (prev.get(r) or 3):
                out[r] = 1
    return out


def apportion(slip: float, events: dict) -> dict:
    """Share a window's slip (days) between event categories. See the module docstring (step 5)."""
    out = {"client": 0.0, "neutral": 0.0, "contractor": 0.0, "unexplained": 0.0}
    if slip <= 0:
        return out
    weather = events.get("weather_days", 0.0)
    out["neutral"] = min(weather, slip)
    rest = slip - out["neutral"]
    n = {"client": sum(events.get(k, 0) for k, (c, _) in EVENT_CLASS.items() if c == "client"),
         "contractor": sum(events.get(k, 0) for k, (c, _) in EVENT_CLASS.items() if c == "contractor")}
    tot = n["client"] + n["contractor"]
    if rest > 0:
        if tot > 0:
            out["client"] = rest * n["client"] / tot
            out["contractor"] = rest * n["contractor"] / tot
        else:
            out["unexplained"] = rest
    return {k: round(v, 1) for k, v in out.items()}


def windows(curve, planned, points: list[dict]) -> tuple[list[dict], dict]:
    """points: chronological [{"created_at", "reporter", "state": live state}], first = baseline."""
    out, prev_sv, prev_state = [], 0.0, None
    totals = {"client": 0.0, "neutral": 0.0, "contractor": 0.0, "unexplained": 0.0, "recovered": 0.0}
    for i, p in enumerate(points):
        st = p["state"]
        sp = status_point(curve, planned, st.get("elapsed_pct") or 0, _num(st.get("spi_now")), _num(st.get("cert_now")))
        if sp is None:
            continue
        slip = round(prev_sv - sp["sv_t"], 1)          # positive = the project fell further behind
        ev = _events_between(prev_state, st)
        share = apportion(slip, ev)
        for k, v in share.items():
            totals[k] += v
        if slip < 0:
            totals["recovered"] += -slip
        client = any(EVENT_CLASS[k][0] == "client" for k in ev)
        contractor = any(EVENT_CLASS[k][0] == "contractor" for k in ev)
        out.append({"index": i, "label": "Before monitoring" if i == 0 else f"Update {i}",
                    "to": p.get("created_at"), "reporter": p.get("reporter"),
                    "elapsed_from": round(prev_state["elapsed_pct"], 1) if prev_state else 0.0,
                    "elapsed_to": round(st.get("elapsed_pct") or 0, 1), "sv_t": sp["sv_t"], "slip_days": slip,
                    "events": [{"key": k, "category": EVENT_CLASS[k][0], "label": EVENT_CLASS[k][1], "count": v}
                               for k, v in ev.items() if k in EVENT_CLASS],
                    "apportioned": share, "concurrent": bool(slip > 0 and client and contractor),
                    "point": sp})
        prev_sv, prev_state = sp["sv_t"], st
    return out, {k: round(v, 1) for k, v in totals.items()}


# ------------------------------------------------------------------ main entry
def analyse(project: dict, live_project: dict | None = None, live_states: list[dict] | None = None,
            ml_overrun_pct: float | None = None, today: date | None = None) -> dict:
    """Current delay for a company project (call inside projects.scope(project) so its schedule is used)."""
    today = today or date.today()
    acts = load_schedule()
    base = cpm(acts)
    planned = float(base["finish"])
    curve = planned_curve(acts, base)
    det = project.get("details") or {}
    inputs = project.get("inputs") or {}
    contract_days = float(det.get("planned_months") or inputs.get("planned_months") or 0) * DAYS_PER_MONTH or planned
    ratio = contract_days / planned if planned else 1.0
    start = None
    if project.get("start_date"):
        try:
            start = date.fromisoformat(project["start_date"])
        except ValueError:
            start = None

    def to_date(day):
        return (start + timedelta(days=round(day * ratio))).isoformat() if start is not None else None

    # ---- the status point: activity progress > latest site update > saved assessment
    points = [{"created_at": u.get("created_at"), "reporter": u.get("reporter"), "state": s}
              for u, s in zip((live_project or {}).get("updates", []), live_states or [])]
    prog = project.get("progress")
    last_upd = points[-1] if points else None
    use_progress = bool(prog and prog.get("activities") and
                        (not last_upd or (prog.get("as_of") or "") >= (last_upd["created_at"] or "")[:10]))
    status, status_date, source = None, None, None
    if use_progress:
        e = prog.get("elapsed_pct")
        if e is None and start is not None and prog.get("as_of"):
            e = 100.0 * (date.fromisoformat(prog["as_of"]) - start).days / contract_days
        if e is None and last_upd:
            e = last_upd["state"].get("elapsed_pct")
        if e is not None:
            total = sum(max(a.duration, 0.0) for a in acts) or 1.0
            pct = {a.id: (prog["activities"].get(a.id) if a.id in prog["activities"] else None) for a in acts}
            ev_share = sum(max(a.duration, 0) * (pct[a.id] if pct[a.id] is not None else 0) / 100.0 for a in acts) / total
            # activities not entered are assumed to follow the plan: count their planned share at the status date
            at_tmp = _clamp(e / 100.0, 0, 3) * planned
            ev_share += sum(max(a.duration, 0) * _clamp((at_tmp - base["es"][a.id]) / a.duration)
                            for a in acts if pct[a.id] is None and a.duration > 0) / total
            status = status_point(curve, planned, e, ev_share=ev_share)
            status_date, source = prog.get("as_of"), "Activity progress entered by the planner"
    if status is None and last_upd:
        st = last_upd["state"]
        status = status_point(curve, planned, st.get("elapsed_pct") or 0, _num(st.get("spi_now")), _num(st.get("cert_now")))
        status_date, source = (last_upd["created_at"] or "")[:10], f"Site update by {last_upd.get('reporter') or 'site team'}"
    if status is None and inputs:
        g50 = _num(inputs.get("spi_50")) is not None or _num(inputs.get("cert_50")) is not None
        cp = "50" if g50 else "25"
        status = status_point(curve, planned, float(cp), _num(inputs.get(f"spi_{cp}")), _num(inputs.get(f"cert_{cp}")))
        status_date, source = (project.get("updated_at") or "")[:10], f"Saved assessment at {cp}% of contract time"
    if status is None:
        return {"available": False, "planned_days": round(planned, 1),
                "reason": "No progress reading yet. Enter SPI (or value certified) on the Forecast sheet, "
                          "start the live site link, or enter activity progress below."}

    at, es = status["at"], status["es"]
    act_pct = prog["activities"] if use_progress else None
    upd = schedule_update(acts, base, at, es, act_pct)
    delay_days = round(upd["finish"] - planned, 1)
    rows = activity_rows(acts, base, at, upd["pct"], upd)
    driving = [r for r in rows if r["critical"] and r["late"]]

    # ---- where it is heading, three ways
    spi_t = status["spi_t"]
    finishes = {"to_plan": round(upd["finish"], 1),
                "current_pace": round(planned / spi_t, 1) if spi_t and spi_t > 0.05 else None,
                "ml_forecast": round(planned * (1 + ml_overrun_pct / 100.0), 1) if ml_overrun_pct is not None else None}

    # ---- freshness against the calendar
    cal = None
    if start is not None:
        e_today = 100.0 * (today - start).days / contract_days
        at_today = _clamp(e_today / 100.0, 0, 3) * planned
        es_today = es + (spi_t or 0) * max(0.0, at_today - at)
        lag = round(e_today - status["elapsed_pct"], 1)
        cal = {"today": today.isoformat(), "elapsed_today_pct": round(e_today, 1), "report_lag_pts": lag,
               "stale": lag > 3, "estimated_delay_today_days": round(at_today - min(es_today, planned), 1),
               "planned_finish_date": to_date(planned)}
    stale_days = None
    if status_date:
        try:
            stale_days = (today - date.fromisoformat(status_date[:10])).days
        except ValueError:
            stale_days = None

    # ---- windows (live history)
    wins, totals = windows(curve, planned, points) if points else ([], {})
    excusable = round(totals.get("client", 0) + totals.get("neutral", 0), 1) if totals else 0.0
    cpi = None
    if last_upd and not use_progress:
        cpi = _num(last_upd["state"].get("cpi_now"))
    elif inputs:
        cpi = _num(inputs.get("cpi_50")) or _num(inputs.get("cpi_25"))

    # ---- S-curve for the chart (in % of planned duration and % of work)
    ts, pv = curve
    hist = [w["point"] for w in wins] if wins else [status]
    if use_progress:
        hist = hist + [status]
    band = _band(delay_days, planned)
    notes = []
    if band["name"] != "On programme" and totals.get("client", 0) > 0:
        notes.append(f"{totals['client']:.0f} days of slip fall in windows with client-side events. Check the notice "
                     "period in your contract (FIDIC forms commonly require notice within 28 days of becoming aware) "
                     "and keep the records behind each event.")
    if cal and cal["stale"]:
        notes.append(f"The calendar is {cal['report_lag_pts']:.0f} points of contract time ahead of the last report. "
                     "Send a site update: the true delay today is probably larger.")
    if any(w["concurrent"] for w in wins):
        notes.append("Some windows have client-side and contractor-side events together (concurrent delay). "
                     "Apportionment there is the hardest to defend; review those windows with the planner.")
    return {
        "available": True, "source": source, "status_date": status_date, "days_since_status": stale_days,
        "planned_days": round(planned, 1), "contract_days": round(contract_days, 1), "day_scale": round(ratio, 4),
        "start_date": project.get("start_date"),
        "status": status, "delay_days": delay_days, "delay_band": band,
        "spi_t": spi_t, "cpi": cpi,
        "cost_overrun_to_date_pct": round((1 / cpi - 1) * 100, 1) if cpi else None,
        "finish": finishes,
        "finish_dates": {k: to_date(v) if v is not None else None for k, v in finishes.items()},
        "planned_finish_date": to_date(planned),
        "activities": rows, "driving": [r["id"] for r in driving],
        "critical_path_now": [a.id for a in acts if a.id in upd["active"] and a.id in upd["cpm"]["critical"]],
        "windows": wins, "apportionment": totals, "excusable_days_indicative": excusable,
        "category_labels": CATEGORY_LABEL,
        "calendar": cal, "notes": notes,
        "curve": {"t_pct": [round(100 * t / planned, 2) for t in ts], "pv_pct": [round(100 * v, 2) for v in pv]},
        "history": [{"at_pct": round(100 * h["at"] / planned, 2), "ev_pct": round(100 * h["ev"], 2),
                     "es_pct": round(100 * h["es"] / planned, 2), "basis": h["basis"]} for h in hist],
        "schedule_activities": len(acts),
        "method": "Earned Schedule (Lipke 2003) on the duration-weighted baseline, retained-logic CPM update from the "
                  "status date, and contemporaneous windows over the site updates. Indicative, not a forensic analysis.",
    }
