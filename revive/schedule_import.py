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
The imported schedule is written as a CSV next to the upload so it can be reviewed
and edited, and every element in an IFC model can link to it by WBS_Code = activity id.
"""
from __future__ import annotations

from pathlib import Path

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


def import_schedule(upload: Path) -> tuple[Path, dict]:
    """Validate an uploaded schedule; returns the CSV the app should use and a report."""
    upload = Path(upload)
    if upload.suffix.lower() == ".xer":
        acts, report = parse_xer(_read_text(upload))
        dest = write_schedule_csv(acts, upload.with_suffix(".csv"))
        load_schedule(dest)
        return dest, report
    acts = load_schedule(upload)
    return upload, {"format": "CSV", "activities": len(acts), "links": sum(len(a.preds) for a in acts),
                    "planned_days": round(cpm(acts)["finish"], 1), "warnings": []}
