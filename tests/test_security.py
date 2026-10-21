"""Every security fix has a test, so a later change cannot quietly undo it."""
from fastapi.testclient import TestClient

from conftest import PASSWORD, company_client, new_project
from revive import auth
from revive.presets import PRESETS
from revive.security import LIMITER
from revive.server import app


def anon():
    LIMITER.hits.clear()
    return TestClient(app, headers={"X-Revive-Request": "1"})


def test_api_needs_a_signed_in_user():
    with anon() as c:
        for path in ("/api/projects", "/api/portfolio", "/api/schema", "/api/model-card", "/api/live",
                     "/api/assessments", "/api/bim/geometry", "/api/weather?lat=33&lon=73"):
            assert c.get(path).status_code == 401, path
        assert c.post("/api/predict", json={"inputs": {}}).status_code == 401
        assert c.get("/api/ping").status_code == 200 and c.get("/api/public/overview").status_code == 200
        r = c.get("/app", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/")


def test_companies_cannot_see_each_other(client, other):
    proj = new_project(client, "Secret tower")
    p = PRESETS[0]
    h = {"X-Revive-Project": str(proj["id"])}
    lp = client.post("/api/live", json={"inputs": p["inputs"], "gate": p["gate"]}, headers=h).json()
    aid = client.post("/api/assessments", json={"name": "Secret", "inputs": p["inputs"], "gate": p["gate"]},
                      headers=h).json()["id"]
    # the other company gets 404 for every id it guesses
    assert other.get(f"/api/projects/{proj['id']}").status_code == 404
    assert other.get(f"/api/projects/{proj['id']}/delay").status_code == 404
    assert other.patch(f"/api/projects/{proj['id']}", json={"name": "pwned"}).status_code == 404
    assert other.delete(f"/api/projects/{proj['id']}").status_code == 404
    assert other.get("/api/bim/summary", headers=h).status_code == 404       # cannot borrow the header either
    assert other.post("/api/bim/disconnect", headers=h).status_code == 404
    assert other.get(f"/api/live/{lp['id']}").status_code == 404
    assert other.get(f"/api/live/{lp['id']}/updates").status_code == 404
    assert other.get(f"/api/live/{lp['id']}/qr.svg").status_code == 404
    assert other.get(f"/api/assessments/{aid}").status_code == 404
    assert other.delete(f"/api/assessments/{aid}").status_code == 404
    assert all(x["id"] != proj["id"] for x in other.get("/api/projects").json())
    assert all(x["id"] != lp["id"] for x in other.get("/api/live").json())
    assert all(x["id"] != aid for x in other.get("/api/portfolio").json()["saved"])
    assert client.get(f"/api/projects/{proj['id']}").json()["name"] == "Secret tower"


def test_csrf_header_and_origin_are_enforced(client):
    no_header = client.post("/api/projects", json={"name": "x"}, headers={"X-Revive-Request": ""})
    assert no_header.status_code == 403
    cross = client.post("/api/projects", json={"name": "x"}, headers={"Origin": "http://evil.example"})
    assert cross.status_code == 403
    same = client.post("/api/projects", json={"name": "x"}, headers={"Origin": "http://testserver"})
    assert same.status_code == 200


def test_security_headers_and_no_docs(client):
    r = client.get("/")
    csp = r.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp and "unsafe-eval" not in csp
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]   # scripts: self + hashes only
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert client.get("/api/projects").headers["cache-control"] == "no-store"
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404


def test_session_cookie_flags_and_logout():
    with anon() as c:
        r = c.post("/api/auth/register", json={"company": "Cookie Co", "name": "A", "email": "cookie@example.com",
                                               "password": PASSWORD})
        sc = r.headers["set-cookie"].lower()
        assert "httponly" in sc and "samesite=lax" in sc
        assert c.get("/api/auth/me").status_code == 200
        c.post("/api/auth/logout")
        assert c.get("/api/auth/me").status_code == 401


def test_passwords_are_hashed_and_policy_applies():
    h = auth.hash_password("a-long-passphrase-1")
    assert h.startswith("scrypt$") and "a-long-passphrase-1" not in h
    assert auth.verify_password("a-long-passphrase-1", h) and not auth.verify_password("wrong-passphrase-1", h)
    with anon() as c:
        weak = c.post("/api/auth/register", json={"company": "Weak", "name": "A", "email": "weak@example.com",
                                                  "password": "short"})
        assert weak.status_code == 400


def test_login_is_throttled():
    with anon() as c:
        c.post("/api/auth/register", json={"company": "Brute", "name": "A", "email": "brute@example.com",
                                           "password": PASSWORD})
        c.post("/api/auth/logout")
        codes = [c.post("/api/auth/login", json={"email": "brute@example.com", "password": f"wrong-{i}-xxxxx"}).status_code
                 for i in range(7)]
        assert codes[:5] == [401] * 5 and codes[-1] == 429
        # even the right password is refused while the e-mail is locked
        assert c.post("/api/auth/login", json={"email": "brute@example.com", "password": PASSWORD}).status_code == 429


def test_only_admins_delete_projects_or_manage_the_team(client):
    proj = new_project(client, "Keep me")
    r = client.post("/api/team", json={"name": "Site PM", "email": "pm-" + client.email, "password": PASSWORD})
    assert r.status_code == 200
    LIMITER.hits.clear()
    m = TestClient(app, headers={"X-Revive-Request": "1"})
    m.__enter__()
    assert m.post("/api/auth/login", json={"email": "pm-" + client.email, "password": PASSWORD}).status_code == 200
    assert m.get(f"/api/projects/{proj['id']}").status_code == 200          # same company: can read
    assert m.delete(f"/api/projects/{proj['id']}").status_code == 403        # member: cannot delete
    assert m.post("/api/team", json={"name": "X", "email": "x@example.com", "password": PASSWORD}).status_code == 403
    m.__exit__(None, None, None)


def test_uploads_are_typed_and_size_limited(client, monkeypatch):
    proj = new_project(client, "Uploads")
    h = {"X-Revive-Project": str(proj["id"])}
    fake = client.post("/api/bim/upload", headers=h, files={"file": ("model.ifc", b"<html>not ifc</html>", "text/plain")})
    assert fake.status_code == 400
    assert client.post("/api/bim/upload", files={"file": ("m.ifc", b"ISO-10303-21;", "text/plain")}).status_code == 400
    from revive import security
    monkeypatch.setattr(security, "upload_limit_bytes", lambda kind: 1000)
    import revive.server as srv
    monkeypatch.setattr(srv, "upload_limit_bytes", lambda kind: 1000)
    big = client.post("/api/bim/upload", headers=h, files={"file": ("model.ifc", b"ISO-10303-21;" + b"x" * 300000, "text/plain")})
    assert big.status_code == 413


def test_bodies_are_bounded_and_validated(client):
    huge = {"inputs": {f"k{i}": "x" for i in range(5000)}}
    assert client.post("/api/predict", json=huge).status_code in (413, 422)
    assert client.get("/api/weather", params={"lat": 999, "lon": 0}).status_code in (400, 422)
    assert client.post("/api/recovery", json={"time_overrun_pct": 1e9}).status_code == 422
    unknown = client.post("/api/predict", json={"inputs": {"__proto__": "x", "province": "Punjab"}, "gate": "G25"})
    assert unknown.status_code == 200                                         # unknown keys are dropped, not used


def test_ifc_export_is_throttled_and_reuses_one_file(client):
    import os

    proj = new_project(client, "Export")
    h = {"X-Revive-Project": str(proj["id"])}
    client.post("/api/bim/demo", json={}, headers=h)
    body = {"gate": "G25", "time_overrun_pct": 40, "high_risk_probability": 0.6}
    # a signed-in user cannot write an unbounded pile of IFC copies: the folder keeps one file, and the rate is capped
    first = client.post("/api/bim/export", json=body, headers=h)
    assert first.status_code == 200 and first.headers["content-type"] == "application/x-step"
    from revive.config import workspace_dir
    exports = workspace_dir(client.user["company_id"], proj["id"]) / "exports"
    for _ in range(5):
        client.post("/api/bim/export", json=body, headers=h)
    assert len([f for f in os.listdir(exports) if f.endswith(".ifc")]) == 1
    codes = {client.post("/api/bim/export", json=body, headers=h).status_code for _ in range(30)}
    assert 429 in codes


def test_registration_can_be_closed(monkeypatch):
    from revive import security
    monkeypatch.setattr(security, "sec_cfg", lambda: {"allow_registration": False})
    import revive.server as srv
    monkeypatch.setattr(srv, "sec_cfg", lambda: {"allow_registration": False})
    with anon() as c:
        r = c.post("/api/auth/register", json={"company": "Closed", "name": "A", "email": "closed@example.com",
                                               "password": PASSWORD})
        assert r.status_code == 403
