# CLAUDE.md — working on REVIVE

REVIVE is a final-year design project (NUST, civil engineering). It is an AI-BIM decision-support app that:
- forecasts construction time/cost overrun at 25% or 50% of contract time with sign-constrained linear models on 10/13 core questions (`schema.CORE_KEYS`, `CORE_DIRECTION`), trained on the 81 real completed projects, and explains each forecast as exact per-answer contributions with owned actions (`actions.py`);
- links the forecast to an IFC model through the schedule (IfcOpenShell);
- optimises recovery with a linear programme (PuLP/CBC).

The backend is FastAPI; the frontend is plain HTML/CSS/JS with vendored Three.js.

## Commands
- Setup: `pip install -r requirements-dev.txt && python -m revive setup`
- Run: `python -m revive serve --reload` then open http://localhost:8000 (API docs at /docs)
- Test: `python -m pytest -q` (must stay green; 73 tests)
- Security scan: `bandit -r revive` (must report no issues)
- Retrain: `python -m revive train --sensitivity`
- External test: `python -m revive evaluate --file <xlsx>`
- JS syntax check: `cp web/assets/js/app.js /tmp/a.mjs && node --check /tmp/a.mjs` (same for charts.js, twin.js, landing.js, tilt.js)

## Architecture (data flow)
`schema.py` → `data.py` → `features.py` → `modeling.py` → `inference.py` → `recovery.py`

`evidence.py` builds the extension-of-time evidence pack (`/api/projects/{id}/evidence`, printable page `web/evidence.html`) and the early-warning record. `schedule_import.py` also reads MS Project XML through defusedxml (never parse uploads with the plain xml modules). `simulation.py` reports the criticality index (what drives the finish).
`recovery.py` combines `scheduling.py` (CPM, forecast), `optimizer.py` (LP), `simulation.py` (Monte Carlo), `bim.py` (IFC) and `sustainability.py`. `weather.py` fetches Open-Meteo site weather and classifies lost days; `schedule_import.py` imports Primavera P6 `.xer` or CSV baseline schedules. `live.py` holds monitored projects, phone updates and the in-process SSE `Broker`; the phone page is `web/site.html` + `web/assets/js/site.js`. `server.py` exposes all of it under /api/*. The frontend lives in `web/assets/js/`:
- `app.js`: state and rendering
- `conn.js`: every API call goes through `api()`/`post()`, which raise `ApiError` (`.network` = server unreachable); the monitor reconnects by itself
- `live.js`: `LiveChannel`, one SSE connection to `/api/live/stream` plus catch-up polling of `/api/live/{pid}/updates?after=`
- `fx.js`: tweens, count-ups, reveal, `[data-tip]` tooltips, toasts
- `charts.js`: hand-drawn SVG charts (entry animations are CSS classes; `animate(false)` while a slider is dragged)
- `twin.js`: Three.js viewer

## Ground rules
1. **schema.py is the single source of truth** for model inputs. When you add a field, add it there (key, survey code, stage, kind, options). The form, encoder and API all follow automatically. Then retrain.
2. **No outcome leakage.** Never add whole-project totals (D*_tot), EOT granted, final cost, status, D10 or G1-G14 as model inputs. See `LEAKAGE_EXCLUDED` in schema.py.
3. **Honest numbers only.**
   - Performance figures come from `models/model_card.json` (cross-validated). Never report in-sample accuracy.
   - Never invent results.
   - When a dataset project is scored in the UI, the out-of-fold value is the honest one (the app already shows it).
4. **Hypothetical data stays labelled.** 32 records (`source_group == "SYN"`) are hypothetical scenarios. Keep the flag visible in the UI and docs.
4a. **Report leave-one-company-out next to random-fold scores.** The model card has both; quote the unseen-company figure when asked whether it generalises. Keep the SPI-only baseline in the comparison.
4b. **Keep the form short.** A new model input must beat the current core set under leave-one-company-out before it joins `CORE_KEYS`, and needs a direction in `CORE_DIRECTION`.
5. **Never commit `data/raw/`.** It contains a private company/project key and an e-mail address.
6. **Assumptions live in config.yaml.** Keep carbon factors, liquidated damages and crash assumptions there, marked VERIFY; do not hard-code them.
7. **Pin PuLP below 3.** PuLP 3+/4 no longer ships the CBC solver; `optimizer.py` has a compatibility shim.
8. **BIM is optional.** Every feature except the 3D view, quantities and IFC export must work when `get_bim()` returns None. Test both modes (`tests/test_weather_schedule_bim.py`).
9. **Never block on the network.** Weather calls must fail soft (`available: false`) and stay out of the forecast unless a person confirms them.
10. **The live channel is in-process.** Run a single uvicorn worker. Changing that means moving `Broker` to Redis. Publish only from async handlers (event-loop thread). Never send SSE through GZip (`StreamSafeGZip` excludes `/stream`).
12. **Never report a network failure as a bug, or a bug as "server not reachable".** Use `report(e)` in app.js: it routes `e.network` to the connection banner and everything else to an error toast.
11. **Frontend needs no build step and must work offline.** Do not add CDN links; vendor any library into `web/vendor/` (Three.js and GSAP are vendored).
13. **Every company-owned row carries company_id and every query filters on it.** New tables follow the same rule. A wrong id must answer 404, never 403 (do not reveal that it exists).
14. **Project files only through the scope.** Use `projects.scope(project)` (or `config.use_scope`) around engine calls; never reintroduce a global "active" model or schedule.
15. **Every state-changing request needs the X-Revive-Request header** (conn.js and site.js add it). Do not exempt routes from `CsrfGuard`.
16. **Phones use the site token, never a row id.** `/api/site/<token>/*` is the only unauthenticated write path.
17. **Inline scripts are allowed only by hash.** The CSP hashes the import maps at start-up; any other inline `<script>` will be blocked. Put code in `web/assets/js/`.
18. **Current delay never uses the ML model.** It is the independent cross-check; keep it deterministic and keep its "indicative, not forensic" wording.

## Design language (frontend)
v6 "concrete and signal": the landing page (`landing.css`) is light concrete paper (`--paper`) with near-black ink, Archivo set heavy and condensed for headlines and figures, one construction-yellow signal colour used only as a flat fill under black text, and ink bands for rhythm; the 3D site sits in a framed daylight panel and runs one building from frame to handover (frame, risk scan and pink recovery, precast and glazed envelope, roof, crane out and landscaping; timings in `T` in landing.js). The workspace and the phone update page (`site.html`) keep the dark cockpit, cleaned up by `workspace.css` (loaded after cockpit.css; its `body.site` block styles the phone page): flat graphite, no grid texture, glows or gradients, labels at 6:1 or better, compact sheet titles, a `meter()` under delay figures (value, reference tick, the gap in the band colour), drawn empty states with the steps to start, and Back/Next links at the foot of every sheet (`sheetNav`). Every text pair must meet WCAG AA (4.5:1), including the printable evidence pack, which uses its own paper-safe risk colours (`BAND` in evidence.js). No Cinzel or Manrope.
v5 "site cockpit" (`web/assets/css/cockpit.css`, loaded after app.css and only overriding it): the workspace as a vehicle instrument cluster on a construction site. Vertical icon rail (a bottom dock on phones), graphite instrument bezels, construction-yellow ambient light, and on the Forecast sheet a cluster of arc gauges (`charts.gauge`) either side of an isometric building with leader-line callouts (`charts.building`) plus warning lights. Earlier layers below still define the base tokens.
The look is "site grade": structural-steel graphite with construction-yellow actions (v3).
- Archivo (variable width, `font-variation-settings:"wdth" N`) for headings and figures, Inter for body text, JetBrains Mono for codes and labels. All three are vendored variable fonts in `web/assets/fonts/`.
- Graphite surfaces (`--ink-*`, `--surface`), steel-blue `--cyan` for data linework; construction yellow (`--amber`) for primary actions only; hazard stripes (`--hazard`) as a small accent.
- Green/amber/orange/red for risk only, and survey-marking pink (`--mark`) only for the recovery plan.
- The REVIVE mark (`.rv`) is a structural frame (columns, floor slabs, an unfinished bay) on a yellow site-sign plate, with the recovery arrow rising out of the bay being built. Children: `rv-plate`, `rv-fl`, `rv-slab`, the `rv-ring` group (`rv-arc`, `rv-head`), then three `rv-bar` columns (keep them last). It is the logo, the rail emblem and the loader (`.rv.loading`); every copy and the favicons use identical markup. Add `.rv-go` to replay its draw-in (not `.play`, which is the BIM timeline button).
- 3D hover cards: `tilt.js`; mark a container `data-tilt` and its layers `data-z="40"`.
- Sentence-case copy, no all-caps labels in the workspace.

Keep charts as SVG in `charts.js`.

The vendored `ui-ux-pro-max` (`.claude/skills/ui-ux-pro-max/`, MIT, nextlevelbuilder/ui-ux-pro-max-skill) and `design-taste-frontend` (`.claude/skills/design-taste-frontend/`, MIT, Leonxlnx/taste-skill; its scratch files go to the git-ignored `.taste-skill/`) skills are advisory: use it for UX, accessibility and layout checks, but the design language above and ground rule 11 (no CDN links, vendored fonts) win over any palette, font, image or link they suggest.

## Useful next tasks
- Collect more completed projects, run `evaluate`, then merge and retrain.
- Replace `bim/sample_building.ifc` and `bim/schedule.csv` with the real case-study model and baseline programme.
- Calibrate crash rates and the liquidated-damages rate from the case-study contract.
- Pilot the live link on one real ongoing project: weekly updates from the site engineer, then collect a practitioner rating.
