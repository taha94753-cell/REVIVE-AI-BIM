"""Saved assessments (SQLite, file data/app.db) so a project can be tracked update by update."""
from __future__ import annotations

import json
from datetime import datetime

from .db import add_columns, connect

SCHEMA = """CREATE TABLE IF NOT EXISTS assessments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, name TEXT NOT NULL,
  gate TEXT, band TEXT, time_overrun_pct REAL, health REAL,
  inputs TEXT NOT NULL, result TEXT NOT NULL, recovery TEXT)"""


def _conn():
    c = connect(SCHEMA)
    add_columns(c, "assessments", {"company_id": "INTEGER", "project_id": "INTEGER"})
    return c


def save(name: str, inputs: dict, result: dict, recovery: dict | None = None,
         company_id: int | None = None, project_id: int | None = None) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO assessments (created_at, name, gate, band, time_overrun_pct, health, inputs, result, recovery,"
            " company_id, project_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), (name or "").strip()[:120] or "Untitled project", result.get("gate"),
             (result.get("band") or {}).get("name"), result.get("time_overrun_pct"),
             (result.get("health") or {}).get("score"), json.dumps(inputs), json.dumps(result),
             json.dumps(recovery) if recovery else None, company_id, project_id))
        return int(cur.lastrowid)


def list_all(company_id: int, project_id: int | None = None) -> list[dict]:
    q = "SELECT id, created_at, name, gate, band, time_overrun_pct, health, project_id FROM assessments WHERE company_id = ?"
    args: list = [int(company_id)]
    if project_id is not None:
        q += " AND project_id = ?"
        args.append(int(project_id))
    with _conn() as c:
        rows = c.execute(q + " ORDER BY id DESC LIMIT 500", args).fetchall()
    return [dict(r) for r in rows]


def latest_for_project(company_id: int, project_id: int) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT id FROM assessments WHERE company_id = ? AND project_id = ? ORDER BY id DESC LIMIT 1",
                      (int(company_id), int(project_id))).fetchone()
    return get(r["id"], company_id) if r else None


def get(aid: int, company_id: int) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM assessments WHERE id = ? AND company_id = ?", (int(aid), int(company_id))).fetchone()
    if not r:
        return None
    d = dict(r)
    for k in ("inputs", "result", "recovery"):
        d[k] = json.loads(d[k]) if d.get(k) else None
    return d


def delete(aid: int, company_id: int) -> bool:
    with _conn() as c:
        return c.execute("DELETE FROM assessments WHERE id = ? AND company_id = ?", (int(aid), int(company_id))).rowcount > 0


def delete_for_project(company_id: int, project_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM assessments WHERE company_id = ? AND project_id = ?", (int(company_id), int(project_id)))


def adopt_legacy(company_id: int) -> int:
    with _conn() as c:
        return c.execute("UPDATE assessments SET company_id = ? WHERE company_id IS NULL", (int(company_id),)).rowcount
