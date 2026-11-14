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
- **E-mail codes need a mail server.** Sign-up and password reset send a six-digit code. With `SMTP_HOST` set it is e-mailed; without it the code is printed in the server window and written to `data/outbox/account/`, which only suits a laptop install where the person signing up can see that window. Members added by an admin are not asked for a code (the admin vouches for them).
- **Sign-up says when an e-mail is already registered** (asked for by the owner, for usability). That lets someone test whether an address has an account; sign-up is rate limited per network to keep it slow. The forgotten-password form gives the same answer for every address.
- **Dependency vulnerabilities were not audited online** (the build machine had no access to the advisory database). Run `pip install pip-audit && pip-audit -r requirements-lock.txt` before deploying.

## Account hardening (v2.1)
| What | How | Test (`tests/test_account.py`) |
|---|---|---|
| E-mail confirmed before a workspace exists | `POST /api/auth/register` parks the sign-up (password already hashed) and sends a code; `POST /api/auth/verify` creates the company. Codes: six digits, stored as SHA-256 bound to the e-mail and purpose, 10 minutes, single use, dropped after five wrong tries, guesses and sends rate limited | `test_signup_needs_the_emailed_code`, `test_code_dies_after_five_wrong_tries_and_a_resend_replaces_it`, `test_expired_code_is_refused`, `test_codes_are_rate_limited` |
| Forgotten password | `POST /api/auth/forgot` (same answer for every address) then `POST /api/auth/reset`; a reset signs the user out everywhere | `test_forgot_password_resets_and_signs_out_everywhere` |
| Sign-in does not outlive the visit | Session cookie without Max-Age (ends with the browser); the server also ends a session after 30 idle minutes or 12 hours | `test_sign_in_ends_with_the_browser_and_after_idle_time` |
| Bots | Hidden honeypot field on sign-up, on top of the rate limits and the e-mail code | `test_honeypot_field_gets_a_fake_success` |
| Weak passwords | Common passwords and all-digit passwords refused | `test_registered_email_is_reported_and_weak_passwords_refused` |
| Behind an HTTPS proxy the app believed it was on HTTP | `REVIVE_TRUST_PROXY=1` (set in `render.yaml` and the Space image): Secure cookie, HSTS, rate limits per real visitor. Off elsewhere, so a direct client cannot fake its address | `test_trusted_proxy_sets_secure_cookie_and_hsts_only_when_switched_on` |
| Deleting an account | `POST /api/auth/delete-account`, confirmed with the password (wrong tries count toward the sign-in lockout). A member or one of several admins removes only themselves; the last person removes the whole workspace (projects, uploads, site links, assessments); the only admin with other people is refused until they hand over | `test_member_deletes_only_their_own_account`, `test_only_admin_must_hand_over_before_leaving`, `test_last_person_takes_the_workspace_with_them`, `test_delete_account_needs_a_session_and_the_csrf_header` |
| Public pages | `/privacy`, `/terms`, a 404 page for people (JSON for the API), `robots.txt`, `sitemap.xml`; the `server` header is no longer sent | `test_public_pages_robots_sitemap_and_404` |

## Deploying safely
1. Keep `security.allow_registration: true` only while companies are signing up; then set it to `false` and add companies with `python -m revive create-company`.
2. Serve over HTTPS for anything outside a trusted network. Behind a single HTTPS proxy set `REVIVE_TRUST_PROXY=1`; never set it on a server that clients reach directly.
2a. Set `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD` and `MAIL_FROM` (environment, never the repository) so codes reach people by e-mail, and `app.contact_email` in config.yaml for the privacy and terms pages.
3. Leave `security.api_docs: false` on shared networks.
4. Back up `data/app.db` and `data/workspaces/`. Never commit them (`.gitignore` already excludes them).
