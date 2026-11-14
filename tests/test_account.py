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
    api = anon.get("/api/no-such-thing", headers={"Accept": "text/html"})
    assert api.status_code == 404 and api.json()["detail"] == "Not Found"
