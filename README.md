# REVIVE — AI-BIM delay analysis, early warning and recovery (v2.0)

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/taha94753-cell/REVIVE-AI-BIM?quickstart=1)

**Try it online, free, no card:** click the button above (GitHub Codespaces). REVIVE installs itself and opens in a new tab after about 5 minutes; see `.devcontainer/README.md`. To share the app from your own laptop instead, run `run.bat`, then `share.bat`.

REVIVE measures how late a construction project is **today** (current delay, from the baseline schedule and site data), forecasts how late it will finish when it is 25% or 50% of the way through its contract time, explains each forecast as exact per-answer contributions with an owner and an action for each driver, and uses a linear programme to find the cheapest recovery.

**New in 2.0**
- **Company workspaces.** Each company signs up, adds its people (admin or member roles) and runs as many projects as it has. Every project has its own baseline schedule, optional IFC model, assessments, live site link and history, isolated from every other company.
- **Current delay analysis** (`revive/delay.py`, the *Current delay* sheet): Earned Schedule on the baseline, a retained-logic CPM update from the status date, three finish estimates side by side (to plan, current pace, ML forecast), activities behind programme, optional activity-level progress, and the slip in each window between site updates apportioned to client, weather and contractor events. It uses no machine learning, so it is an independent check on the forecast.
- **Security hardening.** Authentication, company isolation, revocable phone links, CSRF protection, upload limits, security headers and rate limits. See `docs/SECURITY.md` (14 findings, each with a regression test).
- **New interface.** A separate animated landing page at `/` (Three.js night-site scene, GSAP scroll choreography, tabbed walkthrough, sign-up and sign-in) and a tabbed workspace at `/app` with a project switcher, project cards and a three-step *New project* dialog.

It runs on two things only: the **baseline schedule** (Primavera P6 `.xer` or CSV) and **site reports** (the assessment form and phone updates, with live weather). A **BIM model is optional**. When one is connected, the same forecast and recovery are drawn on the IFC model and written back into it; when it is not, everything else works unchanged.

```
Survey / project records ──► anonymised dataset ──► sign-constrained linear models on 10/13 core questions (time, cost, high-risk) ──► exact contributions
                                                          │
IFC model (Revit export) ──► IfcOpenShell ──► floor area, storeys, concrete ──► model inputs
          │                                               │
          └──► elements ◄── WBS_Code ──► CPM schedule ◄──┘  forecast finish scales the schedule
                    │                         │
                    │                    LP recovery (PuLP/CBC): crash cost vs liquidated damages
                    ▼                         ▼
      3D risk / 4D build / recovery views   Pset_REVIVE_Risk written back into the IFC
```

## Quick start

You need **Python 3.12** (3.13 and 3.14 also work; 3.11 works with slightly older package versions). If none is installed, `setup.bat` offers to install Python 3.12 for you. Everything else installs from `requirements-lock.txt`. No internet is needed once installed, which matters for a defence room with bad Wi-Fi.

**Windows:** double-click `run.bat`. On first use it runs the setup by itself (or run `setup.bat` first). Keep the black window open while you use the app; the browser opens when the server is ready.

If Windows says **"The publisher could not be verified"** or **"Windows protected your PC"**, that is because the folder came from a download and the scripts are not digitally signed (signing needs a paid certificate). Click **Run** (or **More info, Run anyway**) once: setup then clears the download mark from the whole folder, so it does not ask again. To avoid it entirely, right-click the zip before extracting, choose **Properties**, tick **Unblock**, then extract.

**macOS / Linux:**
```bash
./run.sh        # runs ./setup.sh first if needed
```

**Phone on the live link (Windows, once):** double-click `phone-access.bat` and accept the administrator prompt. It allows port 8000 through the firewall. Remove it after the demo with `phone-access.bat remove`.

**By hand:**
```bash
python -m venv .venv && .venv\Scripts\activate        # Windows  (source .venv/bin/activate on Mac/Linux)
pip install -r requirements.txt
python -m revive setup          # ingests data, trains models, builds the demo IFC (skips what already exists)
python -m revive serve --open   # http://localhost:8000  (landing page; the workspace is at /app)
```

The repository ships with the anonymised dataset and trained models, so `serve` works straight away.

**First use:** open http://localhost:8000, press **Create workspace**, enter your company and your own account. In the workspace press **Load a sample project** to see every sheet with data, or **New project** to add a real one (details, then the P6 `.xer` baseline, then an optional IFC model). The first company to register on an install also adopts any assessments and monitored projects saved by an older version.

## If something goes wrong

Run the doctor first. It checks Python, every package, the CBC solver, the model files, the port and the phone address, and says what to fix:
```
.venv\Scripts\python.exe -m revive doctor        (Windows)
.venv/bin/python -m revive doctor                (macOS / Linux)
```

| What you see | Cause | Fix |
|---|---|---|
| Sent back to the landing page | Not signed in, or the session expired (7 days) | Sign in again |
| "Request blocked ... CSRF protection" | A script or tool called the API without the `X-Revive-Request: 1` header | Add the header; the dashboard always sends it |
| Phone says "This link is not valid" | The link was reissued on the Live sheet | Scan the new QR code |
| "Waiting for the REVIVE server" panel, or "Server not reachable" banner | The Python server is not running: the black window was closed, the PC slept or restarted, or the browser restored an old tab | Double-click `run.bat`. The dashboard reconnects and catches up by itself; no reload needed |
| `run.bat` window flashes and closes (older copies) | No `.venv`, or the Python it was built with was removed | Run `setup.bat`. The new `run.bat` repairs this itself and pauses on errors |
| "The publisher could not be verified" | Downloaded, unsigned script | Click **Run** once; setup unblocks the folder. Or unblock the zip in its Properties before extracting |
| "No usable Python was found" | No Python 3.11-3.14, or it is hidden behind the Microsoft Store shortcut | Press **Y** to install Python 3.12, or install it from python.org with "Add python.exe to PATH" ticked. In a command window, `py --list` shows what is installed |
| "Port 8000 is used by another program" | Something else holds the port | Nothing to do: REVIVE moves to the next free port and prints the address |
| Page shows "Open REVIVE through its server" | `index.html` was opened from the disk | Use `run.bat`, or open http://localhost:8000 |
| Phone cannot open the link | Different network, firewall, or the wrong network adapter | Same Wi-Fi or hotspot as the laptop; run `phone-access.bat` once; pick another address under the QR code |
| "Dashboard error" message | A real bug, not a connection problem | Reload; if it repeats, run the doctor and send the message |

## What is in the app

The landing page (`/`) explains the product and holds the sign-up and sign-in forms. The workspace (`/app`) has a project switcher in the top bar and these sheets:

| Sheet | What it does |
|---|---|
| Projects | Every project of your company as a card: delay to date, forecast overrun, live status, a sparkline of the slip. Search, sort, create, delete (admins), or load a labelled sample project. |
| Current delay | How late the project is now: delay to date in days and its band, actual time against earned schedule, SPI(t), work done against plan, cost to date, estimated delay today from the calendar. S-curve with AT and ES, three finish estimates, slip per window apportioned to events (with concurrent windows flagged), activities behind programme, and optional activity progress. | The **evidence pack** button opens a printable extension-of-time pack (delay, slip per window and its apportionment, notice date, every site record, early warning, owned actions, sign-off).
| Forecast | An instrument cluster (overrun and high-risk gauges either side of the building, warning lights), the 10-question form (13 at 50%) with what-if sliders, cost overrun, recovery trigger, *This week* (each driver with an owner and an action) and the contribution waterfall. *Save to project* stores the assessment (re-scored by the server). |
| Live site | Replay of the site updates one by one with the early warning (when REVIVE first flagged the project, and how long before completion). Starts the project's phone link (QR code with an unguessable token, revocable), live trajectory, feed and weather. Updates from the phone reach every open dashboard of the company. |
| BIM | Optional Three.js view of the project's IFC model: risk heat map, 4D build sequence, recovery. Upload, demo model, disconnect, IFC export with `Pset_REVIVE_Risk`. |
| Recovery | The project's baseline schedule (P6 `.xer`, MS Project `.xml` or CSV) and the LP crash plan, time-cost curve, Gantt, Monte Carlo finish risk and *what drives the finish* (the share of simulated futures in which each activity is critical). |
| Impact | Days, cost and carbon avoided, rework carbon at risk. |
| Benchmark | The anonymised training dataset with cross-validated forecasts (formerly "Portfolio"); open a record as a worked example. |
| Evidence | Cross-validated and leave-one-company-out metrics, model comparison against an SPI-only baseline and the old XGBoost design, robustness, predicted against actual, SHAP beeswarm, delay-cause ranking and limitations. |

## Commands

| Command | Purpose |
|---|---|
| `python -m revive ingest --file data/raw/X.xlsx` | Clean and anonymise a survey workbook into `data/processed/projects_clean.csv` |
| `python -m revive train [--tune] [--sensitivity]` | Cross-validate, compare models, refit on all records, save models and figures |
| `python -m revive evaluate --file new.xlsx` | **External test** on newly collected projects. Duplicates of training records are excluded automatically |
| `python -m revive sample-ifc` | Rebuild the illustrative G+3 IFC model |
| `python -m revive serve [--port 8000] [--open]` | Start the web app (reuses a running REVIVE; moves to a free port if 8000 is taken) |
| `python -m revive doctor` | Diagnose Python, packages, models, port and phone address |
| `python -m revive create-company --company "X" --name "Y" --email y@x.com` | Add a company and its admin (works when web sign-up is closed) |
| `python -m revive reset-password --email y@x.com` | Set a new password; signs the user out everywhere |
| `python -m pytest -q` | Run the test suite (`pip install -r requirements-dev.txt` first) |

## Live site link (the demo moment)

1. Open a project, run a forecast on the Forecast sheet, then press **Start the site link for this project** on the Live site sheet.
2. Scan the QR code with a phone on the same Wi-Fi or hotspot. On Windows, allow Python through the firewall on private networks the first time.
3. On the phone, move the time-elapsed slider, enter SPI, and tap the events that happened: late IPCs, material stoppages, variations, design changes, weather days.
4. Press **Send site update**. Every open dashboard re-forecasts within about a second: new point on the trajectory, new feed entry, live trend tiles, recoloured BIM model, new recovery plan and finish-date distribution. A band that worsens to Critical triggers the e-mail alert.

With no second device, press **Open the phone page here**.

What makes the link dependable:
- Every dashboard listens to one stream that carries all monitored projects, so it receives phone updates even if it was opened (or reloaded) after monitoring started. It remembers the project it follows.
- The dashboard shows when a site phone has the page open ("1 site phone connected"), and the phone shows how many dashboards are watching.
- Updates carry ids. Beside the stream, the dashboard polls for anything it missed, so an update sent during a Wi-Fi drop or a server restart still arrives, exactly once.
- With no signal, the phone keeps the update and sends it when the connection returns.
- If the computer has several network adapters (VPN, VirtualBox, Docker), pick the right address under the QR code. For a fixed address such as a tunnel, set `live.public_url` in `config.yaml` or the `REVIVE_PUBLIC_URL` environment variable.

How live readings map onto the trained model:
- Before 50% of contract time the G25 model is used; from 50% on, the G50 model.
- Event counts are expressed per quarter of contract time.
- Value certified is rescaled to the nearest checkpoint.

The details are in `revive/live.py` and `docs/ARCHITECTURE.md`.

## Running without a BIM model

- On the BIM view sheet, press **Disconnect the model**, or set `bim.start_with_demo_model: false` in `config/config.yaml` to start without one.
- Forecasts, explanations, recovery, live monitoring, weather, impact and evidence all keep working from the baseline schedule.
- The hero shows the schedule instead of the building.
- Two things need a model and say so:
  - rework carbon at risk (it needs the concrete volume);
  - the IFC export.
- Reconnect at any time with **Upload IFC model** or **Use the demo model**.

## Live weather

- Data comes from [Open-Meteo](https://open-meteo.com): free for non-commercial use, no API key, CC BY 4.0. One request returns the last 14 days observed plus a 16-day forecast.
- Choose the site location on the Live sheet. It defaults to the provincial capital of the project's province.
- A day counts as lost for weather-sensitive work at 10 mm rain, 50 km/h wind, 45 °C heat or 2 °C frost risk. Edit these in `weather.lost_day_rules`.
- **Observed** lost days since the last update are suggested on the phone page; the site engineer confirms or edits them.
- **Forecast** lost days can be added to the weather-sensitive activities on site on those days (tick the box on the Live sheet). The recovery plan is then re-optimised.
- Which activities are weather-sensitive comes from the `weather_sensitive` column in the schedule. P6 imports guess it from activity names.
- Without internet, the app says so and site staff enter weather days by hand.

## Your own data and model

**New survey data.** Put the workbook in `data/raw/` (same Google Form columns), then run `ingest` and `train`. To keep new projects as a test set, run `evaluate` **before** merging them.

**Your Revit model.**
1. Add a shared parameter `WBS_Code` (text) to model elements, and set it to the activity ids in `bim/schedule.csv` (A01, A02 ...).
2. Export IFC4, and tick "Export user defined property sets" (or include the parameter in a property-set mapping file).
3. Upload the `.ifc` on the project's BIM sheet (or in the *New project* dialog). Each project keeps its own model.

Elements without `WBS_Code` fall back to the `ifc_storey` + `ifc_types` rules in `schedule.csv`. So a model whose storeys are named like the schedule still links without any parameter.

**Your baseline schedule.**
- **Primavera P6:** export the project as `.xer` and upload it on the Recovery sheet. REVIVE reads activities, durations, WBS and links.
  - Level-of-effort and WBS-summary activities are skipped.
  - SS/FF/SF links are treated as finish-to-start and lags are ignored. The import report counts both.
  - The import is saved as a CSV next to the upload so you can edit it.
  - Crash limits and crash costs are not in P6. Defaults from `config.yaml` are applied; calibrate them with your planner.
- **CSV:** use the columns of `bim/schedule.csv`: `id, name, wbs, duration_days, predecessors, crash_max_days, crash_cost_per_day_pkr, crash_method, trade, ifc_storey, ifc_types, weather_sensitive`.

## Configuration

Every threshold and assumption lives in `config/config.yaml`: risk bands, health-score weights, recovery triggers, liquidated-damages default, crash limits, carbon factors, training scope, question set (`feature_set`), model family (`model: linear | xgboost`) and their settings. Lines marked `VERIFY` are assumptions you must check against a cited source before quoting them.

E-mail alerts: set `alerts.enabled: true` and the environment variables `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_TO`. Without them, alerts are written to `data/outbox/` as `.eml` files, which is fine for a demo.

## Current results (81 real completed projects)

| Checkpoint | Time-overrun error | Guessing the median | R² | R², unseen company | High-risk AUC | AUC, unseen company |
|---|---|---|---|---|---|---|
| 25% of contract time | 6.4 pts | 9.8 pts | 0.81 | 0.50 | 0.88 | 0.86 |
| 50% of contract time | 4.2 pts | 9.8 pts | 0.91 | 0.74 | 0.91 | 0.89 |

"Unseen company" is leave-one-company-out: trained on the other contractors, tested on the held-out one. Hypothetical scenarios and ongoing projects are not used for training. Read `docs/DATA_NOTES.md` before quoting any number: it compares this design with SPI alone and with the earlier XGBoost model on all answers, and explains why the 25% cost forecast is indicative only.

## Repository layout

```
config/config.yaml        every threshold, factor and model setting
revive/                   Python package
  schema.py               single source of truth for fields, encodings, checkpoints
  data.py                 workbook -> anonymised dataset + targets
  features.py             answers -> model matrix (same code for training and the web form)
  modeling.py             repeated CV, leave-one-company-out, baselines, final fit, SHAP, sensitivity
  linear.py               sign-constrained ridge / logistic models with exact contributions, saved as JSON
  actions.py              forecast drivers -> reasons with an owner and one action
  inference.py            prediction, 80% range, contributions and actions per project, health score
  scheduling.py           CPM, Earned Schedule status, ML-driven forecast
  optimizer.py            LP recovery (PuLP/CBC) and time-cost curve
  bim.py                  IfcOpenShell geometry, quantities, WBS links, IFC write-back
  recovery.py             ties forecast, schedule, LP and BIM together
  sustainability.py       days/cost/carbon avoided, rework carbon at risk
  insights.py             delay-cause RII, dataset composition
  live.py                 live monitored projects, phone updates, SSE push channel
  weather.py              live site weather (Open-Meteo) and lost-day rules
  schedule_import.py      Primavera P6 .xer and CSV baseline schedule import
  simulation.py           Monte Carlo finish-date risk
  store.py, alerts.py     saved assessments (SQLite), e-mail alerts to the owning company
  auth.py                 companies, users, scrypt passwords, sessions
  projects.py             company projects, per-project files and activity progress
  delay.py                current delay analysis (earned schedule, CPM update, windows)
  security.py             CSP and headers, CSRF guard, body limits, rate limiter
  db.py                   shared SQLite connection (WAL) and migrations
  server.py, cli.py       FastAPI app and command line
  launcher.py             safe start-up (port checks, open when ready) and the doctor
web/                      landing.html (/), app.html (/app), site.html (phone); Three.js, GSAP and fonts vendored
  assets/js/landing.js    landing page: Three.js night-site scene, GSAP motion, sign-up and sign-in
  assets/js/app.js        dashboard controller
  assets/js/conn.js       server connection: error types, heartbeat, automatic reconnect
  assets/js/live.js       live channel: event stream + catch-up polling, de-duplicated by update id
  assets/js/fx.js         motion: tweens, count-ups, scroll reveal, tooltips, toasts, scroll-spy
  assets/js/charts.js     SVG charts with entry animations and hover details
  assets/js/twin.js       Three.js viewer: blended colour changes, hover, camera fly-in
  assets/js/site.js       phone page: presence, offline queue, confirmation
bim/                      demo IFC model and linked schedule
data/processed/           anonymised dataset used by the app
models/                   trained models, model card, out-of-fold predictions
reports/                  figures for the written report, comparison and sensitivity tables
tests/                    pytest suite (73 tests, including test_security.py and test_delay.py)
docs/                     architecture, security review, data notes, defence guide, deployment, roadmap
```

## Using Claude Code

The step-by-step guide in plain words is `docs/CLAUDE_CODE_GUIDE.md`.

Open the folder in Claude Code; `CLAUDE.md` gives it the architecture and ground rules. Two project commands are included:
- `/retrain` retrains the models and summarises the changes.
- `/evaluate-new-data <file>` runs the external test.

## Security

See `docs/SECURITY.md` for the full review. In short: every API route except the landing figures and the phone link needs a signed-in user; everything is scoped to the user's company; phones use revocable capability links; uploads are typed and size-limited; the CSP allows only this server's scripts. Settings live under `security:` in `config/config.yaml`. On anything other than a trusted network, serve REVIVE over HTTPS.

## Data protection

The raw workbook contains a private sheet linking project codes to company and project names, plus a respondent e-mail. `.gitignore` keeps `data/raw/` out of git. The processed CSV has no names, cities, e-mails or timestamps. Still, get your supervisor's and the contributing firms' permission before making the repository public.
