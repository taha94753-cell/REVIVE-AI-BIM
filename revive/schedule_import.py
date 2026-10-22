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
    return acts, report


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
    return acts, report


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
