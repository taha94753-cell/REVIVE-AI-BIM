"""Live weather rules, P6 import, per-project schedules and running with or without a BIM model."""
from conftest import new_project

from revive import weather
from revive.presets import PRESETS
from revive.recovery import run_recovery
from revive.schedule_import import parse_xer
from revive.scheduling import cpm, load_schedule

# Same shape as an Open-Meteo /v1/forecast daily response
PAYLOAD = {"utc_offset_seconds": 18000, "daily": {
    "time": ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03"],
    "precipitation_sum": [0.0, 22.5, 0.4, 0.0, 14.0, 1.0],
    "temperature_2m_max": [34.0, 29.0, 31.0, 46.0, 30.0, 32.0],
    "temperature_2m_min": [21.0, 19.0, 20.0, 24.0, 18.0, 19.0],
    "wind_speed_10m_max": [12.0, 18.0, 55.0, 10.0, 14.0, 9.0]}}


def test_lost_day_rules():
    a = weather.assess(PAYLOAD, today="2026-10-01")
    assert a["lost_past"] == 2                      # rain 22.5 mm, wind 55 km/h
    assert a["lost_forecast_offsets"] == [0, 1]     # heat 46 C today, rain 14 mm tomorrow
    assert [d["date"] for d in weather.lost_since(a, "2026-09-30")] == ["2026-09-30"]


def test_weather_failure_never_breaks_the_app(monkeypatch):
    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(weather, "fetch", boom)
    out = weather.outlook(33.6, 73.0, "Rawalpindi")
    assert out["available"] is False and "manually" in out["reason"]


def test_weather_days_extend_sensitive_work_only():
    base = run_recovery("G25", 0.91, 40.0, 0.7, with_curve=False, simulate_risk=False)
    wet = run_recovery("G25", 0.91, 40.0, 0.7, with_curve=False, simulate_risk=False,
                       weather_lost_offsets=[0, 1, 2, 5])
    assert wet["weather"]["affected"]
    assert wet["forecast_finish_day"] >= base["forecast_finish_day"]
    sensitive = {a.id for a in load_schedule() if a.is_weather_sensitive}
    assert all(x["id"] in sensitive for x in wet["weather"]["affected"])


def _xer_from(acts):
    rows = ["ERMHDR\t20.12", "%T\tPROJWBS", "%F\twbs_id\twbs_short_name\twbs_name", "%R\t10\tB\tBuilding",
            "%T\tTASK", "%F\ttask_id\ttask_code\ttask_name\ttask_type\ttarget_drtn_hr_cnt\twbs_id"]
    rows += [f"%R\t{i}\t{a.id}\t{a.name}\tTT_Task\t{a.duration * 8}\t10" for i, a in enumerate(acts, 1)]
    rows += ["%R\t999\tLOE1\tProject management\tTT_LOE\t3000\t10"]
    ids = {a.id: i for i, a in enumerate(acts, 1)}
    rows += ["%T\tTASKPRED", "%F\ttask_pred_id\ttask_id\tpred_task_id\tpred_type\tlag_hr_cnt"]
    k = 1
    for a in acts:
        for p in a.preds:
            rows.append(f"%R\t{k}\t{ids[a.id]}\t{ids[p]}\tPR_FS\t0")
            k += 1
    return "\n".join(rows + ["%E"])


def test_p6_xer_round_trip():
    acts = load_schedule()
    imported, report = parse_xer(_xer_from(acts))
    assert report["activities"] == len(acts) and report["skipped_level_of_effort_or_wbs"] == 1
    assert abs(cpm(imported)["finish"] - cpm(acts)["finish"]) < 1e-6


def test_app_runs_with_and_without_bim(client):
    proj = new_project(client, "No-BIM project")
    h = {"X-Revive-Project": str(proj["id"])}
    off = client.post("/api/bim/disconnect", headers=h).json()
    assert off["connected"] is False and off["schedule"]["activities"] > 0
    assert client.get("/api/bim/geometry", headers=h).json()["connected"] is False
    p = PRESETS[0]
    pred = client.post("/api/predict", json={"inputs": p["inputs"], "gate": p["gate"]}).json()
    rec = client.post("/api/recovery", headers=h, json={"gate": "G25", "spi": 0.91, "time_overrun_pct": pred["time_overrun_pct"],
                                                         "high_risk_probability": pred["high_risk_probability"]}).json()
    assert rec["optimisation"]["status"] == "Optimal" and rec["bim_connected"] is False
    assert rec["sustainability"]["rework_carbon_at_risk_t"] is None
    assert client.post("/api/bim/export", headers=h, json={"time_overrun_pct": 40}).status_code == 400
    # another project of the same company is untouched by that disconnect
    other = new_project(client, "BIM project")
    assert client.get("/api/bim/summary", headers={"X-Revive-Project": str(other["id"])}).json()["connected"] is True
    on = client.post("/api/bim/demo", headers=h).json()
    assert on["connected"] is True and len(client.get("/api/bim/geometry", headers=h).json()["meshes"]) > 0


def test_schedule_upload_is_per_project_and_validated(client):
    a, b = new_project(client, "A"), new_project(client, "B")
    acts = load_schedule()[:6]
    for x in acts:
        x.preds = [p for p in x.preds if p in {y.id for y in acts}]
    xer = _xer_from(acts).encode()
    r = client.post("/api/schedule/upload", headers={"X-Revive-Project": str(a["id"])},
                    files={"file": ("plan.xer", xer, "application/octet-stream")})
    assert r.status_code == 200, r.text
    assert r.json()["schedule"]["activities"] == 6 and r.json()["schedule"]["demo"] is False
    sb = client.get("/api/bim/summary", headers={"X-Revive-Project": str(b["id"])}).json()["schedule"]
    assert sb["demo"] is True and sb["activities"] > 6          # project B still on its own (demo) schedule
    bad = client.post("/api/schedule/upload", headers={"X-Revive-Project": str(a["id"])},
                      files={"file": ("plan.xer", b"not a schedule", "application/octet-stream")})
    assert bad.status_code == 400
    again = client.get("/api/bim/summary", headers={"X-Revive-Project": str(a["id"])}).json()["schedule"]
    assert again["activities"] == 6                                # a rejected upload never replaces the good one
