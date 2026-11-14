"""
Company workspaces: each company registers once, its users sign in, and every project,
assessment, upload and live monitor is tied to that company.

Security choices (each one can be defended):
  * Passwords: scrypt (memory-hard KDF from the Python standard library), per-user random salt,
    parameters stored with the hash so they can be raised later. Never stored or logged in clear.
  * Sessions: 256-bit random token in an HttpOnly, SameSite=Lax cookie; only its SHA-256 is stored,
    so a copied database does not hand out live sessions. The cookie lasts until the browser closes, and the
    server ends a session after security.session_idle_minutes without a request or security.session_hours in all.
  * E-mail codes (sign-up and password reset): six digits, stored only as SHA-256 bound to the e-mail and the
    purpose, valid for security.code_minutes, dropped after five wrong tries.
  * Roles: "admin" (manages the team, deletes projects) and "member".
  * Login throttling lives in security.py (per IP and per e-mail).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
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
CREATE TABLE IF NOT EXISTS email_codes (email TEXT NOT NULL, purpose TEXT NOT NULL, code_hash TEXT NOT NULL,
  payload TEXT, created_at REAL NOT NULL, expires_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (email, purpose));
"""

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,24}$")
MIN_PASSWORD = 10
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
MAX_CODE_TRIES = 5
COMMON_PASSWORDS = {"password123", "password1234", "passwordpassword", "qwertyuiop", "qwertyuiop123", "qwerty123456",
                    "iloveyou123", "1q2w3e4r5t", "1q2w3e4r5t6y", "letmein12345", "welcome12345", "administrator",
                    "adminadmin", "admin123456", "abcdefghij", "abc123abc123", "changeme123", "pakistan123"}


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
    if len(set(password)) < 4 or password.lower() in COMMON_PASSWORDS or password.isdigit():
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
EMAIL_TAKEN = "This email is already registered. Sign in, or use Forgot password."


def register_company(company: str, name: str, email: str, password: str | None, pw_hash: str | None = None) -> dict:
    """Pass the password, or pw_hash for a sign-up whose password was checked and hashed before the e-mail code."""
    company, name, email = _clean_name(company, "company name"), _clean_name(name, "your name", 80), norm_email(email)
    if pw_hash is None:
        check_password_policy(password, email)
        pw_hash = hash_password(password)
    with _conn() as c:
        if c.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise AuthError(EMAIL_TAKEN)
        base, slug, i = _slug(company), _slug(company), 1
        while c.execute("SELECT 1 FROM companies WHERE slug = ?", (slug,)).fetchone():
            i += 1
            slug = f"{base}-{i}"
        cid = c.execute("INSERT INTO companies (name, slug, created_at) VALUES (?,?,?)",
                        (company, slug, _now())).lastrowid
        uid = c.execute("INSERT INTO users (company_id, email, name, pw_hash, role, created_at) VALUES (?,?,?,?,?,?)",
                        (cid, email, name, pw_hash, "admin", _now())).lastrowid
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


def check_account_removal(user_id: int, password: str) -> dict:
    """Who is leaving and what goes with them. Raises AuthError on a wrong password, or when the only admin
    would leave other people in a company nobody can manage."""
    with _conn() as c:
        r = c.execute("SELECT id, company_id, role, pw_hash FROM users WHERE id = ?", (int(user_id),)).fetchone()
        if not r or not verify_password(password or "", r["pw_hash"]):
            raise AuthError("That password is not right.")
        people = c.execute("SELECT COUNT(*) FROM users WHERE company_id = ?", (r["company_id"],)).fetchone()[0]
        admins_n = c.execute("SELECT COUNT(*) FROM users WHERE company_id = ? AND role = 'admin'",
                             (r["company_id"],)).fetchone()[0]
    if r["role"] == "admin" and admins_n <= 1 and people > 1:
        raise AuthError("You are the only admin. Add another admin, or remove the other people in Team and access, "
                        "before deleting your account.")
    return {"company_id": r["company_id"], "last_person": people <= 1}


def delete_user(user_id: int, with_company: int | None = None) -> None:
    """Remove the user and every session; with_company also removes the (now empty) company record."""
    with _conn() as c:
        row = c.execute("SELECT email FROM users WHERE id = ?", (int(user_id),)).fetchone()
        c.execute("DELETE FROM sessions WHERE user_id = ?", (int(user_id),))
        c.execute("DELETE FROM admin_links WHERE user_id = ?", (int(user_id),))
        if row:
            c.execute("DELETE FROM email_codes WHERE email = ?", (row["email"],))
        c.execute("DELETE FROM users WHERE id = ?", (int(user_id),))
        if with_company is not None and not c.execute("SELECT 1 FROM users WHERE company_id = ?",
                                                       (int(with_company),)).fetchone():
            c.execute("DELETE FROM companies WHERE id = ?", (int(with_company),))


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


def _sec(key: str, default: float) -> float:
    return float((load_config().get("security") or {}).get(key, default))


def create_session(user_id: int, ip: str | None = None) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        c.execute("INSERT INTO sessions (id, user_id, created_at, expires_at, last_seen, ip) VALUES (?,?,?,?,?,?)",
                  (_token_id(token), int(user_id), now, now + _sec("session_hours", 12) * 3600, now, (ip or "")[:64]))
    return token


def session_user(token: str | None) -> dict | None:
    if not token or len(token) > 128:
        return None
    now = time.time()
    with _conn() as c:
        r = c.execute("SELECT user_id, expires_at, last_seen FROM sessions WHERE id = ?", (_token_id(token),)).fetchone()
        if not r or r["expires_at"] < now or now - (r["last_seen"] or now) > _sec("session_idle_minutes", 30) * 60:
            if r:
                c.execute("DELETE FROM sessions WHERE id = ?", (_token_id(token),))
            return None
        if now - (r["last_seen"] or 0) > 300:
            c.execute("UPDATE sessions SET last_seen = ? WHERE id = ?", (now, _token_id(token)))
    return get_user(r["user_id"])


def end_session(token: str | None) -> None:
    if token:
        with _conn() as c:
            c.execute("DELETE FROM sessions WHERE id = ?", (_token_id(token),))


# ------------------------------------------------------------------ e-mail codes (sign-up, password reset)
def _code_hash(email: str, purpose: str, code: str) -> str:
    return hashlib.sha256(f"{purpose}:{email}:{code}".encode("utf-8")).hexdigest()


def code_minutes() -> int:
    return int(_sec("code_minutes", 10))


def _issue_code(c, email: str, purpose: str, payload: dict | None) -> str:
    code, now = f"{secrets.randbelow(10 ** 6):06d}", time.time()
    c.execute("DELETE FROM email_codes WHERE expires_at < ?", (now,))
    c.execute("INSERT OR REPLACE INTO email_codes (email, purpose, code_hash, payload, created_at, expires_at, attempts) "
              "VALUES (?,?,?,?,?,?,0)", (email, purpose, _code_hash(email, purpose, code),
                                         json.dumps(payload) if payload else None, now, now + code_minutes() * 60))
    return code


def _redeem_code(email: str, purpose: str, code: str) -> dict:
    """The stored payload if the code is right; AuthError otherwise. A code is single use and dies after five misses."""
    bad = AuthError("That code is not right or has expired. Ask for a new one.")
    with _conn() as c:
        r = c.execute("SELECT code_hash, payload, expires_at, attempts FROM email_codes WHERE email = ? AND purpose = ?",
                      (email, purpose)).fetchone()
        if not r or r["expires_at"] < time.time():
            raise bad
        if not hmac.compare_digest(r["code_hash"], _code_hash(email, purpose, (code or "").strip())):
            if r["attempts"] + 1 >= MAX_CODE_TRIES:
                c.execute("DELETE FROM email_codes WHERE email = ? AND purpose = ?", (email, purpose))
            else:
                c.execute("UPDATE email_codes SET attempts = attempts + 1 WHERE email = ? AND purpose = ?", (email, purpose))
            c.commit()            # the miss must be counted even though this request ends in an error
            raise bad
        if c.execute("DELETE FROM email_codes WHERE email = ? AND purpose = ? AND code_hash = ?",
                     (email, purpose, r["code_hash"])).rowcount != 1:
            raise bad             # two requests raced for the same code: only one wins
    return json.loads(r["payload"]) if r["payload"] else {}


def start_signup(company: str, name: str, email: str, password: str) -> tuple[str, str]:
    """Check everything, park the sign-up (password already hashed) and return (email, code). No account exists yet."""
    company, name, email = _clean_name(company, "company name"), _clean_name(name, "your name", 80), norm_email(email)
    check_password_policy(password, email)
    with _conn() as c:
        if c.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise AuthError(EMAIL_TAKEN)
        return email, _issue_code(c, email, "signup", {"company": company, "name": name, "pw_hash": hash_password(password)})


def resend_signup(email: str) -> str | None:
    """A fresh code for a parked sign-up, or None when there is none to resend."""
    email = (email or "").strip().lower()
    with _conn() as c:
        r = c.execute("SELECT payload FROM email_codes WHERE email = ? AND purpose = 'signup'", (email,)).fetchone()
        return _issue_code(c, email, "signup", json.loads(r["payload"])) if r else None


def finish_signup(email: str, code: str) -> dict:
    email = (email or "").strip().lower()
    p = _redeem_code(email, "signup", code)
    return register_company(p["company"], p["name"], email, None, pw_hash=p["pw_hash"])


def start_reset(email: str) -> str | None:
    """A reset code if the e-mail has an account; None otherwise (the caller answers the same either way)."""
    email = (email or "").strip().lower()
    with _conn() as c:
        if not c.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            return None
        return _issue_code(c, email, "reset", None)


def finish_reset(email: str, code: str, password: str) -> None:
    email = (email or "").strip().lower()
    check_password_policy(password, email)      # before the code is spent, so a weak password does not burn it
    _redeem_code(email, "reset", code)
    u = user_by_email(email)
    if u:
        set_password(u["id"], password)         # also signs the user out everywhere


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
