"""One SQLite file (data/app.db) for companies, users, sessions, projects, assessments and live monitors.

Every query in REVIVE is parameterised (no string-built SQL), and every row that belongs to a company
carries company_id, which every read filters on. WAL mode lets the live stream read while a phone
update writes.
"""
from __future__ import annotations

import sqlite3
import threading

from .config import database_path

_READY: set[str] = set()
_LOCK = threading.Lock()


def connect(schema: str | None = None) -> sqlite3.Connection:
    db = database_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(db, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout = 15000")
    key = str(db)
    if key not in _READY:
        with _LOCK:
            if key not in _READY:
                try:
                    c.execute("PRAGMA journal_mode = WAL")
                except sqlite3.DatabaseError:
                    pass
                _READY.add(key)
    if schema:
        c.executescript(schema)
    return c


def add_columns(c: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    """Add missing columns to an existing table (lightweight migration for older app.db files)."""
    have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}  # table names are code constants
    for name, decl in columns.items():
        if name not in have:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
