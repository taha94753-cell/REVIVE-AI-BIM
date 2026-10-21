"""
Schedule engine: CPM, progress status at a checkpoint, and the ML-driven forecast.

Forecast logic (how the AI prediction reaches the schedule)
  1. The baseline is computed with the Critical Path Method (CPM).
  2. At the checkpoint (25 % or 50 % of contract time = t0), work actually done is
     estimated with the Earned Schedule idea: ES = SPI x t0. Activities planned to
     finish before ES are complete, the one straddling ES is partly complete.
  3. The remaining work is re-networked from t0 and every remaining duration is
     scaled by one factor k chosen so the forecast finish equals the finish date
     implied by the ML forecast:  finish = planned_duration x (1 + overrun/100).
     (Uniform scaling is a transparent simplification; it keeps the network logic
     and the critical path intact.)
"""
from __future__ import annotations

import csv
import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .config import active_file, load_config

DAYS_PER_MONTH = 30.4375


@dataclass
class Activity:
    id: str
    name: str
    wbs: str
    duration: float
    preds: list[str] = field(default_factory=list)
    crash_max_days: float | None = None
    crash_cost_per_day: float = 0.0
    crash_method: str = ""
    trade: str = ""
    ifc_storey: str = "*"
    ifc_types: list[str] = field(default_factory=list)
    weather_sensitive: bool | None = None

    @property
    def is_weather_sensitive(self) -> bool:
        if self.weather_sensitive is not None:
            return self.weather_sensitive
        trades = [t.lower() for t in load_config().get("weather", {}).get("weather_sensitive_trades", [])]
        return self.trade.lower() in trades

    @property
    def crash_fraction(self) -> float:
        default = load_config()["optimizer"]["default_crash_fraction"]
        if self.crash_max_days is None or self.duration <= 0:
            return default
        return max(0.0, min(0.6, self.crash_max_days / self.duration))


def load_schedule(file: str | Path | None = None) -> list[Activity]:
    file = Path(file) if file else active_file("schedule")
    acts = []
    with open(file, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            acts.append(Activity(
                id=row["id"].strip(), name=row["name"].strip(), wbs=row.get("wbs", row["id"]).strip(),
                duration=float(row["duration_days"]),
                preds=[p.strip() for p in (row.get("predecessors") or "").replace(",", ";").split(";") if p.strip()],
                crash_max_days=float(row["crash_max_days"]) if row.get("crash_max_days") else None,
                crash_cost_per_day=float(row.get("crash_cost_per_day_pkr") or 0),
                crash_method=(row.get("crash_method") or "").strip(),
                trade=(row.get("trade") or "").strip(),
                ifc_storey=(row.get("ifc_storey") or "*").strip(),
                ifc_types=[t.strip() for t in (row.get("ifc_types") or "").split(";") if t.strip()],
                weather_sensitive=_yes_no(row.get("weather_sensitive")),
            ))
    validate(acts)
    return acts


def _yes_no(v) -> bool | None:
    v = (v or "").strip().lower()
    return True if v in ("yes", "y", "true", "1") else False if v in ("no", "n", "false", "0") else None


COLUMNS = ["id", "name", "wbs", "duration_days", "predecessors", "crash_max_days", "crash_cost_per_day_pkr",
           "crash_method", "trade", "ifc_storey", "ifc_types", "weather_sensitive"]


def write_schedule_csv(acts: list[Activity], dest: str | Path) -> Path:
    dest = Path(dest)
    with open(dest, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for a in acts:
            w.writerow({"id": a.id, "name": a.name, "wbs": a.wbs, "duration_days": a.duration,
                        "predecessors": ";".join(a.preds), "crash_max_days": a.crash_max_days,
                        "crash_cost_per_day_pkr": a.crash_cost_per_day, "crash_method": a.crash_method,
                        "trade": a.trade, "ifc_storey": a.ifc_storey if a.ifc_storey != "*" else "",
                        "ifc_types": ";".join(a.ifc_types),
                        "weather_sensitive": "" if a.weather_sensitive is None else ("yes" if a.weather_sensitive else "no")})
    return dest


def validate(acts: list[Activity]) -> None:
    ids = {a.id for a in acts}
    for a in acts:
        for p in a.preds:
            if p not in ids:
                raise ValueError(f"Activity {a.id} lists unknown predecessor {p}")
    topo_order(acts)  # raises on cycles


def topo_order(acts: list[Activity]) -> list[Activity]:
    by_id = {a.id: a for a in acts}
    indeg = {a.id: len(a.preds) for a in acts}
    succ = {a.id: [] for a in acts}
    for a in acts:
        for p in a.preds:
            succ[p].append(a.id)
    queue = deque(i for i, d in indeg.items() if d == 0)
    order = []
    while queue:
        i = queue.popleft()
        order.append(by_id[i])
        for s in succ[i]:
            indeg[s] -= 1
            if indeg[s] == 0:
                queue.append(s)
    if len(order) != len(acts):
        raise ValueError("Schedule contains a dependency cycle")
    return order


def cpm(acts: list[Activity], durations: dict[str, float] | None = None, t0: float = 0.0,
        active: set[str] | None = None) -> dict:
    """Forward/backward pass. `active` limits the network to remaining activities."""
    durations = durations or {a.id: a.duration for a in acts}
    order = [a for a in topo_order(acts) if active is None or a.id in active]
    ids = {a.id for a in order}
    es, ef = {}, {}
    for a in order:
        start = max([ef[p] for p in a.preds if p in ids] + [t0])
        es[a.id], ef[a.id] = start, start + durations[a.id]
    finish = max(ef.values()) if ef else t0
    succ = {a.id: [] for a in order}
    for a in order:
        for p in a.preds:
            if p in ids:
                succ[p].append(a.id)
    ls, lf = {}, {}
    for a in reversed(order):
        lf[a.id] = min([ls[s] for s in succ[a.id]] + [finish])
        ls[a.id] = lf[a.id] - durations[a.id]
    tf = {i: max(0.0, ls[i] - es[i]) for i in es}
    return {"es": es, "ef": ef, "ls": ls, "lf": lf, "tf": tf, "finish": finish,
            "critical": [i for i in es if tf[i] < 1e-6]}


def forecast(acts: list[Activity], elapsed_fraction: float, spi: float | None,
             predicted_overrun_pct: float) -> dict:
    base = cpm(acts)
    planned = base["finish"]
    t0 = elapsed_fraction * planned
    spi = 1.0 if spi is None or (isinstance(spi, float) and math.isnan(spi)) else max(0.2, min(1.5, spi))
    earned = min(planned, spi * t0)

    pct, remaining = {}, {}
    for a in acts:
        s, f = base["es"][a.id], base["ef"][a.id]
        p = 1.0 if f <= earned else (0.0 if s >= earned else (earned - s) / max(a.duration, 1e-9))
        pct[a.id] = round(p, 4)
        remaining[a.id] = a.duration * (1 - p)
    active = {a.id for a in acts if pct[a.id] < 1.0}
    unit = cpm(acts, remaining, t0=t0, active=active)
    span = max(unit["finish"] - t0, 1e-6)
    target_finish = planned * (1 + predicted_overrun_pct / 100.0)
    k = max(0.3, (target_finish - t0) / span)
    fdur = {i: remaining[i] * k for i in active}
    fc = cpm(acts, fdur, t0=t0, active=active)
    return {"baseline": base, "planned_finish": planned, "t0": t0, "earned_schedule": earned, "spi_used": spi,
            "pct_complete": pct, "active": sorted(active), "k": k, "forecast_durations": fdur,
            "forecast": fc, "forecast_finish": fc["finish"]}
