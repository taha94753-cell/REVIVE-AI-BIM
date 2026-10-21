import os
import sys
import tempfile
import uuid
import warnings
from pathlib import Path

# every test run gets its own database and workspace folder (never the real data/app.db)
_TMP = tempfile.mkdtemp(prefix="revive_test_")
os.environ.setdefault("REVIVE_DB", os.path.join(_TMP, "app.db"))
os.environ.setdefault("REVIVE_WORKSPACES", os.path.join(_TMP, "workspaces"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

import pytest  # noqa: E402

PASSWORD = "correct-horse-battery-9"


def company_client(app, name: str | None = None):
    """A TestClient signed in as the admin of a brand-new company, sending the CSRF header like the dashboard."""
    from fastapi.testclient import TestClient
    from revive.security import LIMITER
    LIMITER.hits.clear()
    c = TestClient(app, headers={"X-Revive-Request": "1"})
    c.__enter__()
    tag = uuid.uuid4().hex[:8]
    r = c.post("/api/auth/register", json={"company": name or f"Company {tag}", "name": "Test Admin",
                                           "email": f"admin-{tag}@example.com", "password": PASSWORD})
    assert r.status_code == 200, r.text
    c.email = f"admin-{tag}@example.com"
    c.user = r.json()["user"]
    return c


def new_project(c, name="Hospital block", **extra):
    r = c.post("/api/projects", json={"name": name, **extra})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def client():
    from revive.server import app
    c = company_client(app)
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def other():
    from revive.server import app
    c = company_client(app)
    yield c
    c.__exit__(None, None, None)
