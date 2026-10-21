"""
Live site link: turns a one-off assessment into a monitored project.

Site staff open /site/<id> on a phone (QR code on the dashboard) and send what
happened since the last update: payments paid late, material stoppages,
variations, design changes, weather days, current SPI / CPI / value certified.
Each update is merged into the project state, re-scored by the model, stored in
the project's timeline, and pushed to every open dashboard over Server-Sent
Events (SSE), where the forecast, the BIM model colours and the recovery plan
refresh on their own.

How a live reading maps onto the trained model (stated, so it can be defended)
  * The models were trained on snapshots at 25 % and 50 % of contract time.
    Before 50 % the latest SPI/CPI is used as the 25 % reading (G25 model);
    from 50 % on it is used as the 50 % reading (G50 model).
  * Value certified is rescaled to the nearest checkpoint: cert_25 = cert x 25 / elapsed.
  * Event counts were trained as "events in the first quarter". Live counts are
    expressed per quarter of contract time: count x 25 / max(elapsed, 25), so a
    project two quarters in with 6 late payments reads like 3 in one quarter.
"""
from __future__ import annotations

import asyncio
import copy
import ipaddress
import json
import math
import re
import secrets
import socket
import time
from datetime import datetime

from . import alerts
from .db import add_columns, connect
from .inference import get_predictor
from .schema import FIELD_BY_KEY, FIELDS, match_option, norm, ordinal_value

COUNTERS = {"late_payments": "late_payments_q1", "material_events": "material_events_q1",
            "variations": "variations_q1", "rfis": "rfis_q1", "weather_days": "weather_days_q1"}
EVENT_TEXT = {"late_payments": ("IPC paid more than 30 days late", "IPCs paid more than 30 days late"),
              "material_events": ("material stoppage", "material stoppages"),
              "variations": ("variation order", "variation orders"),
              "rfis": ("design change or RFI", "design changes or RFIs"),
              "weather_days": ("weather day lost", "weather days lost")}
RATINGS = {"labour": "labour_q1", "subcontractor": "subcontractor_q1"}
EVM = ("spi", "cpi", "cert")

SCHEMA = """
CREATE TABLE IF NOT EXISTS live_projects (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
  name TEXT NOT NULL, base_inputs TEXT NOT NULL, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS live_updates (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL,
  created_at TEXT NOT NULL, reporter TEXT, note TEXT, changes TEXT, state TEXT, inputs TEXT,
  prediction TEXT, summary TEXT);
"""


def _conn():
    c = connect(SCHEMA)
    add_columns(c, "live_projects", {"location": "TEXT", "company_id": "INTEGER", "project_id": "INTEGER",
                                     "site_token": "TEXT"})  # nosec B105 - a column type, not a password
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_live_token ON live_projects(site_token)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_live_company ON live_projects(company_id)")
    return c


def new_token() -> str:
    """Unguessable capability for the phone link (128 bits). Sequential ids are never accepted from phones."""
    return secrets.token_urlsafe(16)


# ------------------------------------------------------------------ bands <-> counts
def _range(label: str):
    n = norm(label)
    if m := re.match(r"^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", n):
        return float(m[1]), float(m[2])
    if m := re.match(r"^more than (\d+)", n):
        return float(m[1]) + 1, math.inf
    if m := re.match(r"^(\d+)$", n):
        return float(m[1]), float(m[1])
    return None


def count_to_label(key: str, count: float) -> str:
    c = max(0, int(round(count)))
    for lab, _ in FIELD_BY_KEY[key]["options"]:
        r = _range(lab)
        if r and r[0] <= c <= r[1]:
            return lab
    return FIELD_BY_KEY[key]["options"][-1][0]


def label_to_count(key: str, label) -> float:
    lab = match_option(FIELD_BY_KEY[key], label)
    v = ordinal_value(FIELD_BY_KEY[key], lab) if lab else float("nan")
    return 0.0 if math.isnan(v) else float(v)


def rating_label(key: str, value: int) -> str:
    for lab, v in FIELD_BY_KEY[key]["options"]:
        if v == int(value):
            return lab
    return FIELD_BY_KEY[key]["options"][2][0]


def _num(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ state
def initial_state(inputs: dict, gate: str) -> dict:
    elapsed = 50.0 if gate == "G50" else 25.0
    scale = max(elapsed, 25.0) / 25.0
    st = {"elapsed_pct": elapsed,
          "counts": {c: label_to_count(k, inputs.get(k)) * scale for c, k in COUNTERS.items()},
          "labour": int(label_to_count("labour_q1", inputs.get("labour_q1")) or 3),
          "subcontractor": int(label_to_count("subcontractor_q1", inputs.get("subcontractor_q1")) or 3),
          "rework": inputs.get("rework_q1"), "mobilised": inputs.get("mobilised_q1")}
    for m in EVM:
        for cp in ("25", "50"):
            st[f"{m}_{cp}"] = _num(inputs.get(f"{m}_{cp}"))
    last = "50" if gate == "G50" and st["spi_50"] is not None else "25"
    st["spi_now"], st["cpi_now"] = st[f"spi_{last}"], st[f"cpi_{last}"]
    st["cert_now"] = st[f"cert_{last}"]
    return st


def inputs_from_state(base: dict, st: dict) -> tuple[dict, str]:
    inputs = {f["key"]: base.get(f["key"]) for f in FIELDS if f["stage"] == "award"}
    e = st["elapsed_pct"]
    per_quarter = 25.0 / max(e, 25.0)
    for c, key in COUNTERS.items():
        inputs[key] = count_to_label(key, st["counts"][c] * per_quarter)
    for r, key in RATINGS.items():
        inputs[key] = rating_label(key, st[r])
    inputs["rework_q1"], inputs["mobilised_q1"] = st.get("rework"), st.get("mobilised")
    for m in EVM:
        inputs[f"{m}_25"], inputs[f"{m}_50"] = st.get(f"{m}_25"), st.get(f"{m}_50")
    gate = "G50" if e >= 50 and st.get("spi_50") is not None else "G25"
    if gate == "G25":
        for m in EVM:
            inputs[f"{m}_50"] = None
    return inputs, gate


def apply_update(st: dict, upd: dict) -> tuple[dict, list[str]]:
    new, changes = copy.deepcopy(st), []
    e_old = st["elapsed_pct"]
    e = max(e_old, min(100.0, _num(upd.get("elapsed_pct")) or e_old))
    if e != e_old:
        changes.append(f"time elapsed {e_old:.0f}% \u2192 {e:.0f}%")
    new["elapsed_pct"] = e
    for c, n in (upd.get("events") or {}).items():
        n = _num(n) or 0
        if c in COUNTERS and n > 0:
            new["counts"][c] += n
            changes.append(f"+{n:g} {EVENT_TEXT[c][1 if n > 1 else 0]}")
    for r in RATINGS:
        v = _num(upd.get(r))
        if v is not None and int(v) != st.get(r):
            new[r] = int(max(1, min(5, v)))
            changes.append(f"{r} rating {st.get(r)} \u2192 {new[r]}")
    if upd.get("rework") and match_option(FIELD_BY_KEY["rework_q1"], upd["rework"]) != st.get("rework"):
        new["rework"] = match_option(FIELD_BY_KEY["rework_q1"], upd["rework"])
        changes.append(f"rework now {new['rework']}")
    cp = "50" if e >= 50 else "25"
    for m in EVM:
        v = _num(upd.get(m))
        if v is None:
            continue
        if m != "cert" and not 0.2 <= v <= 1.5:
            raise ValueError(f"{m.upper()} must be between 0.2 and 1.5")
        if v != st.get(f"{m}_now"):
            changes.append(f"{m.upper() if m != 'cert' else 'value certified'} "
                           f"{st.get(f'{m}_now') if st.get(f'{m}_now') is not None else '-'} \u2192 {v:g}{'%' if m == 'cert' else ''}")
        new[f"{m}_now"] = v
        new[f"{m}_{cp}"] = round(v * int(cp) / max(e, 1.0), 2) if m == "cert" else v
    return new, changes or ["status check, no change reported"]


# ------------------------------------------------------------------ scoring
def _summary(pred: dict, st: dict, prev: dict | None, rec: dict | None) -> dict:
    s = {"elapsed_pct": st["elapsed_pct"], "gate": pred["gate"], "time_overrun_pct": pred["time_overrun_pct"],
         "interval": pred["time_interval_pct"], "band": pred["band"], "probability": pred["high_risk_probability"],
         "health": pred["health"]["score"], "spi": st.get("spi_now"), "cpi": st.get("cpi_now"),
         "drivers": [c["label"] for c in pred["explanation"]["contributions"] if c["key"] != "_other" and c["shap"] > 0][:3]}
    if prev:
        s["delta_pts"] = round(pred["time_overrun_pct"] - prev["time_overrun_pct"], 1)
        s["band_before"] = prev["band"]["name"]
    if rec and rec.get("simulation"):
        s["p_on_time_before"] = rec["simulation"]["p_on_time_before"]
        s["p_on_time_after"] = rec["simulation"]["p_on_time_after"]
        s["p80_before_day"] = rec["simulation"]["p80_before_day"]
        s["p80_after_day"] = rec["simulation"]["p80_after_day"]
        s["days_recovered"] = rec["optimisation"].get("days_recovered")
    return s


def _score(base: dict, st: dict, prev_summary: dict | None):
    from .recovery import run_recovery
    inputs, gate = inputs_from_state(base, st)
    pred = get_predictor().predict(inputs, gate)
    rec = None
    try:
        spi = st.get("spi_50") if gate == "G50" else st.get("spi_25")
        rec = run_recovery(gate, spi, pred["time_overrun_pct"], pred["high_risk_probability"],
                           rework=inputs.get("rework_q1"), with_curve=False, elapsed_pct=st["elapsed_pct"])
    except Exception:
        rec = None
    return inputs, pred, _summary(pred, st, prev_summary, rec)


def create_project(name: str, inputs: dict, gate: str, location: dict | None = None,
                   company_id: int | None = None, project_id: int | None = None) -> dict:
    from . import weather
    base = {f["key"]: inputs.get(f["key"]) for f in FIELDS}
    if not location or location.get("lat") is None:
        location = weather.place(None, base.get("province"))
    st = initial_state(base, gate)
    now = datetime.now().isoformat(timespec="seconds")
    ins, pred, summ = _score(base, st, None)
    with _conn() as c:
        pid = c.execute("INSERT INTO live_projects (created_at, name, base_inputs, state, location, company_id,"
                        " project_id, site_token) VALUES (?,?,?,?,?,?,?,?)",
                        (now, (name or "").strip()[:120] or "Monitored project", json.dumps(base), json.dumps(st),
                         json.dumps(location), company_id, project_id, new_token())).lastrowid
        c.execute("INSERT INTO live_updates (project_id, created_at, reporter, note, changes, state, inputs, prediction, summary)"
                  " VALUES (?,?,?,?,?,?,?,?,?)", (pid, now, "REVIVE", "Monitoring started from the assessment",
                                                  json.dumps(["baseline assessment"]), json.dumps(st), json.dumps(ins),
                                                  json.dumps(pred), json.dumps(summ)))
    return get_project(pid)


def add_update(pid: int, upd: dict) -> dict:
    proj = get_project(pid, full=True)
    if not proj:
        raise KeyError(pid)
    st, changes = apply_update(proj["state"], upd)
    prev = proj["updates"][-1]["summary"] if proj["updates"] else None
    ins, pred, summ = _score(proj["base_inputs"], st, prev)
    now = datetime.now().isoformat(timespec="seconds")
    reporter = (upd.get("reporter") or "Site team").strip()[:60]
    note = (upd.get("note") or "").strip()[:500]
    with _conn() as c:
        uid = c.execute("INSERT INTO live_updates (project_id, created_at, reporter, note, changes, state, inputs, prediction, summary)"
                        " VALUES (?,?,?,?,?,?,?,?,?)", (pid, now, reporter, note, json.dumps(changes), json.dumps(st),
                                                        json.dumps(ins), json.dumps(pred), json.dumps(summ))).lastrowid
        c.execute("UPDATE live_projects SET state = ? WHERE id = ?", (json.dumps(st), pid))
    update = {"id": uid, "created_at": now, "reporter": reporter, "note": note, "changes": changes, "summary": summ}
    alert = None
    worse = prev and summ["band"]["name"] != prev["band"]["name"] and summ["time_overrun_pct"] > prev["time_overrun_pct"]
    if worse:
        alert = alerts.maybe_alert(proj["name"], pred, company_id=proj.get("company_id"))
    return {"project_id": pid, "project_name": proj["name"], "update": update, "inputs": ins,
            "prediction": pred, "alert": alert}


def get_project(pid: int, full: bool = False) -> dict | None:
    with _conn() as c:
        p = c.execute("SELECT * FROM live_projects WHERE id = ?", (pid,)).fetchone()
        if not p:
            return None
        ups = c.execute("SELECT * FROM live_updates WHERE project_id = ? ORDER BY id", (pid,)).fetchall()
    out = {"id": p["id"], "name": p["name"], "created_at": p["created_at"], "state": json.loads(p["state"]),
           "location": json.loads(p["location"]) if p["location"] else None,
           "company_id": p["company_id"], "project_id": p["project_id"], "site_token": p["site_token"],
           "base_inputs": json.loads(p["base_inputs"]) if full else None,
           "updates": [{"id": u["id"], "created_at": u["created_at"], "reporter": u["reporter"], "note": u["note"],
                        "changes": json.loads(u["changes"]), "summary": json.loads(u["summary"])} for u in ups]}
    if ups:
        out["latest"] = {"inputs": json.loads(ups[-1]["inputs"]), "prediction": json.loads(ups[-1]["prediction"])}
    return out


def updates_after(pid: int, after_id: int = 0, limit: int = 50) -> list[dict] | None:
    """Updates newer than after_id, in the same shape as the SSE 'update' event.
    The dashboard uses this to catch up after a dropped connection, so no phone update is ever missed."""
    with _conn() as c:
        p = c.execute("SELECT id, name FROM live_projects WHERE id = ?", (pid,)).fetchone()
        if not p:
            return None
        rows = c.execute("SELECT * FROM live_updates WHERE project_id = ? AND id > ? ORDER BY id LIMIT ?",
                         (pid, int(after_id), int(limit))).fetchall()
    return [{"project_id": pid, "project_name": p["name"],
             "update": {"id": u["id"], "created_at": u["created_at"], "reporter": u["reporter"], "note": u["note"],
                        "changes": json.loads(u["changes"]), "summary": json.loads(u["summary"])},
             "inputs": json.loads(u["inputs"]), "prediction": json.loads(u["prediction"]), "alert": None}
            for u in rows]


def list_projects(company_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT p.id, p.name, p.created_at, p.project_id, COUNT(u.id) AS n, MAX(u.id) AS last "
                         "FROM live_projects p LEFT JOIN live_updates u ON u.project_id = p.id WHERE p.company_id = ? "
                         "GROUP BY p.id ORDER BY p.id DESC", (int(company_id),)).fetchall()
        out = []
        for r in rows:
            s = c.execute("SELECT summary, created_at FROM live_updates WHERE id = ?", (r["last"],)).fetchone()
            out.append({"id": r["id"], "name": r["name"], "created_at": r["created_at"], "updates": r["n"],
                        "project_id": r["project_id"],
                        "last_update": s["created_at"] if s else None,
                        "summary": json.loads(s["summary"]) if s else None})
    return out


def owner(pid: int) -> int | None:
    """company_id of a monitored project (None if it does not exist)."""
    with _conn() as c:
        r = c.execute("SELECT company_id FROM live_projects WHERE id = ?", (int(pid),)).fetchone()
    return r["company_id"] if r else None


def by_token(token: str) -> int | None:
    if not token or len(token) > 64 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        return None
    with _conn() as c:
        r = c.execute("SELECT id FROM live_projects WHERE site_token = ?", (token,)).fetchone()
    return r["id"] if r else None


def for_project(company_id: int, project_id: int) -> int | None:
    with _conn() as c:
        r = c.execute("SELECT id FROM live_projects WHERE company_id = ? AND project_id = ? ORDER BY id DESC LIMIT 1",
                      (int(company_id), int(project_id))).fetchone()
    return r["id"] if r else None


def rotate_token(pid: int) -> str:
    """Revoke the old phone link (e.g. a phone was lost or a subcontractor left) and issue a new one."""
    tok = new_token()
    with _conn() as c:
        c.execute("UPDATE live_projects SET site_token = ? WHERE id = ?", (tok, int(pid)))
    BROKER.devices.pop(int(pid), None)
    return tok


def states(pid: int) -> list[dict]:
    """The project state after each update, oldest first (for the delay windows)."""
    with _conn() as c:
        rows = c.execute("SELECT state FROM live_updates WHERE project_id = ? ORDER BY id", (int(pid),)).fetchall()
    return [json.loads(r["state"]) for r in rows]


def delete_for_project(company_id: int, project_id: int) -> None:
    with _conn() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM live_projects WHERE company_id = ? AND project_id = ?",
                                          (int(company_id), int(project_id)))]
        for i in ids:
            c.execute("DELETE FROM live_updates WHERE project_id = ?", (i,))
            c.execute("DELETE FROM live_projects WHERE id = ?", (i,))


def legacy_monitors() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT id, name, base_inputs, location FROM live_projects WHERE company_id IS NULL").fetchall()
    return [{"id": r["id"], "name": r["name"], "base_inputs": json.loads(r["base_inputs"]),
             "location": json.loads(r["location"]) if r["location"] else None} for r in rows]


def assign(pid: int, company_id: int, project_id: int) -> None:
    with _conn() as c:
        c.execute("UPDATE live_projects SET company_id = ?, project_id = ?, site_token = COALESCE(site_token, ?) "
                  "WHERE id = ?", (int(company_id), int(project_id), new_token(), int(pid)))


def adopt_legacy(company_id: int) -> int:
    """Monitors created before company workspaces existed belong to the first company that signs up."""
    with _conn() as c:
        return c.execute("UPDATE live_projects SET company_id = ?, site_token = COALESCE(site_token, ?) "
                         "WHERE company_id IS NULL", (int(company_id), new_token())).rowcount


def weather_for_project(pid: int) -> dict:
    """Live weather at the site, plus the lost days observed since the last update
    (offered to the site engineer as a suggestion, never applied silently)."""
    from . import weather
    proj = get_project(pid)
    if not proj:
        raise KeyError(pid)
    loc = proj.get("location") or weather.place()
    out = weather.outlook(loc["lat"], loc["lon"], loc.get("name"))
    since = proj["updates"][-1]["created_at"] if proj["updates"] else proj["created_at"]
    lost = weather.lost_since(out, since)
    out["since"] = since[:10]
    out["suggested_lost_days"] = len(lost)
    out["suggested_days"] = lost
    return out


# ------------------------------------------------------------------ push channel
PRESENCE_TTL_S = 45
MAX_DEVICES = 50


def company_channel(company_id: int) -> str:
    return f"c{int(company_id)}"


class Broker:
    """In-process publish/subscribe for Server-Sent Events (one uvicorn worker).

    Queue items are (event_name, payload). Channels:
      * a company channel "c<company_id>": every monitored project OF THAT COMPANY (dashboards listen here),
      * a project channel <live id>: one project's events (the phone page listens here).
    A message is only ever delivered to its own project's channel and its own company's channel, so one
    company never receives another company's updates. Must be called from the event-loop thread."""

    def __init__(self):
        self.subs: dict[object, set[asyncio.Queue]] = {}
        self.site_queues: set[asyncio.Queue] = set()   # phone pages listening; not counted as dashboards
        self.devices: dict[int, dict[str, dict]] = {}

    def subscribe(self, channel, site: bool = False) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.subs.setdefault(channel, set()).add(q)
        if site:
            self.site_queues.add(q)
        return q

    def unsubscribe(self, channel, q: asyncio.Queue) -> None:
        self.subs.get(channel, set()).discard(q)
        self.site_queues.discard(q)

    def _targets(self, pid: int, company_id: int | None) -> set:
        qs = set(self.subs.get(pid, ()))
        if company_id is not None:
            qs |= set(self.subs.get(company_channel(company_id), ()))
        return qs

    def listeners(self, pid: int, company_id: int | None = None) -> int:
        """Open dashboards (not phones) that will receive this project's updates."""
        return len(self._targets(pid, company_id) - self.site_queues)

    def publish(self, pid: int, msg: dict, event: str = "update", company_id: int | None = None) -> int:
        """Send to the project's and its company's listeners; returns how many dashboards received it."""
        n = 0
        for q in self._targets(pid, company_id):
            try:
                q.put_nowait((event, msg))
                n += q not in self.site_queues
            except asyncio.QueueFull:
                pass
        return n

    def publish_company(self, company_id: int, msg: dict, event: str) -> None:
        for q in list(self.subs.get(company_channel(company_id), ())):
            try:
                q.put_nowait((event, msg))
            except asyncio.QueueFull:
                pass

    # ---- site devices (phones) that have the update page open
    def seen(self, pid: int, device: str, info: dict) -> dict:
        now = time.time()
        devs = self.devices.setdefault(pid, {})
        self.device_count(pid)
        if device not in devs and len(devs) >= MAX_DEVICES:      # bounded: a script cannot grow this forever
            oldest = min(devs, key=lambda k: devs[k]["last_seen"])
            devs.pop(oldest, None)
        first = device not in devs or now - devs[device]["last_seen"] > PRESENCE_TTL_S
        devs[device] = {**info, "last_seen": now}
        return {"project_id": pid, "devices": self.device_count(pid), "first": first,
                "device": info.get("label") or "Site device", "at": datetime.now().isoformat(timespec="seconds")}

    def device_count(self, pid: int) -> int:
        now = time.time()
        devs = self.devices.get(pid, {})
        for k in [k for k, v in devs.items() if now - v["last_seen"] > PRESENCE_TTL_S]:
            devs.pop(k, None)
        return len(devs)


BROKER = Broker()


# ------------------------------------------------------------------ network addresses for the phone link
def _route_ip() -> str | None:
    """Address of the interface that carries the default route (no packet is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _usable(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return a.version == 4 and not (a.is_loopback or a.is_link_local or a.is_unspecified or a.is_multicast)


def _rank(ip: str) -> int:
    """Typical Wi-Fi / hotspot ranges first; VirtualBox host-only and Docker bridges last."""
    if ip.startswith("192.168.56.") or ip.startswith("172.17."):
        return 9
    if ip.startswith("192.168."):
        return 0
    if ip.startswith("10."):
        return 1
    if ipaddress.ip_address(ip).is_private:
        return 2
    return 5


def lan_ips() -> list[str]:
    """Every IPv4 address a phone on the same network could use to reach this computer, best first."""
    found: list[str] = []
    primary = _route_ip()
    if primary and _usable(primary):
        found.append(primary)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if _usable(ip) and ip not in found:
                found.append(ip)
    except OSError:
        pass
    rest = sorted(found[1:], key=_rank)
    if found and _rank(found[0]) >= 9 and rest and _rank(rest[0]) < 9:
        return rest + found[:1]
    return found[:1] + rest
