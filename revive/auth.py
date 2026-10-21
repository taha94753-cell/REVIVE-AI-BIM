"""
Company workspaces: each company registers once, its users sign in, and every project,
assessment, upload and live monitor is tied to that company.

Security choices (each one can be defended):
  * Passwords: scrypt (memory-hard KDF from the Python standard library), per-user random salt,
    parameters stored with the hash so they can be raised later. Never stored or logged in clear.
  * Sessions: 256-bit random token in an HttpOnly, SameSite=Lax cookie; only its SHA-256 is stored,
    so a copied database does not hand out live sessions. Sessions expire (security.session_days).
  * Roles: "admin" (manages the team, deletes projects) and "member".
  * Login throttling lives in security.py (per IP and per e-mail).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime

from .config import load_config
from .db import connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER NOT NULL,
  email TEXT NOT NULL UNIQUE, name TEXT NOT NULL, pw_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'member',
  created_at TEXT NOT NULL, last_login TEXT);
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at REAL NOT NULL,
  expires_at REAL NOT NULL, last_seen REAL, ip TEXT);
CREATE INDEX IF NOT EXISTS idx_users_company ON users(company_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS admin_links (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at REAL NOT NULL,
  expires_at REAL NOT NULL, used_at REAL);
"""

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,24}$")
MIN_PASSWORD = 10
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}


class AuthError(ValueError):
    """A problem the person can fix (shown to them as-is)."""


def _conn():
    return connect(SCHEMA)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------------ passwords
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, dklen=32, **SCRYPT)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return f"scrypt${SCRYPT['n']}${SCRYPT['r']}${SCRYPT['p']}${b64(salt)}${b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), dklen=32,
                              n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = None


def _dummy_verify(password: str) -> None:
    """Spend the same time on unknown e-mails as on wrong passwords (no account enumeration by timing)."""
    global _DUMMY_HASH
    _DUMMY_HASH = _DUMMY_HASH or hash_password(secrets.token_hex(8))
    verify_password(password, _DUMMY_HASH)


def check_password_policy(password: str, email: str = "") -> None:
    if len(password or "") < MIN_PASSWORD:
        raise AuthError(f"Use a password of at least {MIN_PASSWORD} characters.")
    if len(password) > 256:
        raise AuthError("That password is too long.")
    if len(set(password)) < 4:
        raise AuthError("That password is too easy to guess.")
    local = (email or "").split("@")[0].lower()
    if local and len(local) >= 4 and local in password.lower():
        raise AuthError("Do not use your e-mail name in the password.")


def norm_email(email: str) -> str:
    e = (email or "").strip().lower()
    if not EMAIL_RE.match(e):
        raise AuthError("Enter a valid e-mail address.")
    return e


def _clean_name(s: str, field: str, max_len: int = 120) -> str:
    s = re.sub(r"[\x00-\x1f\x7f]", "", (s or "")).strip()
    if not s:
        raise AuthError(f"Enter the {field}.")
    return s[:max_len]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "company"


# ------------------------------------------------------------------ companies and users
def register_company(company: str, name: str, email: str, password: str) -> dict:
    company, name, email = _clean_name(company, "company name"), _clean_name(name, "your name", 80), norm_email(email)
    check_password_policy(password, email)
    with _conn() as c:
        if c.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise AuthError("An account with this e-mail already exists. Sign in instead.")
        base, slug, i = _slug(company), _slug(company), 1
        while c.execute("SELECT 1 FROM companies WHERE slug = ?", (slug,)).fetchone():
            i += 1
            slug = f"{base}-{i}"
        cid = c.execute("INSERT INTO companies (name, slug, created_at) VALUES (?,?,?)",
                        (company, slug, _now())).lastrowid
        uid = c.execute("INSERT INTO users (company_id, email, name, pw_hash, role, created_at) VALUES (?,?,?,?,?,?)",
                        (cid, email, name, hash_password(password), "admin", _now())).lastrowid
    return get_user(uid)


def add_member(company_id: int, name: str, email: str, password: str, role: str = "member") -> dict:
    name, email = _clean_name(name, "name", 80), norm_email(email)
    check_password_policy(password, email)
    role = role if role in ("admin", "member") else "member"
    with _conn() as c:
        if c.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise AuthError("An account with this e-mail already exists.")
        uid = c.execute("INSERT INTO users (company_id, email, name, pw_hash, role, created_at) VALUES (?,?,?,?,?,?)",
                        (int(company_id), email, name, hash_password(password), role, _now())).lastrowid
    return get_user(uid)


def remove_member(company_id: int, user_id: int) -> bool:
    with _conn() as c:
        row = c.execute("SELECT role FROM users WHERE id = ? AND company_id = ?", (int(user_id), int(company_id))).fetchone()
        if not row:
            return False
        if row["role"] == "admin" and c.execute("SELECT COUNT(*) FROM users WHERE company_id = ? AND role = 'admin'",
                                                (int(company_id),)).fetchone()[0] <= 1:
            raise AuthError("A company needs at least one admin.")
        c.execute("DELETE FROM sessions WHERE user_id = ?", (int(user_id),))
        c.execute("DELETE FROM users WHERE id = ? AND company_id = ?", (int(user_id), int(company_id)))
    return True


def set_password(user_id: int, password: str) -> None:
    u = get_user(user_id)
    if not u:
        raise AuthError("No such user.")
    check_password_policy(password, u["email"])
    with _conn() as c:
        c.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (hash_password(password), int(user_id)))
        c.execute("DELETE FROM sessions WHERE user_id = ?", (int(user_id),))   # sign out everywhere


def get_user(user_id: int) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT u.id, u.email, u.name, u.role, u.company_id, u.created_at, u.last_login, "
                      "c.name AS company_name, c.slug AS company_slug FROM users u JOIN companies c ON c.id = u.company_id "
                      "WHERE u.id = ?", (int(user_id),)).fetchone()
    return dict(r) if r else None


def user_by_email(email: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT id FROM users WHERE email = ?", ((email or "").strip().lower(),)).fetchone()
    return get_user(r["id"]) if r else None


def members(company_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT id, email, name, role, created_at, last_login FROM users WHERE company_id = ? "
                         "ORDER BY role, name", (int(company_id),)).fetchall()
    return [dict(r) for r in rows]


def company_emails(company_id: int) -> list[str]:
    return [m["email"] for m in members(company_id)]


def authenticate(email: str, password: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT id, pw_hash FROM users WHERE email = ?", ((email or "").strip().lower(),)).fetchone()
    if not r:
        _dummy_verify(password or "")
        return None
    if not verify_password(password or "", r["pw_hash"]):
        return None
    with _conn() as c:
        c.execute("UPDATE users SET last_login = ? WHERE id = ?", (_now(), r["id"]))
    return get_user(r["id"])


# ------------------------------------------------------------------ sessions
def _token_id(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_days() -> float:
    return float((load_config().get("security") or {}).get("session_days", 7))


def create_session(user_id: int, ip: str | None = None) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        c.execute("INSERT INTO sessions (id, user_id, created_at, expires_at, last_seen, ip) VALUES (?,?,?,?,?,?)",
                  (_token_id(token), int(user_id), now, now + session_days() * 86400, now, (ip or "")[:64]))
    return token


def session_user(token: str | None) -> dict | None:
    if not token or len(token) > 128:
        return None
    now = time.time()
    with _conn() as c:
        r = c.execute("SELECT user_id, expires_at, last_seen FROM sessions WHERE id = ?", (_token_id(token),)).fetchone()
        if not r or r["expires_at"] < now:
            return None
        if now - (r["last_seen"] or 0) > 300:
            c.execute("UPDATE sessions SET last_seen = ? WHERE id = ?", (now, _token_id(token)))
    return get_user(r["user_id"])


def end_session(token: str | None) -> None:
    if token:
        with _conn() as c:
            c.execute("DELETE FROM sessions WHERE id = ?", (_token_id(token),))


def company_count() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM companies").fetchone()[0]


# ------------------------------------------------------------------ one-time admin sign-in links
# Printed by `python -m revive admin-link` in the server console. Having the console is the proof of
# being the administrator, so no password is needed. Each link: 256-bit random token stored only as
# SHA-256, admins only, usable once, expires after a few minutes.
def admins() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT u.id, u.email, u.name, c.name AS company_name FROM users u JOIN companies c "
                         "ON c.id = u.company_id WHERE u.role = 'admin' ORDER BY u.id").fetchall()
    return [dict(r) for r in rows]


def create_admin_link(email: str | None = None, minutes: float = 10) -> tuple[str, dict]:
    """Returns (token, admin user). Raises AuthError if the choice of admin is missing or ambiguous."""
    pool = admins()
    if not pool:
        raise AuthError("No admin account exists yet. Create one with: python -m revive create-company "
                        "--company \"Your Co\" --name \"Your name\" --email you@company.com")
    if email:
        e = email.strip().lower()
        match = [a for a in pool if a["email"] == e]
        if not match:
            raise AuthError(f"{e} is not an admin on this server. Admins: {', '.join(a['email'] for a in pool)}")
        user = match[0]
    elif len(pool) == 1:
        user = pool[0]
    else:
        raise AuthError("Several admins exist; choose one with --email. Admins: "
                        + ", ".join(f"{a['email']} ({a['company_name']})" for a in pool))
    minutes = max(1.0, min(60.0, float(minutes)))
    token, now = secrets.token_urlsafe(32), time.time()
    with _conn() as c:
        c.execute("DELETE FROM admin_links WHERE expires_at < ? OR used_at IS NOT NULL", (now - 86400,))
        c.execute("INSERT INTO admin_links (id, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                  (_token_id(token), user["id"], now, now + minutes * 60))
    return token, get_user(user["id"])


def redeem_admin_link(token: str | None) -> dict | None:
    """Single use: the UPDATE succeeds for exactly one request, even if the link is opened twice at once."""
    if not token or len(token) > 128:
        return None
    now = time.time()
    with _conn() as c:
        r = c.execute("SELECT user_id FROM admin_links WHERE id = ?", (_token_id(token),)).fetchone()
        if not r:
            return None
        n = c.execute("UPDATE admin_links SET used_at = ? WHERE id = ? AND used_at IS NULL AND expires_at >= ?",
                      (now, _token_id(token), now)).rowcount
    if n != 1:
        return None
    u = get_user(r["user_id"])
    return u if u and u["role"] == "admin" else None
