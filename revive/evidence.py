"""
Extension-of-time evidence pack and the early-warning record (ported from the REVIVE web app's EOT pack
and Replay sheet).

The pack gathers, for one project, what a planner attaches to a notice or an extension-of-time claim:
  * the delay to date and where the finish is heading (from delay.analyse, which uses no machine learning),
  * every site update as a dated, attributed record with the events reported in it,
  * the slip in each window between updates, apportioned to client-side, neutral (weather) and
    contractor-side events, with concurrent windows flagged,
  * the forecast history and the first time REVIVE warned (forecast band At risk or Critical): how long
    before the contract completion date the warning came,
  * the drivers of the latest forecast with an owner and an action each.
It is an evidence summary to support a notice, NOT a forensic delay analysis (SCL Protocol / AACE 29R-03).
Records marked as sample data stay marked.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from .delay import CATEGORY_LABEL, EVENT_CLASS
from .scheduling import DAYS_PER_MONTH

WARNING_BANDS = ("At risk", "Critical")
NOTICE_DAYS = 28            # FIDIC 1999/2017 Sub-Clause 20.1 / 20.2: notice within 28 days of becoming aware


def _d(s: str | None) -> date | None:
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def forecast_history(project: dict, assessment: dict | None, live_project: dict | None) -> list[dict]:
    """Chronological forecasts: the saved assessment (if any), then each live site update."""
    out = []
    if assessment and assessment.get("result"):
        r = assessment["result"]
        gate_pct = 50.0 if r.get("gate") == "G50" else 25.0
        out.append({"at": assessment.get("created_at"), "source": "Saved assessment", "elapsed_pct": gate_pct,
                    "time_overrun_pct": r.get("time_overrun_pct"), "band": (r.get("band") or {}).get("name"),
                    "probability": r.get("high_risk_probability"), "reporter": None})
    for u in (live_project or {}).get("updates", []):
        s = u.get("summary") or {}
        out.append({"at": u.get("created_at"), "source": "Site update", "elapsed_pct": s.get("elapsed_pct"),
                    "time_overrun_pct": s.get("time_overrun_pct"), "band": (s.get("band") or {}).get("name"),
                    "probability": s.get("probability"), "reporter": u.get("reporter"),
                    "drivers": s.get("drivers") or []})
    return [h for h in out if h.get("time_overrun_pct") is not None]


def early_warning(history: list[dict], contract_days: float, start: date | None) -> dict:
    """When the forecast first reached At risk or Critical, and how much contract time was left then."""
    first = next((h for h in history if h.get("band") in WARNING_BANDS), None)
    if not first:
        return {"warned": False, "text": "The forecast has not reached At risk or Critical."}
    e = float(first.get("elapsed_pct") or 0)
    left_days = round(max(0.0, (100.0 - e) / 100.0 * contract_days))
    on = (start + timedelta(days=round(e / 100.0 * contract_days))) if start else _d(first.get("at"))
    weeks = left_days / 7
    return {"warned": True, "band": first["band"], "elapsed_pct": round(e, 1), "date": on.isoformat() if on else None,
            "forecast_overrun_pct": first["time_overrun_pct"], "days_before_completion": left_days,
            "text": (f"REVIVE first warned ({first['band']}, forecast overrun {first['time_overrun_pct']:+.0f}%) at "
                     f"{e:.0f}% of contract time, {left_days} days (about {weeks:.0f} weeks) before the contract "
                     "completion date.")}


def site_records(live_project: dict | None) -> list[dict]:
    """Every site update as a dated, attributed record: what the site reported, in its own words."""
    rows = []
    for i, u in enumerate((live_project or {}).get("updates", [])):
        s = u.get("summary") or {}
        ch = u.get("changes")
        rows.append({"no": i, "at": u.get("created_at"), "reporter": u.get("reporter") or "Site team",
                     "note": u.get("note") or "", "reported": ch if isinstance(ch, list) else [],
                     "elapsed_pct": s.get("elapsed_pct"), "spi": s.get("spi"), "cpi": s.get("cpi"),
                     "forecast_overrun_pct": s.get("time_overrun_pct"), "band": (s.get("band") or {}).get("name")})
    return rows


def build_pack(*, company: str, prepared_by: str, project: dict, delay_result: dict, live_project: dict | None,
               assessment: dict | None, prediction: dict | None, today: date | None = None) -> dict:
    today = today or date.today()
    det = project.get("details") or {}
    start = _d(project.get("start_date"))
    contract_days = float(delay_result.get("contract_days") or (float(det.get("planned_months") or 0) * DAYS_PER_MONTH)
                          or delay_result.get("planned_days") or 0)
    hist = forecast_history(project, assessment, live_project)
    warn = early_warning(hist, contract_days, start)
    available = bool(delay_result.get("available"))
    totals = delay_result.get("apportionment") or {}
    wins = delay_result.get("windows") or []
    notice = None
    if available and totals.get("client", 0) > 0:
        first_client = next((w for w in wins if w.get("apportioned", {}).get("client", 0) > 0), None)
        aware = _d((first_client or {}).get("to"))
        if aware:
            due = aware + timedelta(days=NOTICE_DAYS)
            notice = {"aware": aware.isoformat(), "due": due.isoformat(), "days_left": (due - today).days,
                      "text": f"Client-side events first caused slip in the window ending {aware.isoformat()}. "
                              f"Under FIDIC-style contracts a notice is due within {NOTICE_DAYS} days of becoming "
                              f"aware: by {due.isoformat()}."}
    sample = "sample" in (project.get("client") or "").lower() or str(project.get("name", "")).lower().startswith("sample")
    actions = (prediction or {}).get("actions") or []
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prepared_by": prepared_by, "company": company, "sample": sample,
        "project": {k: project.get(k) for k in ("id", "name", "code", "client", "start_date")}
                   | {"location": (project.get("location") or {}).get("name"),
                      "project_type": det.get("project_type"), "province": det.get("province"),
                      "planned_months": det.get("planned_months")},
        "delay": {k: delay_result.get(k) for k in ("available", "reason", "source", "status_date", "delay_days",
                                                   "delay_band", "spi_t", "planned_finish_date", "finish",
                                                   "finish_dates", "contract_days", "excusable_days_indicative",
                                                   "notes", "method")},
        "windows": [{k: w.get(k) for k in ("label", "to", "reporter", "elapsed_from", "elapsed_to", "slip_days",
                                           "events", "apportioned", "concurrent")} for w in wins],
        "apportionment": totals, "category_labels": CATEGORY_LABEL,
        "critical_activities_behind": [r for r in (delay_result.get("activities") or []) if r.get("critical") and r.get("late")][:8],
        "site_records": site_records(live_project),
        "forecast_history": hist, "early_warning": warn, "notice": notice,
        "forecast": {"time_overrun_pct": (prediction or {}).get("time_overrun_pct"),
                     "band": ((prediction or {}).get("band") or {}).get("name"),
                     "interval": (prediction or {}).get("time_interval_pct"),
                     "probability": (prediction or {}).get("high_risk_probability")} if prediction else None,
        "actions": actions,
        "disclaimer": "Evidence summary to support a notice or an extension-of-time claim. The slip apportionment is "
                      "indicative (events reported in each window), not a forensic delay analysis under the SCL "
                      "Protocol or AACE 29R-03; a planner must verify it against the programme and the records. "
                      "Forecasts come from a model trained on 81 completed projects and carry the error shown.",
    }
