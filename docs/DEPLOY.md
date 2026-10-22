# Deployment

## Local (recommended for the defence)
Run `setup.bat` then `run.bat` (or `./setup.sh`, `./run.sh`).

The frontend has no CDN dependencies: Three.js and the fonts are vendored. The app runs with Wi-Fi off. Test that before the defence.

## Docker
```bash
docker compose up --build        # http://localhost:8000
```
`data/` and `bim/` are mounted as volumes, so saved assessments and uploaded models survive restarts. The Dockerfile builds on Python 3.12 from `requirements-lock.txt` and runs as uid 1000.

## GitHub Codespaces (free, no card, recommended)
`.devcontainer/` makes the repository open as a ready-to-run codespace.
1. Repository page, green **Code** button, **Codespaces** tab, **Create codespace on main**
   (or the *Open in GitHub Codespaces* button in the README).
2. The first start installs everything (about 5 minutes); `.devcontainer/start.sh` then starts REVIVE on
   port 8000, makes the port public and opens it in a new tab. The **Ports** tab always shows the link,
   `https://<codespace-name>-8000.app.github.dev`; the Live site QR code points there too.
3. Share that link. It works while the codespace runs: it stops after 30 minutes idle (raise it to 4 hours
   at github.com/settings/codespaces) and starts again from **Code**, **Codespaces** with the same link.

Free personal accounts get 60 hours a month on a 2-core machine. Stop the codespace after a demo
(github.com/codespaces). Saved workspaces stay in the codespace until it is deleted.

## From your own laptop (free, no account)
Run `run.bat`, then `share.bat` (macOS / Linux: `./run.sh`, then `./share.sh`). It prints a temporary
`https://….trycloudflare.com` link to the app on your laptop (a Cloudflare quick tunnel). The link changes
every time and works only while both windows stay open.

## Render (free plan, but Render may ask for a card)
`render.yaml` is a Render Blueprint for a free Docker web service.
1. render.com, sign up with GitHub.
2. *New*, *Blueprint*, connect `taha94753-cell/REVIVE-AI-BIM`, branch `main`, *Apply*.
3. The first build takes about 10 minutes. The app is then at `https://revive-XXXX.onrender.com`
   (Render shows the exact address). It redeploys on every push to `main`.

Measured in the Docker image: about 200 MB of memory with sign-in, forecast, recovery, BIM and benchmark
all used, inside the free plan's 512 MB. Free services sleep after 15 minutes without visitors (the first
visit takes about a minute) and the disk resets on restart, so saved workspaces do not last. The link is
public and anyone can create a workspace; the anonymised survey dataset is visible in the Benchmark sheet,
so confirm the contractors agree before sharing it.

## Hugging Face Spaces (needs a Hugging Face PRO subscription for Docker Spaces)
`.github/workflows/deploy-hf-space.yml` creates the Space and uploads the app when run from the Actions
tab (*Deploy to Hugging Face Space*, *Run workflow*). It runs
`scripts/deploy_hf_space.py`, which adds the Space README header and never uploads `data/raw/`.

One-time setup:
1. huggingface.co, *Settings*, *Access Tokens*, *Create new token*, type **Write**. Copy it.
2. GitHub repository, *Settings*, *Secrets and variables*, *Actions*, *New repository secret*:
   name `HF_TOKEN`, value the token.
3. *Actions* tab, *Deploy to Hugging Face Space*, *Run workflow* (or push to `main`).
4. The first build takes about 10 minutes. The app then works on the Space page itself
   (huggingface.co/spaces/taha94753/revive) and full screen at **https://taha94753-revive.hf.space**.
   Only the Space allows framing (`REVIVE_EMBED_ORIGINS=https://huggingface.co`, set by the deploy
   script); local and Docker runs keep refusing it.

The Space is **private** by default. Set the repository variable `HF_PRIVATE` to `false` to make it public
once the contractors who shared the records agree to the anonymised dataset being public; `HF_SPACE`
changes the Space name. Free Spaces sleep after 48 hours without visitors (the first visit wakes them,
about a minute) and saved workspaces reset when the Space restarts, so it is for showing the app, not for
keeping project data.

The image was built and run locally as uid 1000 (the user Spaces run as): health check, sign-up and a
forecast all work.

## Railway and others
Use the Dockerfile. Set `PORT` if the platform assigns one; the start command already reads it. Free tiers sleep, so wake the app a few minutes before a demo.
