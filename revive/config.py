"""Load config/config.yaml once and resolve every path relative to the repo root."""
from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def load_config() -> dict:
    path = Path(os.environ.get("REVIVE_CONFIG", ROOT / "config" / "config.yaml"))
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def path(rel: str | Path) -> Path:
    """Resolve a repo-relative path from the config into an absolute Path."""
    p = Path(rel)
    return p if p.is_absolute() else ROOT / p


def models_dir() -> Path:
    d = ROOT / "models"
    d.mkdir(exist_ok=True)
    return d


def reports_dir() -> Path:
    d = ROOT / "reports"
    (d / "figures").mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Project scope. Every company project has its own baseline schedule and (optional)
# IFC model. A request for a project runs inside `use_scope(...)`, so the existing
# engine code (load_schedule(), get_bim()) picks up that project's files without
# any global state that another company could change. Outside a scope (CLI, tests,
# a quick assessment with no project) the demo files from config.yaml are used.
# ---------------------------------------------------------------------------
_SCOPE: ContextVar[dict | None] = ContextVar("revive_scope", default=None)


@contextmanager
def use_scope(files: dict | None):
    """files = {"schedule": path or None, "ifc_mode": "demo" | "none" | "file", "ifc": path or None}."""
    token = _SCOPE.set(files)
    try:
        yield
    finally:
        _SCOPE.reset(token)


def active_file(kind: str) -> Path | None:
    """The schedule or IFC file for the current project scope.
    Returns None for 'ifc' when the project runs without a BIM model."""
    cfg = load_config()["bim"]
    default = path(cfg["ifc_file" if kind == "ifc" else "schedule_file"])
    scope = _SCOPE.get()
    if kind == "schedule":
        p = (scope or {}).get("schedule")
        return Path(p) if p and Path(p).exists() else default
    mode = (scope or {}).get("ifc_mode") or ("demo" if cfg.get("start_with_demo_model", True) else "none")
    if mode == "none":
        return None
    if mode == "file":
        p = (scope or {}).get("ifc")
        return Path(p) if p and Path(p).exists() else None
    return default if default.exists() else None


def workspace_dir(company_id: int, project_id: int | None = None) -> Path:
    """data/workspaces/c<company>/p<project>: uploads and exports never mix between companies."""
    root = os.environ.get("REVIVE_WORKSPACES") or load_config().get("workspace", {}).get("dir", "data/workspaces")
    base = path(root) / f"c{int(company_id)}"
    d = base / f"p{int(project_id)}" if project_id is not None else base
    d.mkdir(parents=True, exist_ok=True)
    return d


def database_path() -> Path:
    """SQLite file for saved assessments and live projects (REVIVE_DB overrides, e.g. in tests)."""
    return Path(os.environ["REVIVE_DB"]) if os.environ.get("REVIVE_DB") else path(load_config()["data"]["database"])
