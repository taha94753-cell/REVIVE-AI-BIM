# Deployment

## Local (recommended for the defence)
Run `setup.bat` then `run.bat` (or `./setup.sh`, `./run.sh`).

The frontend has no CDN dependencies: Three.js and the fonts are vendored. The app runs with Wi-Fi off. Test that before the defence.

## Docker
```bash
docker compose up --build        # http://localhost:8000
```
`data/` and `bim/` are mounted as volumes, so saved assessments and uploaded models survive restarts. The Dockerfile builds on Python 3.12 from `requirements-lock.txt` and runs as uid 1000.

## Hugging Face Spaces (free link, deployed by GitHub Actions)
`.github/workflows/deploy-hf-space.yml` creates the Space and uploads the app on every push to `main`
(or from the Actions tab, *Deploy to Hugging Face Space*, *Run workflow*). It runs
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

## Render / Railway
Use the Dockerfile. Set `PORT` if the platform assigns one; the start command already reads it. Free tiers sleep, so wake the app a few minutes before a demo.
