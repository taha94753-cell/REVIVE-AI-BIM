"""
HTTP hardening for REVIVE. Pure ASGI middleware, so it never buffers the live event stream.

  SecurityHeaders   CSP (scripts only from this server, inline scripts allowed by hash only), no framing,
                    nosniff, strict referrer policy, no-store on API answers, HSTS when served over HTTPS.
  CsrfGuard         every state-changing /api request must carry the X-Revive-Request header (a cross-site
                    form cannot set it, and a cross-site fetch needs CORS, which REVIVE never grants) and,
                    when the browser sends an Origin, it must be this server.
  BodyLimit         JSON bodies are capped (security.max_json_kb); uploads have their own caps.
  RateLimiter       sliding-window counters for logins, sign-ups, phone updates and heavy endpoints.
"""
from __future__ import annotations

import base64
import hashlib
import re
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from .config import load_config

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = b"x-revive-request"


def sec_cfg() -> dict:
    return load_config().get("security") or {}


# ------------------------------------------------------------------ CSP
_INLINE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)


def inline_script_hashes(pages: list[Path]) -> list[str]:
    """sha256 sources for every inline <script> (the import map) in the pages REVIVE serves."""
    out = set()
    for p in pages:
        if p.exists():
            for body in _INLINE.findall(p.read_text(encoding="utf-8")):
                out.add("'sha256-" + base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode() + "'")
    return sorted(out)


def embed_origins() -> list[str]:
    """Sites allowed to show REVIVE inside a frame (security.embed_origins, or REVIVE_EMBED_ORIGINS separated by
    spaces). Empty everywhere except a hosted demo such as a Hugging Face Space, whose page frames the app."""
    import os
    env = os.environ.get("REVIVE_EMBED_ORIGINS")
    raw = env.split() if env is not None else (load_config().get("security", {}).get("embed_origins") or [])
    return [o.rstrip("/") for o in raw if re.fullmatch(r"https://[A-Za-z0-9.-]+(:\d+)?/?", o)]


def build_csp(script_hashes: list[str], frame_origins: list[str] | None = None) -> str:
    frames = "frame-ancestors 'self' " + " ".join(frame_origins) if frame_origins else "frame-ancestors 'none'"
    return "; ".join([
        "default-src 'self'",
        "script-src 'self' " + " ".join(script_hashes),
        "style-src 'self' 'unsafe-inline'",          # SVG charts colour marks with inline style attributes
        "img-src 'self' data: blob:",
        "font-src 'self'",
        "connect-src 'self'",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        frames,
    ])


class SecurityHeaders:
    def __init__(self, app, csp: str, framable: bool = False):
        self.app, self.csp, self.framable = app, csp.encode(), framable

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        https = scope.get("scheme") == "https"

        async def send_h(msg):
            if msg["type"] == "http.response.start":
                h = [(k, v) for k, v in msg.get("headers", []) if k.lower() not in (b"server",)]
                names = {k.lower() for k, _ in h}
                add = [(b"x-content-type-options", b"nosniff"),
                       (b"referrer-policy", b"no-referrer" if path.startswith(("/site", "/auth/link")) else b"same-origin"),
                       (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
                       (b"cross-origin-opener-policy", b"same-origin"),
                       (b"cross-origin-resource-policy", b"same-origin")]
                if not self.framable:          # embedding allowed only for the origins in the CSP frame-ancestors
                    add.append((b"x-frame-options", b"DENY"))
                if b"content-security-policy" not in names:
                    add.append((b"content-security-policy", self.csp))
                if (path.startswith("/api/") or path.startswith("/auth/")) and b"cache-control" not in names:
                    add.append((b"cache-control", b"no-store"))
                if https:
                    add.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                msg = {**msg, "headers": h + add}
            await send(msg)
        return await self.app(scope, receive, send_h)


# ------------------------------------------------------------------ CSRF
def _header(scope, name: bytes) -> str | None:
    for k, v in scope.get("headers", []):
        if k.lower() == name:
            return v.decode("latin-1")
    return None


async def _deny(send, status: int, detail: str):
    import json
    body = json.dumps({"detail": detail}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class CsrfGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] in UNSAFE and scope.get("path", "").startswith("/api/"):
            if _header(scope, CSRF_HEADER) != "1":
                return await _deny(send, 403, "Request blocked: missing the REVIVE request header (CSRF protection).")
            origin = _header(scope, b"origin")
            host = _header(scope, b"host")
            if origin and origin != "null" and host:
                o = re.sub(r"^https?://", "", origin.rstrip("/")).lower()
                # Behind a forwarding proxy (GitHub Codespaces, a Cloudflare tunnel) Host is the local address and
                # the public one arrives as X-Forwarded-Host. Accepting it is safe: a page on another site cannot
                # send it (or the REVIVE header above) without a CORS preflight, which this app never grants.
                fwd = (_header(scope, b"x-forwarded-host") or "").split(",")[0].strip().lower()
                if o not in {host.lower(), fwd}:
                    return await _deny(send, 403, "Request blocked: it came from another website (CSRF protection).")
        return await self.app(scope, receive, send)


# ------------------------------------------------------------------ body size
def upload_limit_bytes(kind: str) -> int:
    c = sec_cfg()
    mb = c.get("max_ifc_mb", 150) if kind == "ifc" else c.get("max_schedule_mb", 20)
    return int(float(mb) * 1024 * 1024)


class BodyLimit:
    """Rejects oversized bodies early (Content-Length) and while streaming (chunked uploads)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in UNSAFE:
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if path.endswith("/bim/upload"):
            limit = upload_limit_bytes("ifc") + 64 * 1024
        elif path.endswith("/schedule/upload"):
            limit = upload_limit_bytes("schedule") + 64 * 1024
        else:
            limit = int(sec_cfg().get("max_json_kb", 1024)) * 1024
        declared = _header(scope, b"content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            return await _deny(send, 413, f"Request too large (limit {limit // (1024 * 1024) or 1} MB).")
        seen = 0

        async def recv():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > limit:
                    raise TooLarge()
            return msg
        try:
            return await self.app(scope, recv, send)
        except TooLarge:
            return await _deny(send, 413, "Request too large.")


class TooLarge(Exception):
    pass


# ------------------------------------------------------------------ rate limiting
class RateLimiter:
    """In-process sliding window (REVIVE runs one worker). key -> timestamps of recent hits."""

    def __init__(self):
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def hit(self, key: str, limit: int, window_s: float) -> bool:
        """Record a hit; False when the key is over its limit."""
        now = time.time()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self.hits) > 20000:          # never let the table grow without bound
                for k in [k for k, v in self.hits.items() if not v or now - v[-1] > 3600][:5000]:
                    self.hits.pop(k, None)
            return True

    def count(self, key: str, window_s: float) -> int:
        now = time.time()
        with self.lock:
            return sum(1 for t in self.hits.get(key, ()) if now - t <= window_s)

    def clear(self, key: str) -> None:
        with self.lock:
            self.hits.pop(key, None)


LIMITER = RateLimiter()


def limit(name: str, default: int) -> int:
    return int((sec_cfg().get("rate_limits") or {}).get(name, default))
