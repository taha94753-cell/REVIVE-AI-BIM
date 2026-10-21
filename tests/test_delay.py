"""Current delay analysis: earned schedule maths, schedule update, windows and the API."""
from datetime import date

from conftest import new_project
from revive import delay
from revive.presets import PRESETS
from revive.scheduling import cpm, load_schedule


def _setup():
    acts = load_schedule()
    base = cpm(acts)
    return acts, base, delay.planned_curve(acts, base), base["finish"]


def test_planned_curve_is_monotone_and_invertible():
    acts, base, curve, planned = _setup()
    ts, pv = curve
    assert pv[0] == 0 and abs(pv[-1] - 1) < 1e-6 and all(b >= a for a, b in zip(pv, pv[1:]))
    for t in (0, 13.7, planned / 3, planned / 2, planned * 0.9):
        assert abs(delay.earned_schedule(curve, delay.pv_at(curve, t)) - t) < 1e-6 or delay.pv_at(curve, t) == 0


def test_on_programme_project_has_no_delay():
    acts, base, curve, planned = _setup()
    s = delay.status_point(curve, planned, 40, spi=1.0)
    assert s["sv_t"] == 0 and s["spi_t"] == 1.0
    upd = delay.schedule_update(acts, base, s["at"], s["es"])
    assert abs(upd["finish"] - planned) < 0.05


def test_schedule_update_matches_earned_schedule_when_only_spi_is_known():
    acts, base, curve, planned = _setup()
    for spi in (0.95, 0.85, 0.7):
        s = delay.status_point(curve, planned, 35, spi=spi)
        upd = delay.schedule_update(acts, base, s["at"], s["es"])
        assert abs((upd["finish"] - planned) - (s["at"] - s["es"])) < 0.05    # delay = AT - ES
        assert s["es"] < s["at"]


def test_activity_progress_captures_out_of_sequence_work():
    acts, base, curve, planned = _setup()
    at = 0.3 * planned
    crit = [a.id for a in acts if a.id in base["critical"] and base["es"][a.id] < at]
    behind = {crit[-1]: 0.0}                                  # the critical activity due by now has not started
    s = delay.status_point(curve, planned, 30, spi=1.0)
    upd = delay.schedule_update(acts, base, at, s["es"], behind)
    assert upd["finish"] > planned + 1                       # a stalled critical activity delays completion


def test_window_apportionment_adds_up():
    share = delay.apportion(12, {"weather_days": 4, "late_payments": 1, "material_events": 1})
    assert share["neutral"] == 4 and share["client"] == 4 and share["contractor"] == 4
    assert delay.apportion(5, {})["unexplained"] == 5
    assert sum(delay.apportion(-3, {"late_payments": 2}).values()) == 0      # recovery is not apportioned


def test_delay_api_before_and_after_site_updates(client):
    proj = new_project(client, "Delay check", start_date=(date.today().replace(day=1)).isoformat(),
                       details={"planned_months": 12})
    h = {"X-Revive-Project": str(proj["id"])}
    first = client.get(f"/api/projects/{proj['id']}/delay").json()
    assert first["available"] is False                                       # nothing reported yet
    p = PRESETS[0]
    lp = client.post("/api/live", json={"inputs": p["inputs"], "gate": p["gate"]}, headers=h).json()
    tok = lp["site_path"].rsplit("/", 1)[1]
    client.post(f"/api/site/{tok}/update", json={"elapsed_pct": 35, "spi": 0.8, "events": {"late_payments": 2}})
    client.post(f"/api/site/{tok}/update", json={"elapsed_pct": 45, "spi": 0.72, "events": {"weather_days": 3, "material_events": 1}})
    d = client.get(f"/api/projects/{proj['id']}/delay").json()
    assert d["available"] and d["delay_days"] > 0 and d["status"]["elapsed_pct"] == 45
    assert len(d["windows"]) == 3 and d["windows"][-1]["apportioned"]["neutral"] <= 3
    gross = sum(sum(v for k, v in w["apportioned"].items()) for w in d["windows"])
    assert abs(gross - d["apportionment"]["recovered"] - d["delay_days"]) < 1.0   # windows reconcile to the total
    assert d["finish"]["ml_forecast"] is not None and d["finish"]["current_pace"] > d["planned_days"]
    assert d["calendar"] is not None
    # the planner's activity progress takes over as the status source
    acts = client.get(f"/api/projects/{proj['id']}/activities").json()["activities"]
    r = client.post(f"/api/projects/{proj['id']}/progress", json={"elapsed_pct": 50, "activities": {acts[0]["id"]: 100}})
    assert r.status_code == 200 and r.json()["source"].startswith("Activity progress")
