"""
Company projects. A company can run any number of projects; each one owns
  * its details (client, location, contract start, duration, type, value band),
  * its latest assessment inputs (what the Forecast sheet scores),
  * its own baseline schedule and optional IFC model (files under data/workspaces/c<id>/p<id>/),
  * optional activity progress at a status date (feeds the current delay analysis),
  * at most one live monitor (live.py) with an unguessable site-link token.

Every function takes company_id and filters on it, so one company can never read or change
another company's project, even by guessing an id.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import date, datetime
from pathlib import Path

from .config import use_scope, workspace_dir
from .db import add_columns, connect
from .schema import FIELD_BY_KEY, FIELDS, match_option

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER NOT NULL,
  name TEXT NOT NULL, code TEXT, client TEXT, location TEXT, start_date TEXT, details TEXT,
  inputs TEXT, gate TEXT, schedule_file TEXT, ifc_mode TEXT NOT NULL DEFAULT 'demo', ifc_file TEXT,
  progress TEXT, created_by INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_projects_company ON projects(company_id);
"""
DETAIL_KEYS = ("project_type", "province", "contract_value", "contract_type", "client_sector", "planned_months",
               "floor_area_m2", "storeys", "length_km", "description")
TEXT_MAX = 160


def _conn():
    c = connect(SCHEMA)
    add_columns(c, "projects", {"progress": "TEXT"})
    return c


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _txt(v, n: int = TEXT_MAX) -> str | None:
    if v is None:
        return None
    s = re.sub(r"[\x00-\x1f\x7f]", " ", str(v)).strip()
    return s[:n] or None


def clean_inputs(inputs: dict | None) -> dict:
    """Keep only model fields, with values of the right kind. Unknown keys are dropped."""
    out = {}
    for f in FIELDS:
        v = (inputs or {}).get(f["key"])
        if v is None or v == "":
            out[f["key"]] = None
        elif f["kind"] == "number":
            try:
                x = float(v)
                lo, hi = f.get("min"), f.get("max")
                out[f["key"]] = None if x != x else max(lo, min(hi, x)) if lo is not None and hi is not None else x
            except (TypeError, ValueError):
                out[f["key"]] = None
        else:
            out[f["key"]] = match_option(f, v)
    return out


def clean_details(d: dict | None) -> dict:
    d = d or {}
    out = {}
    for k in DETAIL_KEYS:
        v = d.get(k)
        if v in (None, ""):
            continue
        if k in FIELD_BY_KEY and FIELD_BY_KEY[k]["kind"] != "number":
            v = match_option(FIELD_BY_KEY[k], v)
        elif k in FIELD_BY_KEY:
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
        else:
            v = _txt(v, 600)
        if v is not None:
            out[k] = v
    return out


def clean_location(loc: dict | None) -> dict | None:
    if not loc:
        return None
    try:
        lat, lon = float(loc.get("lat")), float(loc.get("lon"))
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {"name": _txt(loc.get("name"), 60) or "Site", "lat": round(lat, 4), "lon": round(lon, 4)}


def clean_date(s) -> str | None:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10]).isoformat()
    except ValueError:
        return None


def _row(r) -> dict:
    d = dict(r)
    for k in ("location", "details", "inputs", "progress"):
        d[k] = json.loads(d[k]) if d.get(k) else None
    d["details"] = d["details"] or {}
    return d


# ------------------------------------------------------------------ CRUD
def create(company_id: int, user_id: int | None, name: str, *, code=None, client=None, location=None,
           start_date=None, details=None, inputs=None, gate=None) -> dict:
    name = _txt(name, 120)
    if not name:
        raise ValueError("Give the project a name.")
    det = clean_details(details)
    # details are not an assessment: inputs are stored only when the caller scored real answers
    ins = clean_inputs({**{k: v for k, v in det.items() if k in FIELD_BY_KEY}, **inputs}) if inputs else None
    now = _now()
    with _conn() as c:
        pid = c.execute("INSERT INTO projects (company_id, name, code, client, location, start_date, details, inputs, gate,"
                        " ifc_mode, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (int(company_id), name, _txt(code, 40), _txt(client), json.dumps(clean_location(location)),
                         clean_date(start_date), json.dumps(det), json.dumps(ins) if ins else None,
                         gate if gate in ("G25", "G50") else None, "demo", user_id, now, now)).lastrowid
    return get(company_id, pid)


def get(company_id: int, pid: int) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM projects WHERE id = ? AND company_id = ?", (int(pid), int(company_id))).fetchone()
    return _row(r) if r else None


def list_for(company_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM projects WHERE company_id = ? ORDER BY updated_at DESC, id DESC",
                         (int(company_id),)).fetchall()
    return [_row(r) for r in rows]


def update(company_id: int, pid: int, **fields) -> dict | None:
    p = get(company_id, pid)
    if not p:
        return None
    sets, vals = [], []
    if "name" in fields and fields["name"] is not None:
        n = _txt(fields["name"], 120)
        if not n:
            raise ValueError("Give the project a name.")
        sets.append("name = ?"); vals.append(n)
    for k in ("code", "client"):
        if k in fields and fields[k] is not None:
            sets.append(f"{k} = ?"); vals.append(_txt(fields[k], 40 if k == "code" else TEXT_MAX))
    if fields.get("location") is not None:
        sets.append("location = ?"); vals.append(json.dumps(clean_location(fields["location"])))
    if "start_date" in fields and fields["start_date"] is not None:
        sets.append("start_date = ?"); vals.append(clean_date(fields["start_date"]))
    if fields.get("details") is not None:
        sets.append("details = ?"); vals.append(json.dumps({**p["details"], **clean_details(fields["details"])}))
    if fields.get("inputs") is not None:
        sets.append("inputs = ?"); vals.append(json.dumps(clean_inputs(fields["inputs"])))
    if fields.get("gate") in ("G25", "G50"):
        sets.append("gate = ?"); vals.append(fields["gate"])
    if "progress" in fields:
        sets.append("progress = ?"); vals.append(json.dumps(fields["progress"]) if fields["progress"] else None)
    for k in ("schedule_file", "ifc_mode", "ifc_file"):
        if k in fields:
            sets.append(f"{k} = ?"); vals.append(fields[k])
    if not sets:
        return p
    sets.append("updated_at = ?"); vals.append(_now())
    with _conn() as c:
        # nosec B608: `sets` holds only column names written in this function; every value is a bound parameter
        c.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id = ? AND company_id = ?",  # nosec B608
                  (*vals, int(pid), int(company_id)))
    return get(company_id, pid)


def touch(company_id: int, pid: int) -> None:
    with _conn() as c:
        c.execute("UPDATE projects SET updated_at = ? WHERE id = ? AND company_id = ?", (_now(), int(pid), int(company_id)))


def delete(company_id: int, pid: int) -> bool:
    if not get(company_id, pid):
        return False
    from . import live, store
    live.delete_for_project(company_id, pid)
    store.delete_for_project(company_id, pid)
    with _conn() as c:
        c.execute("DELETE FROM projects WHERE id = ? AND company_id = ?", (int(pid), int(company_id)))
    shutil.rmtree(workspace_dir(company_id, pid), ignore_errors=True)
    return True


# ------------------------------------------------------------------ files and scope
def files(p: dict | None) -> dict | None:
    """The scope dict config.use_scope() expects."""
    if not p:
        return None
    return {"schedule": p.get("schedule_file"), "ifc_mode": p.get("ifc_mode") or "demo", "ifc": p.get("ifc_file")}


def scope(p: dict | None):
    return use_scope(files(p))


def store_upload(company_id: int, pid: int, kind: str, src: Path, original_name: str) -> Path:
    """Move an upload into the project's own folder under a fixed name (no user-chosen paths)."""
    ext = Path(original_name).suffix.lower()
    dest = workspace_dir(company_id, pid) / (f"model{ext}" if kind == "ifc" else f"schedule_upload{ext}")
    shutil.move(str(src), dest)
    return dest


# ------------------------------------------------------------------ activity progress
def clean_progress(acts_ids: set[str], body: dict) -> dict | None:
    """{"as_of": "YYYY-MM-DD", "elapsed_pct": 0-100, "activities": {id: 0-100}} -> validated, or None to clear."""
    raw = (body or {}).get("activities") or {}
    pct = {}
    for k, v in list(raw.items())[:2000]:
        k = str(k)[:40]
        if k not in acts_ids:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if x == x:
            pct[k] = max(0.0, min(100.0, x))
    if not pct:
        return None
    try:
        e = float(body.get("elapsed_pct"))
        e = max(0.0, min(100.0, e)) if e == e else None
    except (TypeError, ValueError):
        e = None
    return {"as_of": clean_date(body.get("as_of")) or date.today().isoformat(), "elapsed_pct": e, "activities": pct}
