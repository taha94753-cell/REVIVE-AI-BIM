from conftest import new_project

from revive.presets import PRESETS


def test_end_to_end_flow(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/schema").status_code == 200
    p = PRESETS[0]
    pred = client.post("/api/predict", json={"inputs": p["inputs"], "gate": p["gate"]}).json()
    contrib = sum(x["shap"] for x in pred["explanation"]["contributions"])
    assert abs(pred["explanation"]["base_value"] + contrib - pred["time_overrun_pct"]) < 0.3   # SHAP adds up
    assert 0 <= pred["health"]["score"] <= 100
    rec = client.post("/api/recovery", json={"gate": pred["gate"], "spi": p["inputs"]["spi_25"],
                                             "time_overrun_pct": pred["time_overrun_pct"],
                                             "high_risk_probability": pred["high_risk_probability"]}).json()
    assert rec["optimisation"]["status"] == "Optimal"
    assert rec["optimisation"]["recovered_finish_day"] <= rec["forecast_finish_day"]
    assert len(client.get("/api/bim/geometry").json()["meshes"]) > 0
    assert client.get("/api/portfolio").status_code == 200


def test_company_can_run_many_projects(client):
    a = new_project(client, "Tower A", client="CDA", start_date="2026-01-15",
                    details={"province": "Punjab", "project_type": "Commercial building", "planned_months": 18})
    b = new_project(client, "Bridge B", details={"province": "Sindh"})
    assert a["location"]["name"] == "Lahore" and b["location"]["name"] == "Karachi"   # province capital default
    names = [p["name"] for p in client.get("/api/projects").json()]
    assert {"Tower A", "Bridge B"} <= set(names)
    full = client.get(f"/api/projects/{a['id']}").json()
    assert full["details"]["province"] == "Punjab" and full["details"]["planned_months"] == 18
    assert full["inputs"] is None and full["has_inputs"] is False      # details alone are not an assessment
    r = client.patch(f"/api/projects/{a['id']}", json={"client": "CDA Islamabad"})
    assert r.json()["client"] == "CDA Islamabad"
    assert client.delete(f"/api/projects/{b['id']}").status_code == 200
    assert client.get(f"/api/projects/{b['id']}").status_code == 404


def test_saving_an_assessment_is_rescored_by_the_server(client):
    proj = new_project(client, "Plaza")
    p = PRESETS[1]
    forged = {"band": {"name": "On track"}, "time_overrun_pct": 0}
    r = client.post("/api/assessments", json={"name": "Plaza Q1", "inputs": p["inputs"], "gate": p["gate"],
                                              "result": forged}, headers={"X-Revive-Project": str(proj["id"])})
    assert r.status_code == 200
    saved = client.get(f"/api/assessments/{r.json()['id']}").json()
    truth = client.post("/api/predict", json={"inputs": p["inputs"], "gate": p["gate"]}).json()
    assert abs(saved["time_overrun_pct"] - truth["time_overrun_pct"]) < 1e-6   # the forged result was ignored
    assert client.get(f"/api/projects/{proj['id']}").json()["has_inputs"] is True
