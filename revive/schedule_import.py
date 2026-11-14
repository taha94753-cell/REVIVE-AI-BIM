"""
Baseline schedule import. REVIVE runs on the baseline schedule and site reports alone;
this module lets a planner bring the schedule straight from Primavera P6.

Supported
  * .csv  in the bim/schedule.csv column layout (crash data and BIM links included)
  * .xer  Primavera P6 export: TASK, TASKPRED and PROJWBS tables are read
          - durations: target_drtn_hr_cnt / schedule.hours_per_day
          - level-of-effort and WBS-summary activities are skipped
          - SS / FF / SF links are treated as finish-to-start and lags are ignored;
            both are counted in the import report so the simplification is visible
          - crash limits and crash costs are not in P6: defaults from config.yaml are
            applied and flagged for calibration
          - weather sensitivity is guessed from activity names (editable in the CSV)
  * .xml  MS Project (File > Save As > XML, the MSPDI format), ported from the REVIVE web app:
          - durations from <Duration> (PT40H0M0S) / MinutesPerDay; summary, blank and inactive rows skipped
          - finished activities keep their duration (the baseline is the plan, not the remaining work)
          - links: same simplification as P6 (non-FS as FS, lags ignored, both counted in the report);
            links to summary rows are dropped and counted
          - parsed with defusedxml, so an uploaded file cannot expand entities or reach the network
Cost, resources and progress (read_loading)
  The same files often carry more than logic. When present, these are read too:
  * .xer  TASKRSRC and PROJCOST (budget and actual cost, resource units), RSRC (names, types),
          TASK status (% complete, actual dates, remaining duration), PROJECT (data date)
  * .xml  Task Cost / ActualCost / PercentComplete / actual dates, Resources and Assignments,
          StatusDate. MS Project stores money x100 in this format, so costs are divided by 100.
  * .csv  optional columns budget_cost_pkr, actual_cost_pkr, pct_complete, resources ("Mason:120;Crane:16")
  Nothing is invented: a file with no cost loading yields no CPI, and the analysis says so.
The imported schedule is written as a CSV next to the upload so it can be reviewed
and edited, and every element in an IFC model can link to it by WBS_Code = activity id.
"""
from __future__ import annotations

import re
from pathlib import Path

from defusedxml import ElementTree as SafeET

from .config import load_config
from .scheduling import Activity, cpm, load_schedule, validate, write_schedule_csv

WEATHER_WORDS = ("excavat", "earth", "fill", "concrete", "slab", "pour", "footing", "foundation", "roof",
                 "asphalt", "paving", "pavement", "masonry", "brick", "external", "landscap", "waterproof",
                 "compaction", "subgrade", "base course", "culvert", "pile", "erection", "crane")


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _read_text(p: Path) -> str:
    raw = p.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_xer(text: str) -> tuple[list[Activity], dict]:
    acts, report, _ = _xer_full(text)
    return acts, report


def _day(v) -> str | None:
    """'2024-03-01 08:00' or '2024-03-01T08:00:00' -> '2024-03-01' (None when blank or not a date)."""
    v = (v or "").strip()[:10]
    return v if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else None


def _xer_pct(t: dict, rs: list[dict]) -> float | None:
    status = t.get("status_code") or ""
    if status == "TK_Complete":
        return 100.0
    if status == "TK_NotStart":
        return 0.0
    kind = t.get("complete_pct_type") or ""
    if kind == "CP_Phys" and t.get("phys_complete_pct") not in (None, ""):
        return max(0.0, min(100.0, _f(t.get("phys_complete_pct"))))
    if kind == "CP_Units":
        done = sum(_f(r.get("act_reg_qty")) + _f(r.get("act_ot_qty")) for r in rs)
        left = sum(_f(r.get("remain_qty")) for r in rs)
        if done + left > 0:
            return round(100.0 * done / (done + left), 1)
    target, remain = _f(t.get("target_drtn_hr_cnt")), _f(t.get("remain_drtn_hr_cnt"))
    if status == "TK_Active" and target > 0:
        return round(max(0.0, min(100.0, 100.0 * (target - remain) / target)), 1)
    return None


def _xer_full(text: str) -> tuple[list[Activity], dict, dict]:
    tables: dict[str, list[dict]] = {}
    cur, fields = None, None
    for line in text.splitlines():
        parts = line.rstrip("\r\n").split("\t")
        tag = parts[0].strip() if parts else ""
        if tag == "%T":
            cur, fields = parts[1].strip(), None
            tables.setdefault(cur, [])
        elif tag == "%F":
            fields = [x.strip() for x in parts[1:]]
        elif tag == "%R" and cur and fields:
            tables[cur].append(dict(zip(fields, parts[1:])))
    tasks = tables.get("TASK", [])
    if not tasks:
        raise ValueError("No TASK table found. Export the schedule from Primavera P6 as an .xer file.")
    cfg = load_config()
    hpd = float(cfg["schedule"]["hours_per_day"])
    cost = float(cfg["schedule"]["default_crash_cost_per_day_pkr"])
    frac = float(cfg["optimizer"]["default_crash_fraction"])
    wbs = {w.get("wbs_id"): (w.get("wbs_name") or w.get("wbs_short_name") or "").strip()
           for w in tables.get("PROJWBS", [])}
    by_tid, acts, seen, skipped = {}, [], set(), 0
    for t in tasks:
        if (t.get("task_type") or "") in ("TT_LOE", "TT_WBS"):
            skipped += 1
            continue
        code = (t.get("task_code") or t.get("task_id") or "").strip()
        if code in seen:
            code = f"{code}-{t.get('task_id')}"
        seen.add(code)
        hours = _f(t.get("target_drtn_hr_cnt")) or _f(t.get("remain_drtn_hr_cnt"))
        dur = round(hours / hpd, 2)
        name = (t.get("task_name") or code).strip()
        a = Activity(id=code, name=name, wbs=code, duration=dur, preds=[],
                     crash_max_days=round(dur * frac, 2), crash_cost_per_day=cost if dur > 0 else 0.0,
                     crash_method="Acceleration (calibrate cost with the planner)",
                     trade=wbs.get(t.get("wbs_id"), ""), ifc_storey="", ifc_types=[],
                     weather_sensitive=any(w in name.lower() for w in WEATHER_WORDS))
        by_tid[t.get("task_id")] = a
        acts.append(a)
    # ---- cost, resources and progress carried by the same file
    rsrc = {r.get("rsrc_id"): r for r in tables.get("RSRC", [])}
    by_task: dict[str, list[dict]] = {}
    for r in tables.get("TASKRSRC", []):
        by_task.setdefault(r.get("task_id"), []).append(r)
    expenses: dict[str, list[dict]] = {}
    for r in tables.get("PROJCOST", []):
        expenses.setdefault(r.get("task_id"), []).append(r)
    kinds = {"RT_Labor": "labour", "RT_Equip": "equipment", "RT_Mat": "material"}
    load = {}
    for t in tasks:
        a = by_tid.get(t.get("task_id"))
        if a is None:
            continue
        rs, ex = by_task.get(t.get("task_id"), []), expenses.get(t.get("task_id"), [])
        res = []
        for r in rs:
            info = rsrc.get(r.get("rsrc_id"), {})
            res.append({"name": (info.get("rsrc_name") or info.get("rsrc_short_name") or "Unnamed resource").strip()[:60],
                        "type": kinds.get(info.get("rsrc_type") or "", "other"),
                        "units": round(_f(r.get("target_qty")), 2), "cost": round(_f(r.get("target_cost")), 2)})
        load[a.id] = {
            "budget": round(sum(_f(r.get("target_cost")) for r in rs) + sum(_f(e.get("target_cost")) for e in ex), 2),
            "actual_cost": round(sum(_f(r.get("act_reg_cost")) + _f(r.get("act_ot_cost")) for r in rs)
                                 + sum(_f(e.get("act_cost")) for e in ex), 2),
            "pct": _xer_pct(t, rs), "actual_start": _day(t.get("act_start_date")),
            "actual_finish": _day(t.get("act_end_date")),
            "remaining": round(_f(t.get("remain_drtn_hr_cnt")) / hpd, 2), "resources": res}
    proj = (tables.get("PROJECT") or [{}])[0]
    starts = [d for d in (_day(t.get("target_start_date")) for t in tasks) if d]
    ends = [d for d in (_day(t.get("target_end_date")) for t in tasks) if d]
    loading = {"data_date": _day(proj.get("last_recalc_date")),
               "start": _day(proj.get("plan_start_date")) or (min(starts) if starts else None),
               "finish": max(ends) if ends else None, "activities": load}
    non_fs = lags = dropped = links = 0
    for r in tables.get("TASKPRED", []):
        succ, pred = by_tid.get(r.get("task_id")), by_tid.get(r.get("pred_task_id"))
        if not succ or not pred or succ is pred:
            dropped += 1
            continue
        if pred.id not in succ.preds:
            succ.preds.append(pred.id)
            links += 1
        non_fs += (r.get("pred_type") or "PR_FS") != "PR_FS"
        lags += _f(r.get("lag_hr_cnt")) != 0
    validate(acts)
    report = {"format": "Primavera P6 XER", "activities": len(acts), "links": links,
              "skipped_level_of_effort_or_wbs": skipped, "links_dropped": dropped,
              "non_finish_to_start_treated_as_fs": int(non_fs), "lags_ignored": int(lags),
              "weather_sensitive_guessed": sum(a.weather_sensitive for a in acts),
              "planned_days": round(cpm(acts)["finish"], 1) if acts else 0,
              "warnings": ["Crash limits and crash costs are defaults from config.yaml: calibrate them with the planner."]}
    if non_fs or lags:
        report["warnings"].append(f"{int(non_fs)} non-FS links were treated as FS and {int(lags)} lags were ignored.")
    return acts, report, loading


_MSPDI_DURATION = re.compile(
    r"^-?P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?$")
MSPDI_LINK_TYPES = {"0": "FF", "1": "FS", "2": "SF", "3": "SS"}


def mspdi_days(value: str | None, minutes_per_day: float = 480) -> float:
    """MS Project duration ("PT40H0M0S"; a day part is read as working days) in working days."""
    m = _MSPDI_DURATION.match((value or "").strip())
    if not m:
        return 0.0
    d, h, mi, s = (float(x or 0) for x in m.groups())
    return round(d + (h * 60 + mi + s / 60) / minutes_per_day, 3)


def parse_mspdi(text: str) -> tuple[list[Activity], dict]:
    acts, report, _ = _mspdi_full(text)
    return acts, report


def _mspdi_hours(value: str | None) -> float:
    m = _MSPDI_DURATION.match((value or "").strip())
    if not m:
        return 0.0
    d, h, mi, s = (float(x or 0) for x in m.groups())
    return round(d * 8 + h + mi / 60 + s / 3600, 2)


def _mspdi_full(text: str) -> tuple[list[Activity], dict, dict]:
    try:
        root = SafeET.fromstring(text.encode("utf-8"))
    except Exception as exc:  # malformed XML or a blocked construct (entities, DTDs)
        raise ValueError(f"Could not read the MS Project XML file: {exc}") from exc
    ns = root.tag[:root.tag.index("}") + 1] if root.tag.startswith("{") else ""
    if root.tag != f"{ns}Project":
        raise ValueError("Not an MS Project XML file: no <Project> element. In MS Project use File > Save As > XML.")
    get = lambda el, tag: (el.findtext(f"{ns}{tag}") or "").strip()
    flag = lambda el, tag: get(el, tag) in ("1", "true")
    mpd = _f(get(root, "MinutesPerDay")) or 480.0
    cfg = load_config()
    cost = float(cfg["schedule"]["default_crash_cost_per_day_pkr"])
    frac = float(cfg["optimizer"]["default_crash_fraction"])
    tasks = root.findall(f"{ns}Tasks/{ns}Task")
    if not tasks:
        raise ValueError("The MS Project file has no tasks.")
    by_uid, acts, summary, skipped, seen = {}, [], set(), 0, set()
    for t in tasks:
        uid = get(t, "UID")
        if not uid or uid == "0" or flag(t, "IsNull"):
            continue
        if flag(t, "Summary"):
            summary.add(uid)
            continue
        if get(t, "Active") == "0":
            skipped += 1
            continue
        dur = mspdi_days(get(t, "Duration"), mpd)
        code = get(t, "ID") or uid
        if code in seen:
            code = f"{code}-{uid}"
        seen.add(code)
        name = get(t, "Name") or f"Task {code}"
        a = Activity(id=code, name=name, wbs=get(t, "WBS") or get(t, "OutlineNumber") or code, duration=dur,
                     preds=[], crash_max_days=round(dur * frac, 2), crash_cost_per_day=cost if dur > 0 else 0.0,
                     crash_method="Acceleration (calibrate cost with the planner)", trade="", ifc_storey="",
                     ifc_types=[], weather_sensitive=any(w in name.lower() for w in WEATHER_WORDS))
        by_uid[uid] = a
        acts.append(a)
    if not acts:
        raise ValueError("The MS Project file has only summary rows; no activities to schedule.")
    # ---- cost, resources and progress carried by the same file (money is stored x100 in MSPDI)
    money = lambda el, tag: round(_f(get(el, tag)) / 100.0, 2)
    names = {get(r, "UID"): (get(r, "Name") or "Unnamed resource", {"0": "material", "1": "labour", "2": "cost"}.get(get(r, "Type"), "other"))
             for r in root.findall(f"{ns}Resources/{ns}Resource")}
    assigned: dict[str, list[dict]] = {}
    for asg in root.findall(f"{ns}Assignments/{ns}Assignment"):
        nm, kind = names.get(get(asg, "ResourceUID"), ("", "other"))
        if not nm or get(asg, "ResourceUID").startswith("-"):
            continue
        assigned.setdefault(get(asg, "TaskUID"), []).append(
            {"name": nm[:60], "type": kind, "units": _mspdi_hours(get(asg, "Work")), "cost": money(asg, "Cost")})
    load = {}
    for t in tasks:
        a = by_uid.get(get(t, "UID"))
        if a is None:
            continue
        pct = get(t, "PercentComplete")
        load[a.id] = {"budget": money(t, "Cost"), "actual_cost": money(t, "ActualCost"),
                      "pct": max(0.0, min(100.0, _f(pct))) if pct != "" else None,
                      "actual_start": _day(get(t, "ActualStart")), "actual_finish": _day(get(t, "ActualFinish")),
                      "remaining": mspdi_days(get(t, "RemainingDuration"), mpd) if get(t, "RemainingDuration") else None,
                      "resources": assigned.get(get(t, "UID"), [])}
    starts = [d for d in (_day(get(t, "Start")) for t in tasks if get(t, "UID") in by_uid) if d]
    ends = [d for d in (_day(get(t, "Finish")) for t in tasks if get(t, "UID") in by_uid) if d]
    loading = {"data_date": _day(get(root, "StatusDate")), "start": _day(get(root, "StartDate")) or (min(starts) if starts else None),
               "finish": max(ends) if ends else None, "activities": load}
    links = non_fs = lags = summary_links = 0
    for t in tasks:
        succ = by_uid.get(get(t, "UID"))
        for link in t.findall(f"{ns}PredecessorLink"):
            pid = get(link, "PredecessorUID")
            pred = by_uid.get(pid)
            if not succ or not pred or succ is pred:
                summary_links += pid in summary or get(t, "UID") in summary
                continue
            if pred.id not in succ.preds:
                succ.preds.append(pred.id)
                links += 1
            non_fs += MSPDI_LINK_TYPES.get(get(link, "Type") or "1", "FS") != "FS"
            lags += _f(get(link, "LinkLag")) != 0
    validate(acts)
    report = {"format": "MS Project XML", "project": get(root, "Title") or get(root, "Name") or "Untitled",
              "activities": len(acts), "links": links, "skipped_summary": len(summary),
              "skipped_inactive": skipped, "links_to_summary_dropped": int(summary_links),
              "non_finish_to_start_treated_as_fs": int(non_fs), "lags_ignored": int(lags),
              "weather_sensitive_guessed": sum(a.weather_sensitive for a in acts),
              "planned_days": round(cpm(acts)["finish"], 1),
              "warnings": ["Crash limits and crash costs are defaults from config.yaml: calibrate them with the planner."]}
    if non_fs or lags:
        report["warnings"].append(f"{int(non_fs)} non-FS links were treated as FS and {int(lags)} lags were ignored.")
    if summary_links:
        report["warnings"].append(f"{int(summary_links)} links to or from summary tasks were dropped; "
                                  "link the activities underneath instead.")
    return acts, report, loading


def import_schedule(upload: Path) -> tuple[Path, dict]:
    """Validate an uploaded schedule; returns the CSV the app should use and a report."""
    upload = Path(upload)
    if upload.suffix.lower() in (".xer", ".xml"):
        parse = parse_xer if upload.suffix.lower() == ".xer" else parse_mspdi
        acts, report = parse(_read_text(upload))
        dest = write_schedule_csv(acts, upload.with_suffix(".csv"))
        load_schedule(dest)
        return dest, report
    acts = load_schedule(upload)
    return upload, {"format": "CSV", "activities": len(acts), "links": sum(len(a.preds) for a in acts),
                    "planned_days": round(cpm(acts)["finish"], 1), "warnings": []}


def _csv_loading(upload: Path) -> dict:
    """Optional columns of the REVIVE CSV layout: budget_cost_pkr, actual_cost_pkr, pct_complete, resources."""
    import csv
    load = {}
    with open(upload, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            res = []
            for part in (row.get("resources") or "").split(";"):
                name, _, units = part.partition(":")
                if name.strip():
                    res.append({"name": name.strip()[:60], "type": "labour", "units": round(_f(units), 2), "cost": 0.0})
            pct = (row.get("pct_complete") or "").strip()
            load[(row.get("id") or "").strip()] = {
                "budget": round(_f(row.get("budget_cost_pkr")), 2), "actual_cost": round(_f(row.get("actual_cost_pkr")), 2),
                "pct": max(0.0, min(100.0, _f(pct))) if pct else None, "actual_start": None, "actual_finish": None,
                "remaining": None, "resources": res}
    return {"data_date": None, "start": None, "finish": None, "activities": load}


def read_loading(upload: Path) -> tuple[list[Activity], dict]:
    """Activities plus whatever cost, resource and progress data the file carries (see the module note)."""
    upload = Path(upload)
    ext = upload.suffix.lower()
    if ext == ".xer":
        acts, _, loading = _xer_full(_read_text(upload))
    elif ext == ".xml":
        acts, _, loading = _mspdi_full(_read_text(upload))
    else:
        acts, loading = load_schedule(upload), _csv_loading(upload)
    return acts, loading
