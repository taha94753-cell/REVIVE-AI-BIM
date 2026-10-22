"""
REVIVE web server (FastAPI).

    /            public landing page
    /app         the dashboard (signed-in company users only)
    /site/<tok>  phone page for site staff (capability link, no account needed)
    /api/*       JSON API

Who can see what
  * Every /api route except ping, health, public/overview, auth/* and site/<token>/* needs a signed-in user.
  * Everything a company creates (projects, uploads, assessments, live monitors, alerts, exports)
    carries its company_id and every read filters on it. Another company's ids answer 404.
  * The dashboard says which project it is working on with the X-Revive-Project header; the server
    checks that the project belongs to the user's company and runs the request inside that
    project's scope (its own schedule and IFC model).
  * Phones reach a monitored project only through its unguessable site token, which can be revoked.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import secrets
import shutil
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, alerts, auth, delay, live, projects, store, weather
from .bim import BimModel, forget, get_bim
from .config import ROOT, load_config, workspace_dir
from .inference import get_predictor
from .insights import insights
from .pipeline import bootstrap
from .presets import PRESETS
from .recovery import element_properties, run_recovery
from .scheduling import DAYS_PER_MONTH, cpm, load_schedule
from .schema import LEAKAGE_EXCLUDED, public_schema
from .security import (LIMITER, BodyLimit, CsrfGuard, SecurityHeaders, build_csp, embed_origins, inline_script_hashes, limit,
                       sec_cfg, upload_limit_bytes)

WEB = ROOT / "web"
PAGES = {"landing": WEB / "landing.html", "app": WEB / "app.html", "site": WEB / "site.html"}
COOKIE = "revive_session"
log = logging.getLogger("revive")


def clean_json(obj: Any):
    """Make numpy types and NaN safe for JSON."""
    if isinstance(obj, dict):
        return {str(k): clean_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def ok(obj) -> JSONResponse:
    return JSONResponse(clean_json(obj))


class _QuietPolls(logging.Filter):
    """Hide heartbeat and catch-up polls from the access log; real requests still show."""
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(k in msg for k in ("/api/ping", "/updates?after=", "/presence "))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.getLogger("uvicorn.access").addFilter(_QuietPolls())
    bootstrap(verbose=True)
    get_predictor()
    yield


class StreamSafeGZip:
    """GZip for normal responses, never for Server-Sent Events (some Starlette versions buffer them)."""

    def __init__(self, app, minimum_size: int = 1000):
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].endswith("/stream"):
            return await self.app(scope, receive, send)
        return await self.gzip(scope, receive, send)


class FreshFrontend:
    """Cache-Control: no-cache on pages and scripts, so an updated app.js is always picked up."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        p = scope.get("path", "") if scope["type"] == "http" else ""
        if not (p in ("/", "/app") or p.startswith("/assets/") or p.startswith("/site/")):
            return await self.app(scope, receive, send)

        async def send_nc(msg):
            if msg["type"] == "http.response.start":
                headers = [(k, v) for k, v in msg.get("headers", []) if k.lower() != b"cache-control"]
                headers.append((b"cache-control", b"no-cache"))
                msg = {**msg, "headers": headers}
            await send(msg)
        return await self.app(scope, receive, send_nc)


_docs = bool(sec_cfg().get("api_docs")) or os.environ.get("REVIVE_API_DOCS") == "1"
app = FastAPI(title="REVIVE API", version=__version__, lifespan=lifespan,
              docs_url="/docs" if _docs else None, redoc_url=None, openapi_url="/openapi.json" if _docs else None,
              description="AI-BIM early warning, current delay analysis, explained forecasts and LP recovery.")
# added last = runs first: headers wrap everything, then CSRF, then size limits
app.add_middleware(FreshFrontend)
app.add_middleware(StreamSafeGZip, minimum_size=1000)
app.add_middleware(BodyLimit)
app.add_middleware(CsrfGuard)
EMBED = embed_origins()
app.add_middleware(SecurityHeaders, csp=build_csp(inline_script_hashes(list(PAGES.values())), EMBED), framable=bool(EMBED))


# ------------------------------------------------------------------ identity
def client_ip(request: Request) -> str:
    return (request.client.host if request.client else "unknown")[:64]


def current_user(request: Request) -> dict:
    u = auth.session_user(request.cookies.get(COOKIE))
    if not u:
        raise HTTPException(401, "Sign in to continue.")
    return u


def require_admin(user: Annotated[dict, Depends(current_user)]) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Only a company admin can do this.")
    return user


User = Annotated[dict, Depends(current_user)]
Admin = Annotated[dict, Depends(require_admin)]


def header_project(request: Request, user: dict, required: bool = False) -> dict | None:
    """The project named in X-Revive-Project, if it belongs to the user's company."""
    raw = request.headers.get("x-revive-project")
    if not raw:
        if required:
            raise HTTPException(400, "Open a project first (this action changes a project's files).")
        return None
    if not raw.isdigit():
        raise HTTPException(400, "Bad project id.")
    p = projects.get(user["company_id"], int(raw))
    if not p:
        raise HTTPException(404, "Project not found.")
    return p


def own_project(user: dict, pid: int) -> dict:
    p = projects.get(user["company_id"], pid)
    if not p:
        raise HTTPException(404, "Project not found.")
    return p


def own_live(user: dict, lid: int) -> dict:
    if live.owner(lid) != user["company_id"]:
        raise HTTPException(404, "Monitored project not found.")
    return live.get_project(lid)


def throttle(key: str, n: int, window_s: float, msg: str = "Too many requests. Wait a minute and try again."):
    if not LIMITER.hit(key, n, window_s):
        raise HTTPException(429, msg)


def _embedded_cookie(resp: Response, value: str, max_age: int) -> None:
    """Session cookie for a framed app, written by hand: Starlette only emits Partitioned on Python 3.14+.
    The token is url-safe base64, so it needs no quoting."""
    expires = "; expires=Thu, 01 Jan 1970 00:00:00 GMT" if max_age == 0 else ""
    resp.headers.append("set-cookie", f"{COOKIE}={value}; Max-Age={max_age}{expires}; Path=/; HttpOnly; Secure; "
                                      "SameSite=None; Partitioned")


def _set_cookie(request: Request, resp: Response, token: str) -> None:
    if EMBED:
        # Shown inside another site's page (e.g. a Hugging Face Space): the browser only sends the session cookie
        # from inside that frame if it is SameSite=None and Secure; Partitioned (CHIPS) keeps it per embedding site.
        _embedded_cookie(resp, token, int(auth.session_days() * 86400))
        return
    mode = str(sec_cfg().get("cookie_secure", "auto")).lower()
    secure = request.url.scheme == "https" if mode == "auto" else mode in ("true", "1", "yes")
    resp.set_cookie(COOKIE, token, max_age=int(auth.session_days() * 86400), httponly=True, secure=secure,
                    samesite="lax", path="/")


# ------------------------------------------------------------------ request bodies (bounded)
Name = Annotated[str, Field(min_length=1, max_length=120)]
Short = Annotated[str, Field(max_length=160)]
Inputs = Annotated[dict[str, Any], Field(max_length=120)]


class RegisterReq(BaseModel):
    company: Name
    name: Annotated[str, Field(min_length=1, max_length=80)]
    email: Annotated[str, Field(max_length=254)]
    password: Annotated[str, Field(max_length=256)]


class LoginReq(BaseModel):
    email: Annotated[str, Field(max_length=254)]
    password: Annotated[str, Field(max_length=256)]


class TeamAdd(RegisterReq):
    company: str | None = None
    role: Literal["admin", "member"] = "member"


class PredictRequest(BaseModel):
    inputs: Inputs
    gate: Literal["G25", "G50"] | None = None
    source_project_id: Annotated[str, Field(max_length=40)] | None = None


class RecoveryRequest(BaseModel):
    gate: Literal["G25", "G50"] = "G25"
    spi: Annotated[float, Field(ge=0.0, le=3.0)] | None = None
    time_overrun_pct: Annotated[float, Field(ge=-100, le=2000)]
    high_risk_probability: Annotated[float, Field(ge=0, le=1)] = 0.5
    ld_per_day: Annotated[float, Field(ge=0, le=1e11)] | None = None
    budget_pkr: Annotated[float, Field(ge=0, le=1e13)] | None = None
    deadline_day: Annotated[float, Field(gt=0, le=20000)] | None = None
    rework: Annotated[str, Field(max_length=60)] | None = None
    elapsed_pct: Annotated[float, Field(ge=0, le=100)] | None = None
    weather_lost_offsets: Annotated[list[Annotated[int, Field(ge=0, le=31)]], Field(max_length=40)] | None = None


class ExportRequest(RecoveryRequest):
    project_name: Annotated[str, Field(max_length=120)] = "REVIVE assessment"


class Location(BaseModel):
    name: Annotated[str, Field(max_length=60)] | None = None
    lat: Annotated[float, Field(ge=-90, le=90)]
    lon: Annotated[float, Field(ge=-180, le=180)]


class LiveCreate(BaseModel):
    name: Annotated[str, Field(max_length=120)] = ""
    inputs: Inputs
    gate: Literal["G25", "G50"] = "G25"
    location: Location | None = None


class LiveUpdate(BaseModel):
    reporter: Annotated[str, Field(max_length=60)] | None = None
    note: Annotated[str, Field(max_length=500)] | None = None
    elapsed_pct: Annotated[float, Field(ge=0, le=100)] | None = None
    spi: float | None = None
    cpi: float | None = None
    cert: Annotated[float, Field(ge=0, le=100)] | None = None
    events: Annotated[dict[Literal["late_payments", "material_events", "variations", "rfis", "weather_days"],
                           Annotated[float, Field(ge=0, le=365)]], Field(max_length=5)] = {}
    labour: Annotated[int, Field(ge=1, le=5)] | None = None
    subcontractor: Annotated[int, Field(ge=1, le=5)] | None = None
    rework: Annotated[str, Field(max_length=60)] | None = None


class SaveRequest(BaseModel):
    name: Name
    inputs: Inputs
    gate: Literal["G25", "G50"] | None = None
    result: dict[str, Any] | None = None          # ignored: the server re-scores (a client cannot forge a result)
    recovery: Annotated[dict[str, float | None], Field(max_length=10)] | None = None


class ProjectBody(BaseModel):
    name: Annotated[str, Field(max_length=120)] | None = None
    code: Annotated[str, Field(max_length=40)] | None = None
    client: Short | None = None
    location: Location | None = None
    start_date: Annotated[str, Field(max_length=10)] | None = None
    details: Annotated[dict[str, Any], Field(max_length=20)] | None = None
    inputs: Inputs | None = None
    gate: Literal["G25", "G50"] | None = None


class ProgressBody(BaseModel):
    as_of: Annotated[str, Field(max_length=10)] | None = None
    elapsed_pct: Annotated[float, Field(ge=0, le=100)] | None = None
    activities: Annotated[dict[str, Annotated[float, Field(ge=0, le=100)]], Field(max_length=2000)] = {}


class Presence(BaseModel):
    device: Annotated[str, Field(min_length=1, max_length=64)]
    label: Annotated[str, Field(max_length=40)] | None = None


# ------------------------------------------------------------------ public
@app.get("/api/ping")
def ping():
    """Cheapest liveness check: the dashboard calls it to tell 'server down' from 'request failed'."""
    return {"app": "REVIVE", "version": __version__, "status": "ok", "time": time.time()}


@app.get("/api/health")
def health():
    return {"app": "REVIVE", "version": __version__, "status": "ok"}


@app.get("/api/public/overview")
@lru_cache(maxsize=1)
def public_overview():
    """Aggregate, non-identifying facts for the landing page (cross-validated metrics and dataset shape)."""
    P = get_predictor()
    card = P.card
    comp = insights(P.dataset).get("composition", {}) if not P.dataset.empty else {}
    return clean_json({
        "projects": card.get("dataset", {}).get("n_projects"),
        "records": int(len(P.dataset)),
        "hypothetical": int(P.dataset["is_hypothetical"].astype(bool).sum()) if not P.dataset.empty else 0,
        "trained_on_hypothetical": card.get("dataset", {}).get("hypothetical"),
        "share_over_10pct": comp.get("share_over_10pct"),
        "median_time_overrun_pct": comp.get("median_time_overrun_pct"),
        "gates": {g: {"label": v.get("label"), "mae": v["time_overrun"]["mae"]["mean"],
                      "baseline_mae": v["time_overrun"]["baseline_median_mae"],
                      "r2": v["time_overrun"]["r2"]["mean"], "auc": v["high_risk"]["auc"]["mean"],
                      "loco_r2": (v.get("leave_company_out") or {}).get("time_overrun", {}).get("r2"),
                      "loco_auc": (v.get("leave_company_out") or {}).get("high_risk_auc")}
                  for g, v in card.get("gates", {}).items()},
        "registration_open": bool(sec_cfg().get("allow_registration", True)),
    })


# ------------------------------------------------------------------ auth
def _adopt_legacy(company_id: int) -> None:
    """Data saved before workspaces existed belongs to the first company that registers on this install."""
    for m in live.legacy_monitors():
        p = projects.create(company_id, None, m["name"], location=m["location"], inputs=m["base_inputs"])
        live.assign(m["id"], company_id, p["id"])
    store.adopt_legacy(company_id)


@app.post("/api/auth/register")
def register(req: RegisterReq, request: Request):
    if not sec_cfg().get("allow_registration", True):
        raise HTTPException(403, "New company sign-up is closed on this server. Ask the administrator.")
    throttle(f"register:{client_ip(request)}", limit("register_per_hour", 5), 3600,
             "Too many sign-ups from this network. Try again later.")
    try:
        first = auth.company_count() == 0
        u = auth.register_company(req.company, req.name, req.email, req.password)
    except auth.AuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    if first:
        _adopt_legacy(u["company_id"])
    resp = JSONResponse({"user": _public_user(u)})
    _set_cookie(request, resp, auth.create_session(u["id"], client_ip(request)))
    return resp


@app.post("/api/auth/login")
def login(req: LoginReq, request: Request):
    ip, em = client_ip(request), (req.email or "").strip().lower()[:254]
    if not LIMITER.hit(f"login-ip:{ip}", limit("login_per_15min", 10), 900) or \
            LIMITER.count(f"login-fail:{em}", 900) >= 5:
        raise HTTPException(429, "Too many sign-in attempts. Wait 15 minutes and try again.")
    u = auth.authenticate(em, req.password)
    if not u:
        LIMITER.hit(f"login-fail:{em}", 1000, 900)
        raise HTTPException(401, "E-mail or password is not right.")
    LIMITER.clear(f"login-fail:{em}")
    resp = JSONResponse({"user": _public_user(u)})
    _set_cookie(request, resp, auth.create_session(u["id"], ip))
    return resp


@app.post("/api/auth/logout")
def logout(request: Request):
    auth.end_session(request.cookies.get(COOKIE))
    resp = JSONResponse({"signed_out": True})
    if EMBED:   # a partitioned cookie is only removed by a cookie with the same attributes
        _embedded_cookie(resp, '""', 0)
    else:
        resp.delete_cookie(COOKIE, path="/")
    return resp


def _public_user(u: dict) -> dict:
    return {k: u[k] for k in ("id", "email", "name", "role", "company_id", "company_name")}


@app.get("/api/auth/me")
def me(user: User):
    return {"user": _public_user(user)}


@app.get("/api/team")
def team(user: User):
    return ok({"members": auth.members(user["company_id"]), "you": user["id"]})


@app.post("/api/team")
def team_add(req: TeamAdd, admin: Admin):
    try:
        u = auth.add_member(admin["company_id"], req.name, req.email, req.password, req.role)
    except auth.AuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ok(_public_user(u))


@app.delete("/api/team/{uid}")
def team_remove(uid: int, admin: Admin):
    if uid == admin["id"]:
        raise HTTPException(400, "You cannot remove yourself.")
    try:
        if not auth.remove_member(admin["company_id"], uid):
            raise HTTPException(404, "No such member.")
    except auth.AuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ok({"removed": uid})


# ------------------------------------------------------------------ model (signed-in users)
@app.get("/api/schema")
def schema(user: User):
    cfg = load_config()
    return ok({**public_schema(cfg["gates"], cfg["training"].get("feature_set", "all")), "risk_bands": cfg["risk_bands"],
               "high_risk_threshold_pct": cfg["training"]["high_risk_threshold_pct"],
               "optimizer": cfg["optimizer"], "app": cfg["app"],
               "delay_bands": (cfg.get("delay") or {}).get("bands") or delay.DEFAULT_BANDS})


@app.get("/api/model-card")
def model_card(user: User):
    P = get_predictor()
    sens = ROOT / "models" / "sensitivity.json"
    card = dict(P.card)
    if sens.exists():
        card["sensitivity"] = json.loads(sens.read_text())
    card["excluded_for_leakage"] = LEAKAGE_EXCLUDED
    return ok(card)


@app.get("/api/insights")
def get_insights(user: User):
    P = get_predictor()
    out = insights(P.dataset) if not P.dataset.empty else {}
    out["drivers"] = {g: v["global"] for g, v in P.gates.items()}
    oof = P.oof.merge(P.dataset[["project_id", "status", "is_hypothetical"]], on="project_id", how="left") \
        if not P.oof.empty and not P.dataset.empty else None
    if oof is not None:
        clip = load_config()["training"]["time_overrun_clip_pct"]
        out["oof"] = {g: [{"actual": min(r["actual_time_overrun_pct"], clip), "predicted": r[f"{g}_time"],
                           "status": r["status"], "hypothetical": bool(r["is_hypothetical"])}
                          for _, r in oof.iterrows() if not math.isnan(r["actual_time_overrun_pct"])]
                      for g in P.gates}
    return ok(out)


@app.get("/api/presets")
def presets(user: User):
    return ok(PRESETS)


@app.get("/api/portfolio")
def portfolio(user: User):
    """The anonymised benchmark dataset (what the model learned from) and this company's saved assessments."""
    return ok({"dataset": get_predictor().portfolio(), "saved": store.list_all(user["company_id"])})


@app.get("/api/benchmark/{record_id}")
def benchmark_record(record_id: str, user: User):
    inputs = get_predictor().inputs_for(record_id[:40])
    if inputs is None:
        raise HTTPException(404, "Benchmark record not found")
    return ok({"project_id": record_id, "inputs": inputs})


@app.post("/api/predict")
def predict(req: PredictRequest, user: User):
    throttle(f"predict:{user['id']}", limit("predict_per_min", 400), 60)
    try:
        return ok(get_predictor().predict(projects.clean_inputs(req.inputs), req.gate, req.source_project_id))
    except ValueError as exc:
        raise HTTPException(400, f"Could not score this project: {exc}") from exc
    except Exception as exc:
        log.exception("predict failed")
        raise HTTPException(400, "Could not score this project. Check the answers and try again.") from exc


@app.post("/api/recovery")
def recovery(req: RecoveryRequest, request: Request, user: User):
    throttle(f"recovery:{user['id']}", limit("recovery_per_min", 240), 60)
    p = header_project(request, user)
    try:
        with projects.scope(p):
            return ok(run_recovery(**req.model_dump()))
    except ValueError as exc:
        raise HTTPException(400, f"Recovery planning failed: {exc}") from exc
    except Exception as exc:
        log.exception("recovery failed")
        raise HTTPException(400, "Recovery planning failed. Check the schedule and the inputs.") from exc


# ------------------------------------------------------------------ BIM and schedule (project scope)
def _bim_summary_now() -> dict:
    acts = load_schedule()
    base = cpm(acts)
    bim = get_bim()
    q = bim.quantities(acts) if bim else None
    months = round(base["finish"] / DAYS_PER_MONTH, 1)
    autofill = {"planned_months": months}
    if q:
        autofill.update({"floor_area_m2": q.get("gross_floor_area_m2"), "storeys": q.get("storeys_above_ground")})
    from .config import active_file
    sched = active_file("schedule")
    demo = sched.resolve() == (ROOT / load_config()["bim"]["schedule_file"]).resolve()
    return {"connected": q is not None, "quantities": q,
            "schedule": {"file": "Demo schedule (schedule.csv)" if demo else "Uploaded baseline schedule",
                         "demo": demo, "activities": len(acts),
                         "planned_days": base["finish"], "planned_months": months, "critical_path": base["critical"],
                         "weather_sensitive": sum(a.is_weather_sensitive for a in acts)},
            "autofill": autofill}


@app.get("/api/bim/geometry")
def bim_geometry(request: Request, user: User):
    p = header_project(request, user)
    with projects.scope(p):
        bim = get_bim()
        if bim is None:
            return ok({"connected": False, "meshes": []})
        geom = bim.geometry()
        mapping = bim.mapping(load_schedule())
    meshes = []
    for m in geom["meshes"]:
        e = bim.elements.get(m["guid"], {})
        meshes.append({"guid": m["guid"], "verts": m["verts"], "faces": m["faces"], "name": e.get("name"),
                       "ifc_class": e.get("ifc_class"), "storey": e.get("storey"), "material": e.get("material"),
                       "activity": mapping.get(m["guid"])})
    return ok({"connected": True, "file": "model.ifc" if p and p.get("ifc_mode") == "file" else geom["file"],
               "hash": geom["hash"], "bounds": geom["bounds"], "meshes": meshes})


@app.get("/api/bim/summary")
def bim_summary(request: Request, user: User):
    p = header_project(request, user)
    with projects.scope(p):
        return ok(_bim_summary_now())


@app.get("/api/schedule")
def schedule(request: Request, user: User):
    p = header_project(request, user)
    with projects.scope(p):
        acts = load_schedule()
        base = cpm(acts)
    return ok([{"id": a.id, "name": a.name, "wbs": a.wbs, "duration": a.duration, "predecessors": a.preds,
                "trade": a.trade, "es": base["es"][a.id], "ef": base["ef"][a.id], "total_float": base["tf"][a.id],
                "critical": a.id in base["critical"]} for a in acts])


async def _receive_upload(file: UploadFile, kind: str, dest_dir: Path) -> Path:
    """Stream to a random temporary name inside the project folder, enforcing the size cap and file type."""
    limit_b = upload_limit_bytes(kind)
    tmp = dest_dir / f".upload_{secrets.token_hex(8)}{Path(file.filename or '').suffix.lower()[:8]}"
    size, head = 0, b""
    try:
        with open(tmp, "wb") as fh:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit_b:
                    raise HTTPException(413, f"File too large (limit {limit_b // (1024 * 1024)} MB).")
                if len(head) < 4096:
                    head += chunk[:4096 - len(head)]
                fh.write(chunk)
        if size == 0:
            raise HTTPException(400, "The file is empty.")
        if kind == "ifc" and b"ISO-10303-21" not in head[:2048]:
            raise HTTPException(400, "This is not an IFC (STEP) file. Export IFC from Revit and upload the .ifc file.")
        if kind == "xer" and not head.lstrip(b"\xef\xbb\xbf").startswith(b"ERMHDR"):
            raise HTTPException(400, "This is not a Primavera P6 .xer export.")
        if b"\x00" in head and kind != "ifc":
            raise HTTPException(400, "This does not look like a text schedule file.")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp


@app.post("/api/bim/upload")
async def upload_ifc(request: Request, user: User, file: UploadFile = File(...)):
    p = header_project(request, user, required=True)
    if not (file.filename or "").lower().endswith(".ifc"):
        raise HTTPException(400, "Upload an .ifc file exported from Revit or another BIM tool.")
    throttle(f"upload:{user['id']}", 20, 600)
    d = workspace_dir(user["company_id"], p["id"])
    tmp = await _receive_upload(file, "ifc", d)

    def check():
        try:
            BimModel(tmp).geometry()
        except Exception as exc:
            raise ValueError(exc.__class__.__name__) from exc
    try:
        await run_in_threadpool(check)
    except ValueError as exc:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, "This IFC file could not be read. Re-export it as IFC4 (or IFC2x3) from Revit.") from exc
    dest = projects.store_upload(user["company_id"], p["id"], "ifc", tmp, "model.ifc")
    forget(dest)
    p = projects.update(user["company_id"], p["id"], ifc_mode="file", ifc_file=str(dest))
    with projects.scope(p):
        return ok(await run_in_threadpool(_bim_summary_now))


@app.post("/api/schedule/upload")
async def upload_schedule(request: Request, user: User, file: UploadFile = File(...)):
    from .schedule_import import import_schedule
    p = header_project(request, user, required=True)
    name = (file.filename or "").lower()
    if not name.endswith((".csv", ".xer")):
        raise HTTPException(400, "Upload the baseline schedule as a Primavera P6 .xer export or a REVIVE .csv.")
    throttle(f"upload:{user['id']}", 20, 600)
    d = workspace_dir(user["company_id"], p["id"])
    tmp = await _receive_upload(file, "xer" if name.endswith(".xer") else "schedule", d)
    try:   # validate the temporary copy first: a rejected upload never touches the project's current schedule
        checked, report = await run_in_threadpool(import_schedule, tmp)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        tmp.with_suffix(".csv").unlink(missing_ok=True)
        msg = str(exc) if isinstance(exc, (ValueError, KeyError)) else exc.__class__.__name__
        raise HTTPException(400, f"Schedule rejected: {msg[:300]}") from exc
    used = d / "schedule.csv"
    shutil.move(str(checked), used)
    if tmp.exists():
        shutil.move(str(tmp), d / f"schedule_source{tmp.suffix}")
    p = projects.update(user["company_id"], p["id"], schedule_file=str(used), progress=None)
    with projects.scope(p):
        summary = await run_in_threadpool(_bim_summary_now)
    summary["import_report"] = report
    return ok(summary)


def _project_files(request: Request, user: dict, **fields) -> JSONResponse:
    p = header_project(request, user, required=True)
    if fields.get("schedule_file", "keep") is None:
        fields["progress"] = None             # progress was entered against the old schedule
    p = projects.update(user["company_id"], p["id"], **fields)
    with projects.scope(p):
        return ok(_bim_summary_now())


@app.post("/api/bim/reset")
def reset_bim(request: Request, user: User):
    """Back to the demo model and the demo schedule."""
    return _project_files(request, user, ifc_mode="demo", ifc_file=None, schedule_file=None)


@app.post("/api/schedule/reset")
def reset_schedule(request: Request, user: User):
    return _project_files(request, user, schedule_file=None)


@app.post("/api/bim/demo")
def bim_demo(request: Request, user: User):
    _ensure_demo_model()
    return _project_files(request, user, ifc_mode="demo", ifc_file=None)


@app.post("/api/bim/disconnect")
def bim_disconnect(request: Request, user: User):
    """Run on the baseline schedule and site reports alone."""
    return _project_files(request, user, ifc_mode="none")


def _ensure_demo_model():
    from .config import path as cpath
    from .sample_ifc import build
    ifc = cpath(load_config()["bim"]["ifc_file"])
    if not ifc.exists():
        build(ifc)


@app.post("/api/bim/export")
def export_ifc(req: ExportRequest, request: Request, user: User):
    throttle(f"export:{user['id']}", 30, 600)      # writing a full IFC copy is heavy, like an upload: cap it per user
    p = header_project(request, user)
    with projects.scope(p):
        if get_bim() is None:
            raise HTTPException(400, "No BIM model is connected. Upload an IFC model or use the demo model first.")
        params = req.model_dump()
        name = params.pop("project_name")
        result = run_recovery(**params, with_curve=False, simulate_risk=False)
        props = element_properties(result, {"time_overrun_pct": req.time_overrun_pct,
                                            "high_risk_probability": req.high_risk_probability}, name)
        out = workspace_dir(user["company_id"], p["id"] if p else None) / "exports"
        dest = get_bim().export_with_risk(props, name, out_dir=out)   # fixed name: one export file per project, never a growing pile
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return FileResponse(dest, media_type="application/x-step", filename=f"{dest.stem}_{stamp}.ifc")


# ------------------------------------------------------------------ company projects
def _latest_prediction(cid: int, p: dict, lid: int | None) -> tuple[dict | None, dict | None]:
    """(summary for cards, full prediction) from the live monitor, else the latest saved assessment."""
    if lid:
        lp = live.get_project(lid)
        if lp and lp.get("updates"):
            return lp["updates"][-1]["summary"], (lp.get("latest") or {}).get("prediction")
    a = store.latest_for_project(cid, p["id"])
    if a:
        r = a["result"] or {}
        return {"time_overrun_pct": r.get("time_overrun_pct"), "band": r.get("band"),
                "health": (r.get("health") or {}).get("score"), "probability": r.get("high_risk_probability"),
                "gate": r.get("gate"), "at": a["created_at"]}, r
    return None, None


_DELAY_CACHE: dict = {}


def _delay_for(user_cid: int, p: dict, full: bool = True) -> dict:
    lid = live.for_project(user_cid, p["id"])
    lp = live.get_project(lid) if lid else None
    sts = live.states(lid) if lid else None
    summ, pred = _latest_prediction(user_cid, p, lid)
    last_upd = lp["updates"][-1]["id"] if lp and lp.get("updates") else None
    key = (p["id"], p.get("updated_at"), last_upd, (summ or {}).get("at"))
    if not full and key in _DELAY_CACHE:
        return _DELAY_CACHE[key]
    with projects.scope(p):
        out = delay.analyse(p, lp, sts, ml_overrun_pct=(pred or {}).get("time_overrun_pct"))
    out["live_id"] = lid
    if len(_DELAY_CACHE) > 500:
        _DELAY_CACHE.clear()
    _DELAY_CACHE[key] = out
    return out


def _project_public(user: dict, p: dict, with_status: bool = True) -> dict:
    lid = live.for_project(user["company_id"], p["id"])
    out = {k: p[k] for k in ("id", "name", "code", "client", "location", "start_date", "details", "gate",
                             "created_at", "updated_at", "ifc_mode")}
    out["has_inputs"] = bool(p.get("inputs"))
    out["schedule"] = "uploaded" if p.get("schedule_file") else "demo"
    out["live_id"] = lid
    out["has_progress"] = bool(p.get("progress"))
    if with_status:
        summ, _ = _latest_prediction(user["company_id"], p, lid)
        out["forecast"] = summ
        try:
            d = _delay_for(user["company_id"], p, full=False)
            out["delay"] = {k: d.get(k) for k in ("available", "delay_days", "delay_band", "spi_t", "status_date", "source")}
            if d.get("available"):
                out["delay"]["history"] = [round(-w["sv_t"], 1) for w in d.get("windows", [])][-12:]
        except Exception:
            log.exception("delay summary failed for project %s", p["id"])
            out["delay"] = {"available": False}
    return out


@app.get("/api/projects")
def list_projects(user: User):
    return ok([_project_public(user, p) for p in projects.list_for(user["company_id"])])


@app.post("/api/projects")
def create_project(req: ProjectBody, user: User):
    if not req.name:
        raise HTTPException(400, "Give the project a name.")
    throttle(f"create:{user['company_id']}", 60, 3600)
    loc = req.location.model_dump() if req.location else None
    if not loc:
        prov = (req.details or {}).get("province") or (req.inputs or {}).get("province")
        loc = weather.place(None, prov)
    try:
        p = projects.create(user["company_id"], user["id"], req.name, code=req.code, client=req.client, location=loc,
                            start_date=req.start_date, details=req.details, inputs=req.inputs, gate=req.gate)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ok(_project_public(user, p))


@app.get("/api/projects/{pid}")
def get_project(pid: int, request: Request, user: User):
    p = own_project(user, pid)
    out = _project_public(user, p)
    out["inputs"] = p.get("inputs")
    out["progress"] = p.get("progress")
    if out["live_id"]:
        lp = live.get_project(out["live_id"])
        out["site_url"] = _site_url(request, lp["site_token"])
    return ok(out)


@app.patch("/api/projects/{pid}")
def patch_project(pid: int, req: ProjectBody, user: User):
    own_project(user, pid)
    body = req.model_dump(exclude_unset=True)
    if body.get("location"):
        body["location"] = req.location.model_dump()
    try:
        p = projects.update(user["company_id"], pid, **body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ok(_project_public(user, p))


@app.delete("/api/projects/{pid}")
def delete_project(pid: int, admin: Admin):
    if not projects.delete(admin["company_id"], pid):
        raise HTTPException(404, "Project not found.")
    return ok({"deleted": pid})


@app.get("/api/projects/{pid}/delay")
def project_delay(pid: int, user: User):
    p = own_project(user, pid)
    try:
        return ok(_delay_for(user["company_id"], p, full=True))
    except ValueError as exc:
        raise HTTPException(400, f"Delay analysis failed: {exc}") from exc


@app.get("/api/projects/{pid}/activities")
def project_activities(pid: int, user: User):
    """Baseline activities with planned dates, for the activity-progress editor."""
    p = own_project(user, pid)
    with projects.scope(p):
        acts = load_schedule()
        base = cpm(acts)
    prog = (p.get("progress") or {}).get("activities") or {}
    return ok({"planned_days": base["finish"], "progress": p.get("progress"),
               "activities": [{"id": a.id, "name": a.name, "trade": a.trade, "duration": a.duration,
                               "es": base["es"][a.id], "ef": base["ef"][a.id], "critical": a.id in base["critical"],
                               "pct": prog.get(a.id)} for a in acts]})


@app.post("/api/projects/{pid}/progress")
def set_progress(pid: int, req: ProgressBody, user: User):
    p = own_project(user, pid)
    with projects.scope(p):
        ids = {a.id for a in load_schedule()}
    prog = projects.clean_progress(ids, req.model_dump())
    p = projects.update(user["company_id"], pid, progress=prog)
    return ok(_delay_for(user["company_id"], p, full=True))


@app.post("/api/projects/{pid}/site-link")
def rotate_site_link(pid: int, request: Request, user: User):
    p = own_project(user, pid)
    lid = live.for_project(user["company_id"], p["id"])
    if not lid:
        raise HTTPException(400, "This project is not monitored yet.")
    tok = live.rotate_token(lid)
    return ok({"site_url": _site_url(request, tok), "site_urls": [f"{b}/site/{tok}" for b in _bases(request)]})


# ------------------------------------------------------------------ assessments (company)
@app.get("/api/assessments")
def assessments(request: Request, user: User):
    p = header_project(request, user)
    return ok(store.list_all(user["company_id"], p["id"] if p else None))


@app.post("/api/assessments")
def save_assessment(req: SaveRequest, request: Request, user: User):
    p = header_project(request, user)
    inputs = projects.clean_inputs(req.inputs)
    result = get_predictor().predict(inputs, req.gate)
    aid = store.save(req.name, inputs, result, req.recovery, company_id=user["company_id"],
                     project_id=p["id"] if p else None)
    if p:
        projects.update(user["company_id"], p["id"], inputs=inputs, gate=result.get("gate"))
    return ok({"id": aid, "alert": alerts.maybe_alert(req.name, result, company_id=user["company_id"])})


@app.get("/api/assessments/{aid}")
def get_assessment(aid: int, user: User):
    a = store.get(aid, user["company_id"])
    if not a:
        raise HTTPException(404, "Assessment not found")
    return ok(a)


@app.delete("/api/assessments/{aid}")
def delete_assessment(aid: int, user: User):
    if not store.delete(aid, user["company_id"]):
        raise HTTPException(404, "Assessment not found")
    return ok({"deleted": aid})


# ------------------------------------------------------------------ live site link
def _public_url() -> str | None:
    u = os.environ.get("REVIVE_PUBLIC_URL") or (load_config().get("live") or {}).get("public_url") or ""
    return u.rstrip("/") or None


def _bases(request: Request) -> list[str]:
    """Every base URL a phone could use to reach this server, best first."""
    out = []
    if pub := _public_url():
        out.append(pub)
    host = request.url.hostname or "localhost"
    port = request.url.port or (443 if request.url.scheme == "https" else 80)
    if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "testserver"):  # nosec B104 - comparing, not binding
        out += [f"http://{ip}:{port}" for ip in live.lan_ips()]
    else:
        out.append(str(request.base_url).rstrip("/"))
        out += [f"http://{ip}:{port}" for ip in live.lan_ips() if ip != host]
    return list(dict.fromkeys(out)) or [f"http://127.0.0.1:{port}"]


def _site_url(request: Request, token: str, base: str | None = None) -> str:
    bases = _bases(request)
    chosen = base.rstrip("/") if base and base.rstrip("/") in bases else bases[0]
    return f"{chosen}/site/{token}"


def _live_public(request: Request, proj: dict, company_id: int) -> dict:
    tok = proj.pop("site_token", None)
    proj.pop("base_inputs", None)
    proj["site_url"] = _site_url(request, tok)
    proj["site_urls"] = [f"{b}/site/{tok}" for b in _bases(request)]
    proj["site_path"] = f"/site/{tok}"
    proj["listeners"] = live.BROKER.listeners(proj["id"], company_id)
    proj["site_devices"] = live.BROKER.device_count(proj["id"])
    return proj


@app.get("/api/live")
def live_list(user: User):
    return ok(live.list_projects(user["company_id"]))


@app.post("/api/live")
async def live_create(req: LiveCreate, request: Request, user: User):
    p = header_project(request, user, required=True)
    if (lid := live.for_project(user["company_id"], p["id"])) is not None:
        return JSONResponse({"detail": "This project is already monitored.", "live_id": lid}, status_code=409)
    loc = req.location.model_dump() if req.location else p.get("location")
    inputs = projects.clean_inputs(req.inputs)
    with projects.scope(p):
        proj = await run_in_threadpool(live.create_project, req.name or p["name"], inputs, req.gate, loc,
                                       user["company_id"], p["id"])
    projects.update(user["company_id"], p["id"], inputs=inputs, gate=req.gate)
    live.BROKER.publish_company(user["company_id"], clean_json({"id": proj["id"], "name": proj["name"],
                                                                "project_id": p["id"]}), event="project")
    return ok(_live_public(request, proj, user["company_id"]))


@app.get("/api/live/stream")
async def live_stream_all(request: Request, user: User):
    """Every monitored project OF THIS COMPANY on one connection (dashboards listen here)."""
    return _event_stream(request, live.company_channel(user["company_id"]))


@app.get("/api/live/{lid}")
def live_get(lid: int, request: Request, user: User):
    proj = own_live(user, lid)
    return ok(_live_public(request, proj, user["company_id"]))


@app.get("/api/live/{lid}/updates")
def live_updates_after(lid: int, user: User, after: int = 0):
    own_live(user, lid)
    return ok(live.updates_after(lid, after))


@app.get("/api/live/{lid}/weather")
async def live_weather(lid: int, user: User):
    own_live(user, lid)
    return ok(await run_in_threadpool(live.weather_for_project, lid))


@app.get("/api/live/{lid}/qr.svg", include_in_schema=False)
def live_qr(lid: int, request: Request, user: User, base: str | None = None):
    import io
    import segno
    proj = own_live(user, lid)
    buf = io.BytesIO()
    segno.make(_site_url(request, proj["site_token"], base), error="m").save(
        buf, kind="svg", scale=6, dark="#06121C", light="#E9F1F4", border=2)
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


# ---- phone side: capability token, no account
def _site_lid(token: str) -> int:
    lid = live.by_token(token)
    if lid is None:
        raise HTTPException(404, "This site link is not valid any more. Ask the project manager for the new QR code.")
    return lid


@app.get("/api/site/{token}")
def site_get(token: str):
    lid = _site_lid(token)
    p = live.get_project(lid)
    return ok({"name": p["name"], "state": p["state"], "location": p["location"],
               "updates": [{"id": u["id"], "created_at": u["created_at"], "summary": u["summary"]} for u in p["updates"]]})


@app.post("/api/site/{token}/update")
async def site_update(token: str, req: LiveUpdate):
    lid = _site_lid(token)
    throttle(f"site:{token}", limit("site_updates_per_min", 30), 60, "Too many updates from this link. Wait a minute.")
    lp = live.get_project(lid)
    p = projects.get(lp["company_id"], lp["project_id"]) if lp.get("project_id") else None
    try:
        with projects.scope(p):
            msg = await run_in_threadpool(live.add_update, lid, req.model_dump())
    except KeyError:
        raise HTTPException(404, "Monitored project not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if p:
        projects.touch(lp["company_id"], p["id"])
    msg = clean_json(msg)
    msg["project_ref"] = lp.get("project_id")
    msg["delivered_to"] = live.BROKER.publish(lid, msg, company_id=lp["company_id"])
    return JSONResponse(msg)


@app.post("/api/site/{token}/presence")
async def site_presence(token: str, req: Presence):
    lid = _site_lid(token)
    throttle(f"presence:{token}", 120, 60)
    cid = live.owner(lid)
    info = live.BROKER.seen(lid, req.device, {"label": (req.label or "Site device")})
    live.BROKER.publish(lid, info, event="presence", company_id=cid)
    return ok({**info, "listeners": live.BROKER.listeners(lid, cid)})


@app.get("/api/site/{token}/stream")
async def site_stream(token: str, request: Request):
    return _event_stream(request, _site_lid(token), site=True)


@app.get("/api/site/{token}/weather")
async def site_weather(token: str):
    lid = _site_lid(token)
    throttle(f"wx:{token}", 30, 60)
    return ok(await run_in_threadpool(live.weather_for_project, lid))


def _event_stream(request: Request, channel, site: bool = False) -> StreamingResponse:
    queue = live.BROKER.subscribe(channel, site=site)

    async def events():
        try:
            yield "retry: 2000\n\n"
            yield f"event: hello\ndata: {json.dumps({'server_time': time.time(), 'version': __version__})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event, msg = await asyncio.wait_for(queue.get(), timeout=10)
                    yield f"event: {event}\ndata: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    yield f"event: ping\ndata: {json.dumps({'t': time.time()})}\n\n"
        finally:
            live.BROKER.unsubscribe(channel, queue)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                                      "Content-Encoding": "identity"})


# ------------------------------------------------------------------ weather
@app.get("/api/weather/places")
def weather_places(user: User):
    return ok({"places": [{"name": k, "lat": v[0], "lon": v[1]} for k, v in weather.PLACES.items()],
               "province_default": weather.PROVINCE_DEFAULT, "rules": load_config()["weather"]["lost_day_rules"]})


@app.get("/api/weather")
async def weather_outlook(user: User, lat: float, lon: float, name: str | None = None):
    try:
        lat, lon = weather.valid_coords(lat, lon)
    except ValueError as exc:
        raise HTTPException(400, "Latitude must be -90 to 90 and longitude -180 to 180.") from exc
    throttle(f"wx:{user['id']}", 60, 60)
    return ok(await run_in_threadpool(weather.outlook, lat, lon, (name or "")[:60] or None))


# ------------------------------------------------------------------ pages
app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")
app.mount("/vendor", StaticFiles(directory=WEB / "vendor"), name="vendor")


@app.get("/", include_in_schema=False)
def landing():
    return FileResponse(PAGES["landing"])


@app.get("/app", include_in_schema=False)
def dashboard(request: Request):
    if not auth.session_user(request.cookies.get(COOKIE)):
        return RedirectResponse("/?next=app#start", status_code=303)
    return FileResponse(PAGES["app"])


@app.get("/auth/link/{token}", include_in_schema=False)
def admin_link(token: str, request: Request):
    """One-time admin sign-in link from `python -m revive admin-link`."""
    if not LIMITER.hit(f"adminlink:{client_ip(request)}", 20, 600):
        return RedirectResponse("/?link=invalid#start", status_code=303)
    u = auth.redeem_admin_link(token)
    if not u:
        return RedirectResponse("/?link=invalid#start", status_code=303)
    log.warning("Admin %s signed in with a one-time console link from %s", u["email"], client_ip(request))
    resp = RedirectResponse("/app#projects", status_code=303)
    _set_cookie(request, resp, auth.create_session(u["id"], client_ip(request)))
    return resp


@app.get("/site/{token}", include_in_schema=False)
def site_page(token: str):
    return FileResponse(PAGES["site"], status_code=200 if live.by_token(token) else 404)
