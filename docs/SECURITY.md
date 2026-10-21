# Security review and hardening (v2.0)

## How the review was done
1. **Static scan** with `bandit -r revive`. Before: 5 findings (1 high: MD5 used as a cache key; 4 medium: fixed-URL `urlopen`, a bind-all-interfaces comparison). After: **0**. The four remaining hits were reviewed and annotated `# nosec` with the reason (fixed URLs, a column type, a column-name whitelist).
2. **Manual review** of every route, upload path, database query and every place the frontend writes HTML. A scanner cannot see the problems that mattered most here, because they were design problems.
3. **A regression test for every fix** (`tests/test_security.py`, plus tenant tests in `test_live.py` and `test_weather_schedule_bim.py`).

## Findings and fixes

| # | Finding (v1.2) | Severity | Fix (v2.0) | Test |
|---|---|---|---|---|
| 1 | No authentication. The server listens on 0.0.0.0 for the phone link, so anyone on the same Wi-Fi could read, change or delete everything. | Critical | Company accounts: scrypt password hashing, 256-bit session tokens stored only as SHA-256, HttpOnly + SameSite=Lax cookies, expiry, admin/member roles | `test_api_needs_a_signed_in_user`, `test_session_cookie_flags_and_logout`, `test_only_admins_delete_projects_or_manage_the_team` |
| 2 | The live event stream sent every monitored project to every dashboard | Critical | Stream channels per company; a message goes only to its project's channel and its own company's channel | `test_broker_keeps_companies_apart` |
| 3 | Phone links were `/site/1`, `/site/2`: guessable, and anyone could post updates to any project | Critical | Unguessable 128-bit capability token per project; revocable from the dashboard; numeric ids rejected | `test_live_api_token_links_and_qr`, `test_rotating_the_link_revokes_the_old_one` |
| 4 | The active IFC model and schedule were global: one user's upload changed what everyone saw | Critical | Files belong to a project, stored under `data/workspaces/c<company>/p<project>/`; every request runs in that project's scope (`config.use_scope`) | `test_app_runs_with_and_without_bim`, `test_schedule_upload_is_per_project_and_validated` |
| 5 | No cross-site request forgery protection | High | Every state-changing `/api/` request must carry `X-Revive-Request: 1` and, if the browser sends an Origin, it must be this server | `test_csrf_header_and_origin_are_enforced` |
| 6 | Uploads: no size limit, extension check only, user-chosen file names, and a rejected CSV re-upload could delete the working schedule | High | Streaming size caps (config), magic-byte checks (IFC = ISO-10303-21, XER = ERMHDR), fixed server-side names, validation on a temporary copy before anything is replaced | `test_uploads_are_typed_and_size_limited`, `test_schedule_upload_is_per_project_and_validated` |
| 7 | No security headers; interactive API docs public | Medium | Content-Security-Policy (scripts from this server only, inline scripts by hash, no eval), `frame-ancestors 'none'`, nosniff, referrer policy (no-referrer on the phone page so the token never leaks), `no-store` on API answers, HSTS over HTTPS; `/docs` off unless `security.api_docs` | `test_security_headers_and_no_docs` |
| 8 | Saved assessments trusted the result sent by the browser (a forged "On track" could be stored and alerted on) | Medium | The server re-scores the inputs and ignores any client result | `test_saving_an_assessment_is_rescored_by_the_server` |
| 9 | No brute-force protection on anything | Medium | Sliding-window limits: login per IP and per e-mail (5 failures lock the e-mail for 15 min), sign-up per IP, phone updates per link, heavy endpoints per user | `test_login_is_throttled` |
| 10 | Unbounded request bodies, unknown model keys accepted, weather cache keyed by user coordinates grew without limit, phone-device table unbounded | Medium | Pydantic limits on every field, unknown keys dropped, JSON body cap, coordinates validated, bounded caches | `test_bodies_are_bounded_and_validated` |
| 11 | Project names went into e-mail headers unfiltered | Low | Control characters stripped; alerts go only to the owning company's users; per-company outbox | (unit-level) |
| 12 | MD5 used to key a geometry cache shared by all companies (collisions are practical) | Low | SHA-256 | bandit |
| 13 | Raw exception text returned to the browser | Low | Generic messages for unexpected errors (details stay in the server log); validation messages kept | (review) |
| 14 | Docker image ran as root | Low | Non-root `revive` user | (review) |

Already good in v1.2 and kept: every SQL query is parameterised; the frontend escapes every user string before writing HTML; models are stored as XGBoost JSON (no pickle); secrets come from environment variables.

## Residual risks (state these honestly)
- **Plain HTTP on a LAN.** Cookies and phone tokens cross the network in clear text unless REVIVE sits behind HTTPS (a reverse proxy or a tunnel). For anything beyond a demo, put it behind HTTPS and set `security.cookie_secure: true`.
- **One process, SQLite.** Right for a pilot or a defence; a hosted multi-company service needs Postgres, backups and a shared event bus (the live channel is in-process).
- **IFC parsing runs in the server process.** The size cap limits abuse, but a crafted file could still exhaust memory; a production deployment would parse uploads in a separate worker.
- **No e-mail verification or self-service password reset.** Admins add members; `python -m revive reset-password` resets a password from the server console.
- **Dependency vulnerabilities were not audited online** (the build machine had no access to the advisory database). Run `pip install pip-audit && pip-audit -r requirements-lock.txt` before deploying.

## Deploying safely
1. Keep `security.allow_registration: true` only while companies are signing up; then set it to `false` and add companies with `python -m revive create-company`.
2. Serve over HTTPS for anything outside a trusted network; set `cookie_secure: true` behind the proxy.
3. Leave `security.api_docs: false` on shared networks.
4. Back up `data/app.db` and `data/workspaces/`. Never commit them (`.gitignore` already excludes them).
