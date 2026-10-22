"""Extension-of-time evidence pack and the early-warning record."""
from conftest import new_project

from revive.evidence import early_warning
from revive.presets import PRESETS

UPDATES = [{"elapsed_pct": 30, "spi": 0.86, "events": {"late_payments": 1}, "note": "IPC-3 unpaid 41 days"},
           {"elapsed_pct": 36, "spi": 0.82, "events": {"weather_days": 3, "material_events": 1}, "note": "Rain, rebar late"},
           {"elapsed_pct": 41, "spi": 0.80, "events": {"variations": 1}, "note": "VO-2 without time"}]


def _monitored(client, name="Hospital block"):
    pre = PRESETS[0]
    p = new_project(client, name, client="CDA", code="CDA/26/1", start_date="2026-01-05",
                    details={"planned_months": pre["inputs"]["planned_months"], "province": "Punjab"},
                    inputs=pre["inputs"], gate=pre["gate"])
    h = {"X-Revive-Project": str(p["id"])}
    assert client.post("/api/assessments", json={"name": "At 25%", "inputs": pre["inputs"], "gate": pre["gate"]},
                       headers=h).status_code == 200
    lp = client.post("/api/live", json={"name": name, "inputs": pre["inputs"], "gate": pre["gate"]}, headers=h).json()
    tok = lp["site_path"].rstrip("/").split("/")[-1]
    for u in UPDATES:
        r = client.post(f"/api/site/{tok}/update", json={"reporter": "Site engineer", **u})
        assert r.status_code == 200, r.text
    return p


def test_evidence_pack_has_the_records_a_claim_needs(client):
    p = _monitored(client)
    d = client.get(f"/api/projects/{p['id']}/evidence").json()
    assert d["project"]["name"] == "Hospital block" and d["company"] and d["prepared_by"]
    assert d["delay"]["available"] and d["delay"]["delay_days"] > 0
    assert len(d["site_records"]) == 1 + len(UPDATES)                      # monitoring start + three updates
    assert any("IPC" in r["note"] for r in d["site_records"])
    assert any(r["reported"] for r in d["site_records"][1:])
    assert d["windows"] and abs(sum(d["apportionment"][k] for k in ("client", "neutral", "contractor", "unexplained"))
                                - sum(max(0, w["slip_days"]) for w in d["windows"])) < 0.5
    assert len(d["forecast_history"]) >= 1 + len(UPDATES)
    assert d["early_warning"]["warned"] and d["early_warning"]["days_before_completion"] > 0
    assert d["notice"] and d["notice"]["due"] > d["notice"]["aware"]
    assert "not a forensic" in d["disclaimer"]


def test_evidence_pack_is_company_private(client, other):
    p = _monitored(client, "Private tower")
    assert other.get(f"/api/projects/{p['id']}/evidence").status_code == 404


def test_evidence_page_needs_a_session(client):
    from fastapi.testclient import TestClient
    from revive.server import app
    p = new_project(client, "Page check")
    assert client.get(f"/evidence/{p['id']}").status_code == 200
    anon = TestClient(app)
    r = anon.get(f"/evidence/{p['id']}", follow_redirects=False)
    assert r.status_code == 303


def test_early_warning_counts_the_contract_time_left():
    hist = [{"elapsed_pct": 25, "band": "Watch", "time_overrun_pct": 20},
            {"elapsed_pct": 40, "band": "At risk", "time_overrun_pct": 35},
            {"elapsed_pct": 50, "band": "Critical", "time_overrun_pct": 60}]
    w = early_warning(hist, contract_days=400, start=None)
    assert w["warned"] and w["elapsed_pct"] == 40 and w["days_before_completion"] == 240
    assert not early_warning(hist[:1], 400, None)["warned"]
