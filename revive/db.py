"""One SQLite file (data/app.db) for companies, users, sessions, projects, assessments and live monitors.

Every query in REVIVE is parameterised (no string-built SQL), and every row that belongs to a company
carries company_id, which every read filters on. WAL mode lets the live stream read while a phone
update writes.

On a stateless host (Vercel) the local file would vanish when the container stops, so when
TURSO_DATABASE_URL is set the same SQL runs on a hosted SQLite (Turso) over its HTTP API instead.
`Remote` behaves like sqlite3 for what REVIVE uses: Row access by name, implicit transactions,
commit on `with` exit, sqlite3 exceptions.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import threading
import urllib.error
import urllib.request

from .config import database_path

_READY: set[str] = set()
_LOCK = threading.Lock()


def connect(schema: str | None = None):
    url = os.environ.get("TURSO_DATABASE_URL")
    if url and not os.environ.get("REVIVE_DB"):
        c = Remote(url, os.environ.get("TURSO_AUTH_TOKEN", ""))
        if schema and ("schema", schema) not in _READY:   # one round trip per process, not per request
            c.executescript(schema)
            _READY.add(("schema", schema))
        return c
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


def add_columns(c, table: str, columns: dict[str, str]) -> None:
    """Add missing columns to an existing table (lightweight migration for older app.db files)."""
    if isinstance(c, Remote) and ("cols", table) in _READY:
        return
    have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}  # table names are code constants
    for name, decl in columns.items():
        if name not in have:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    if isinstance(c, Remote):
        c.commit()
        _READY.add(("cols", table))


# ------------------------------------------------------------------ hosted SQLite (Turso, Hrana over HTTP)
class Row(tuple):
    """sqlite3.Row stand-in: r[0], r["name"], r.keys(), dict(r)."""

    def __new__(cls, values, keys):
        r = super().__new__(cls, values)
        r._keys = keys
        return r

    def __getitem__(self, k):
        return super().__getitem__(self._keys.index(k) if isinstance(k, str) else k)

    def keys(self):
        return list(self._keys)


class Cursor:
    def __init__(self, result: dict | None):
        result = result or {}
        keys = [c.get("name") for c in result.get("cols", [])]
        self._rows = [Row([_decode(v) for v in row], keys) for row in result.get("rows", [])]
        self.description = [(k, None, None, None, None, None, None) for k in keys] or None
        rid = result.get("last_insert_rowid")
        self.lastrowid = int(rid) if rid is not None else None
        self.rowcount = result.get("affected_row_count", -1)

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def __iter__(self):
        return iter(self.fetchall())


_DML = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b", re.I)


class Remote:
    """One Turso stream per connection. Like sqlite3, a write opens a transaction that `commit()`
    (or leaving `with`) ends; without a commit the server drops it when the stream closes."""

    def __init__(self, url: str, token: str):
        self.url = re.sub(r"^libsql://", "https://", url).rstrip("/")
        self.token = token
        self.baton = None
        self.in_tx = False

    def _pipeline(self, requests: list[dict]) -> list[dict]:
        n = len(requests)
        if not self.in_tx:   # nothing to keep open: close the stream in the same round trip
            requests = [*requests, {"type": "close"}]
        body = json.dumps({"baton": self.baton, "requests": requests}).encode()
        req = urllib.request.Request(self.url + "/v2/pipeline", data=body, method="POST",
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310 - https URL from the deploy settings
                out = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise sqlite3.OperationalError(f"database HTTP {e.code}: {e.read()[:200]!r}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise sqlite3.OperationalError(f"database unreachable: {e}") from e
        self.baton = out.get("baton") if self.in_tx else None
        if out.get("base_url"):
            self.url = out["base_url"].rstrip("/")
        for res in out["results"]:
            if res.get("type") == "error":
                self.in_tx, self.baton = False, None   # the server ends the stream after an error
                msg = (res.get("error") or {}).get("message", "database error")
                raise (sqlite3.IntegrityError if "constraint" in msg.lower() else sqlite3.OperationalError)(msg)
        return [res["response"] for res in out["results"][:n]]

    def execute(self, sql: str, params=()) -> Cursor:
        reqs = []
        if not self.in_tx and _DML.match(sql):
            reqs.append({"type": "execute", "stmt": {"sql": "BEGIN"}})
            self.in_tx = True
        reqs.append({"type": "execute", "stmt": {"sql": sql, "args": [_encode(p) for p in params]}})
        return Cursor(self._pipeline(reqs)[-1].get("result"))

    def executemany(self, sql: str, seq) -> Cursor:
        cur = Cursor(None)
        for params in seq:
            cur = self.execute(sql, params)
        return cur

    def executescript(self, script: str) -> None:
        self.commit()
        self._pipeline([{"type": "sequence", "sql": script}])

    def commit(self) -> None:
        if self.in_tx:
            self.in_tx = False
            self._pipeline([{"type": "execute", "stmt": {"sql": "COMMIT"}}])

    def rollback(self) -> None:
        if self.in_tx:
            self.in_tx = False
            self._pipeline([{"type": "execute", "stmt": {"sql": "ROLLBACK"}}])

    def close(self) -> None:
        self.rollback()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        self.rollback() if exc_type else self.commit()
        return False



def _encode(v) -> dict:
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"type": "blob", "base64": base64.b64encode(bytes(v)).decode()}
    return {"type": "text", "value": str(v)}


def _decode(v: dict):
    t = v.get("type")
    if t == "integer":
        return int(v["value"])
    if t == "float":
        return float(v["value"])
    if t == "text":
        return v["value"]
    if t == "blob":
        b = v["base64"]
        return base64.b64decode(b + "=" * (-len(b) % 4))
    return None
