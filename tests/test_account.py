"""Sign-up with an e-mail code, forgotten passwords, session-only sign-in and the public pages."""
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from conftest import PASSWORD
from revive import auth, mailer
from revive.security import LIMITER


@pytest.fixture
def anon():
    from revive.server import app
    LIMITER.hits.clear()
    with TestClient(app, headers={"X-Revive-Request": "1"}) as c:
        yield c


@pytest.fixture
def inbox(monkeypatch):
    """E-mail codes switched on, with the outgoing mail caught instead of sent: {address: latest code}."""
    monkeypatch.setenv("REVIVE_EMAIL_VERIFICATION", "1")
    codes = {}
    monkeypatch.setattr(mailer, "send_code", lambda to, code, purpose, minutes: codes.__setitem__(to, code) or "email")
    return codes


def _signup(c, tag=None):
    email = f"otp-{tag or uuid.uuid4().hex[:8]}@example.com"
    r = c.post("/api/auth/register", json={"company": "OTP Co", "name": "Ada", "email": email, "password": PASSWORD})
    return email, r


def test_signup_needs_the_emailed_code(anon, inbox):
    email, r = _signup(anon)
    assert r.status_code == 200 and r.json()["verify"] is True and "set-cookie" not in r.headers
    assert anon.get("/api/auth/me").status_code == 401                 # no account, no session yet
    assert auth.user_by_email(email) is None
    code = inbox[email]
    assert len(code) == 6 and code.isdigit()
    wrong = "000000" if code != "000000" else "111111"
    assert anon.post("/api/auth/verify", json={"email": email, "code": wrong}).status_code == 400
    r = anon.post("/api/auth/verify", json={"email": email, "code": code})
    assert r.status_code == 200 and r.json()["user"]["email"] == email and r.json()["user"]["role"] == "admin"
    assert anon.get("/api/auth/me").status_code == 200
    assert anon.post("/api/auth/verify", json={"email": email, "code": code}).status_code == 400   # single use


def test_code_dies_after_five_wrong_tries_and_a_resend_replaces_it(anon, inbox):
    email, _ = _signup(anon)
    first = inbox[email]
    wrong = "000000" if first != "000000" else "111111"
    for _ in range(auth.MAX_CODE_TRIES):
        assert anon.post("/api/auth/verify", json={"email": email, "code": wrong}).status_code == 400
    assert anon.post("/api/auth/verify", json={"email": email, "code": first}).status_code == 400   # burnt
    email2, _ = _signup(anon)
    old = inbox[email2]
    assert anon.post("/api/auth/resend", json={"email": email2}).status_code == 200
    new = inbox[email2]
    if new != old:
        assert anon.post("/api/auth/verify", json={"email": email2, "code": old}).status_code == 400
    assert anon.post("/api/auth/verify", json={"email": email2, "code": new}).status_code == 200


def test_expired_code_is_refused(anon, inbox, monkeypatch):
    email, _ = _signup(anon)
    real = time.time
    monkeypatch.setattr(auth.time, "time", lambda: real() + auth.code_minutes() * 60 + 5)
    assert anon.post("/api/auth/verify", json={"email": email, "code": inbox[email]}).status_code == 400


def test_registered_email_is_reported_and_weak_passwords_refused(anon, inbox):
    email, _ = _signup(anon)
    anon.post("/api/auth/verify", json={"email": email, "code": inbox[email]})
    anon.post("/api/auth/logout")
    r = anon.post("/api/auth/register", json={"company": "Again", "name": "B", "email": email, "password": PASSWORD})
    assert r.status_code == 400 and "already registered" in r.json()["detail"]
    for weak in ("password123", "12345678901234", "short"):
        r = anon.post("/api/auth/register", json={"company": "W", "name": "B", "email": "w@example.com", "password": weak})
        assert r.status_code == 400


def test_honeypot_field_gets_a_fake_success(anon, inbox):
    r = anon.post("/api/auth/register", json={"company": "Bot", "name": "Bot", "email": "bot@example.com",
                                              "password": PASSWORD, "website": "http://spam.example"})
    assert r.status_code == 200 and r.json()["verify"] is True
    assert "bot@example.com" not in inbox and auth.resend_signup("bot@example.com") is None


def test_forgot_password_resets_and_signs_out_everywhere(anon, inbox):
    email, _ = _signup(anon)
    anon.post("/api/auth/verify", json={"email": email, "code": inbox.pop(email)})
    assert anon.get("/api/auth/me").status_code == 200
    # the answer is the same for a stranger's address, and nothing is sent to it
    unknown = anon.post("/api/auth/forgot", json={"email": "nobody@example.com"})
    known = anon.post("/api/auth/forgot", json={"email": email})
    assert unknown.status_code == known.status_code == 200 and unknown.json() == known.json()
    assert "nobody@example.com" not in inbox
    code, new = inbox[email], "another-long-passphrase-7"
    weak = anon.post("/api/auth/reset", json={"email": email, "code": code, "password": "short"})
    assert weak.status_code == 400                                     # and the code survives a weak password
    assert anon.post("/api/auth/reset", json={"email": email, "code": code, "password": new}).status_code == 200
    assert anon.get("/api/auth/me").status_code == 401                 # every session ended
    assert anon.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401
    assert anon.post("/api/auth/login", json={"email": email, "password": new}).status_code == 200
    assert anon.post("/api/auth/reset", json={"email": email, "code": code, "password": PASSWORD}).status_code == 400


def test_codes_are_rate_limited(anon, inbox):
    email, _ = _signup(anon)
    sent = [anon.post("/api/auth/resend", json={"email": email}).status_code for _ in range(5)]
    assert 429 in sent


def test_sign_in_ends_with_the_browser_and_after_idle_time(client, monkeypatch):
    r = client.post("/api/auth/login", json={"email": client.email, "password": PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "max-age" not in cookie and "expires" not in cookie and "httponly" in cookie   # a session cookie
    assert client.get("/api/auth/me").status_code == 200
    real = time.time
    monkeypatch.setattr(auth.time, "time", lambda: real() + 31 * 60)   # the app was closed for half an hour
    assert client.get("/api/auth/me").status_code == 401


def test_trusted_proxy_sets_secure_cookie_and_hsts_only_when_switched_on(anon, monkeypatch):
    fwd = {"X-Forwarded-Proto": "https", "X-Forwarded-For": "203.0.113.9, 198.51.100.7"}
    r = anon.get("/", headers=fwd)
    assert "strict-transport-security" not in r.headers               # off by default: the headers are not believed
    monkeypatch.setenv("REVIVE_TRUST_PROXY", "1")
    r = anon.get("/", headers=fwd)
    assert "strict-transport-security" in r.headers
    email = f"px-{uuid.uuid4().hex[:8]}@example.com"
    r = anon.post("/api/auth/register", headers=fwd, json={"company": "Px", "name": "P", "email": email, "password": PASSWORD})
    assert "secure" in r.headers["set-cookie"].lower()
    from revive.security import client_addr
    assert client_addr({"headers": [(b"x-forwarded-for", b"1.1.1.1, 198.51.100.7")], "client": ("10.0.0.1", 1)}) == "198.51.100.7"


def test_public_pages_robots_sitemap_and_404(anon):
    for path in ("/privacy", "/terms"):
        r = anon.get(path)
        assert r.status_code == 200 and "text/html" in r.headers["content-type"] and "REVIVE" in r.text
    robots = anon.get("/robots.txt")
    assert robots.status_code == 200 and "Disallow: /api/" in robots.text and "/sitemap.xml" in robots.text
    sm = anon.get("/sitemap.xml")
    assert sm.status_code == 200 and "<loc>" in sm.text and "/privacy</loc>" in sm.text
    page = anon.get("/no-such-page", headers={"Accept": "text/html"})
    assert page.status_code == 404 and "text/html" in page.headers["content-type"] and "not on the programme" in page.text
    assert page.headers["x-content-type-options"] == "nosniff"
    og = anon.get("/assets/img/og.png")                                # the share image named in og:image exists
    assert og.status_code == 200 and og.headers["cross-origin-resource-policy"] == "cross-origin"
    assert 'property="og:image" content="https://' in anon.get("/").text
    api = anon.get("/api/no-such-thing", headers={"Accept": "text/html"})
    assert api.status_code == 404 and api.json()["detail"] == "Not Found"


def _member(admin, role="member"):
    email = f"m-{uuid.uuid4().hex[:8]}@example.com"
    r = admin.post("/api/team", json={"name": "Mem", "email": email, "password": PASSWORD, "role": role})
    assert r.status_code == 200, r.text
    from revive.server import app
    c = TestClient(app, headers={"X-Revive-Request": "1"})
    assert c.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    return c, email


def test_member_deletes_only_their_own_account(client):
    from conftest import new_project
    p = new_project(client, "Stays with the team")
    m, email = _member(client)
    assert m.post("/api/auth/delete-account", json={"password": "not-the-password-1"}).status_code == 400
    assert m.get("/api/auth/me").status_code == 200                    # a wrong password changes nothing
    r = m.post("/api/auth/delete-account", json={"password": PASSWORD})
    assert r.status_code == 200 and r.json() == {"deleted": True, "workspace_deleted": False}
    assert m.get("/api/auth/me").status_code == 401 and auth.user_by_email(email) is None
    assert m.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401
    assert client.get(f"/api/projects/{p['id']}").status_code == 200   # the company and its projects are untouched


def test_only_admin_must_hand_over_before_leaving(client):
    m, _ = _member(client)
    r = client.post("/api/auth/delete-account", json={"password": PASSWORD})
    assert r.status_code == 400 and "only admin" in r.json()["detail"]
    assert client.get("/api/auth/me").status_code == 200
    _member(client, role="admin")                                      # with a second admin the first may leave
    assert client.post("/api/auth/delete-account", json={"password": PASSWORD}).json()["workspace_deleted"] is False
    assert m.get("/api/projects").status_code == 200


def test_last_person_takes_the_workspace_with_them(client, other):
    from conftest import new_project
    from revive import live, projects, store
    from revive.config import workspace_dir
    from revive.presets import PRESETS
    cid, pre = client.user["company_id"], PRESETS[0]
    p = new_project(client, "Goes with the account")
    keep = new_project(other, "Another company's project")
    hdr = {"X-Revive-Project": str(p["id"])}
    assert client.post("/api/live", json={"name": "L", "inputs": pre["inputs"], "gate": pre["gate"]}, headers=hdr).status_code == 200
    assert client.post("/api/assessments", json={"name": "a", "inputs": pre["inputs"], "gate": pre["gate"],
                                                 "project_id": p["id"]}).status_code == 200
    folder = workspace_dir(cid)
    r = client.post("/api/auth/delete-account", json={"password": PASSWORD})
    assert r.status_code == 200 and r.json()["workspace_deleted"] is True
    assert "max-age=0" in r.headers["set-cookie"].lower() and client.get("/api/auth/me").status_code == 401
    assert projects.list_for(cid) == [] and live.list_projects(cid) == [] and store.list_all(cid) == []
    assert not folder.exists() and auth.user_by_email(client.email) is None
    assert other.get(f"/api/projects/{keep['id']}").status_code == 200  # nobody else's data is touched
    # the e-mail is free again
    assert client.post("/api/auth/register", json={"company": "Back", "name": "A", "email": client.email,
                                                   "password": PASSWORD}).status_code == 200


def test_delete_account_needs_a_session_and_the_csrf_header(client):
    from revive.server import app
    with TestClient(app) as bare:
        assert bare.post("/api/auth/delete-account", json={"password": PASSWORD}).status_code == 403
    with TestClient(app, headers={"X-Revive-Request": "1"}) as nobody:
        assert nobody.post("/api/auth/delete-account", json={"password": PASSWORD}).status_code == 401
