"""Upload this repository to a Hugging Face Docker Space (run by .github/workflows/deploy-hf-space.yml).

Environment: HF_TOKEN (write access), HF_SPACE ("owner/name"), HF_PRIVATE ("true" / "false").
The Space gets the same files as the repository except local and private data, plus a README with the
YAML header Hugging Face needs (sdk: docker, app_port: 8000), and its Dockerfile allows the Space page
(https://huggingface.co) to show the app in a frame.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parent.parent
# never uploaded: private survey data, local databases and uploads, caches, the backup folder
SKIP_DIRS = {".git", ".github", ".venv", "venv", "__pycache__", "_backup", ".pytest_cache", "tests"}
SKIP_PATHS = ("data/raw", "data/app.db", "data/outbox", "data/workspaces", "models/bim_cache",
              "models/exports", "bim/uploads")

HEADER = """---
title: REVIVE
emoji: 🏗️
colorFrom: yellow
colorTo: gray
sdk: docker
app_port: 8000
pinned: false
short_description: AI-BIM early warning and recovery for construction delays
---

> The app runs right here on this page. Full-screen link: https://{subdomain}.hf.space
> Click **Create workspace** to start, then **Load a sample project**. Saved workspaces live in the
> container and reset when the Space restarts, so this is a demo, not a place to keep project data.

"""


def skipped(rel: str) -> bool:
    parts = rel.split("/")
    if any(p in SKIP_DIRS for p in parts):
        return True
    return any(rel == s or rel.startswith(s + "/") for s in SKIP_PATHS) and not rel.endswith("README.md")


def stage(dest: Path, subdomain: str) -> int:
    n = 0
    for src in ROOT.rglob("*"):
        rel = src.relative_to(ROOT).as_posix()
        if src.is_dir() or skipped(rel):
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
        n += 1
    # this Space's page shows the app in a frame from huggingface.co: allow exactly that origin
    # (everywhere else, e.g. run.bat and docker compose, framing stays refused)
    docker = dest / "Dockerfile"
    docker.write_text(docker.read_text(encoding="utf-8").replace(
        "ENV PYTHONDONTWRITEBYTECODE=1", "ENV REVIVE_EMBED_ORIGINS=https://huggingface.co PYTHONDONTWRITEBYTECODE=1", 1),
        encoding="utf-8")
    readme = dest / "README.md"
    readme.write_text(HEADER.format(subdomain=subdomain) + (ROOT / "README.md").read_text(encoding="utf-8"),
                      encoding="utf-8")
    return n


def main() -> int:
    token, space = os.environ.get("HF_TOKEN"), os.environ.get("HF_SPACE", "taha94753/revive")
    private = os.environ.get("HF_PRIVATE", "true").strip().lower() not in ("false", "0", "no")
    if not token:
        print("HF_TOKEN is not set", file=sys.stderr)
        return 1
    api = HfApi(token=token)
    api.create_repo(space, repo_type="space", space_sdk="docker", private=private, exist_ok=True)
    subdomain = space.replace("/", "-").replace("_", "-").replace(".", "-").lower()
    with tempfile.TemporaryDirectory() as tmp:
        n = stage(Path(tmp), subdomain)
        api.upload_folder(repo_id=space, repo_type="space", folder_path=tmp, delete_patterns=["*"],
                          commit_message=f"Deploy {os.environ.get('GITHUB_SHA', 'local')[:7]} from GitHub")
    print(f"Uploaded {n} files to https://huggingface.co/spaces/{space} ({'private' if private else 'public'}).")
    print(f"App URL once the build finishes: https://{subdomain}.hf.space")
    return 0


if __name__ == "__main__":
    sys.exit(main())
