# Architecture and methods

## 1. Data
- **Source:** the FYDP survey workbook, sheet "FORM ORDER (88 cols)". `data.py` recognises columns by survey code (B12, D2_q1, E2, G4 ...), so re-worded questions still load.
- **Anonymisation:** these fields are dropped:
  - timestamps
  - consent text
  - e-mail
  - city
  - project code (except the source prefix C01/C02/C03/EXT/SYN)
  - the private key sheet
- **Targets:**
  - `time_overrun_pct = (C4 − C1) / (C2 − C1) − 1`, where C1 is commencement, C2 the original completion and C4 the actual or reported completion. Training clips this at 150%.
  - `cost_overrun_pct = C7 / C6 − 1`, clipped to −40..100%.
  - High risk = time overrun > 40% (36 of 121 projects).

## 2. Checkpoints (gates)
Each gate uses only information that exists at that point:

| Gate | Inputs |
|---|---|
| G25 (25% of contract time) | contract and site data at award (B1–B20, planned duration), first-quarter events (D1–D9 "by 25%"), SPI, CPI and value certified at 25% |
| G50 (50% of contract time) | everything in G25, plus SPI, CPI and value certified at 50% |

An award-only model was tested and **had no predictive value** (cross-validated R² ≈ −0.1). That is why there is no "at award" forecast.

## 3. Models
Three XGBoost models are trained per gate:
- time overrun: regression with a pseudo-Huber loss;
- cost overrun: regression;
- high risk: classifier.

Settings: shallow trees (depth 2, 600 rounds, learning rate 0.03) suit 121 records. Missing answers stay missing (NaN); XGBoost learns a default branch, so nothing is imputed.

**Validation:** 5-fold cross-validation repeated 3 times. Every project is predicted by models that never saw it (out-of-fold). The final models are then refitted on all records. Comparators on the same folds:
- median baseline;
- Random Forest;
- SVM (RBF);
- Ridge / logistic regression.

**80% range:** the 10th and 90th percentiles of the out-of-fold residuals, added to each forecast (empirical, split-conformal style).

## 4. Explanation (TreeSHAP)
`shap.TreeExplainer` gives exact Shapley values for tree ensembles. Contributions of one-hot columns are summed per question. The result:

base value (average prediction) + Σ contributions = this project's forecast, in percentage points.

The API test asserts this additivity.

## 5. Project Health Score (0–100)
A transparent composite index. It is **not** learned.
- PHS = 100 × (0.35·s_SPI + 0.25·s_CPI + 0.40·s_F) / Σ weights used.
- s_SPI and s_CPI rise linearly from 0.60 (score 0) to 1.00 (score 1).
- s_F = 1 − forecast overrun / 100%.

Recovery is triggered when PHS < 60, SPI < 0.80, CPI < 0.90, or the band is At risk or Critical.

## 6. From forecast to schedule
1. Run CPM on the baseline (bim/schedule.csv) to get the planned finish P.
2. The checkpoint is t0 = 0.25P or 0.50P. Work done follows Earned Schedule: ES = SPI × t0. This approximation uses cost-based SPI as a proxy for time-based SPI(t).
3. Remaining durations are scaled by one factor k so that the forecast finish equals P × (1 + forecast overrun). Network logic is unchanged.

## 7. Recovery LP
Minimise Z = Σ cᵢ yᵢ + LD · L, subject to:
- Sⱼ ≥ Sᵢ + dᵢ − yᵢ for every finish-to-start link;
- T ≥ Sᵢ + dᵢ − yᵢ for every activity;
- L ≥ T − D;
- 0 ≤ yᵢ ≤ uᵢ;
- Sᵢ ≥ t0;
- Σ cᵢ yᵢ ≤ B (optional budget cap).

Where:
- cᵢ is the crash cost per day and uᵢ = crash_max_days / duration × dᵢ;
- LD is liquidated damages per day and D the target completion.

The optimum buys a day only when it is cheaper than a day of liquidated damages. The time-cost curve re-solves the LP with a hard finish T ≤ target for a series of targets. The solver is CBC (open source) through PuLP. A unit test checks a textbook case with a known optimum.

## 8. BIM integration
**BIM → AI:**
- Gross floor area = upward faces of non-roof slabs.
- Storeys = non-roof storeys at or above ground.
- Planned duration comes from the linked schedule.

These fill the form ("Fill from BIM").

**AI → BIM:**
- Every element links to one activity, via its WBS_Code property or the storey + IFC class rule.
- Activity risk = project risk × exp(−total float / 12 days), where project risk = ½ P(high risk) + ½ min(1, overrun/80).
- Elements are coloured by activity risk, animated by schedule (4D), and highlighted when their activity is crashed.

**Write-back:** `Pset_REVIVE_Risk` is written on every linked element with:
- activity and status;
- planned, forecast and recovered finish;
- float and critical flag;
- risk score and level;
- crash days;
- project overrun and probability.

The file opens in Revit, Navisworks or any IFC viewer.

## 9. Sustainability
- **Avoided** (from days recovered): site diesel (L/day × 2.68 kgCO₂/L), time-related overheads and liquidated damages.
- **At risk** (exposure, not a saving): embodied carbon of concrete + rebar from the IFC × current rework share.

Every factor is in config.yaml and marked VERIFY.

## 10. Live monitoring (Server-Sent Events)
- A monitored project stores three things in SQLite:
  - the award-stage inputs;
  - a running state: time elapsed, cumulative event counts, ratings, and SPI/CPI/value certified;
  - a timeline of updates.
- The phone page posts an update. The server merges it into the state and re-scores it: model forecast, recovery LP at the actual time elapsed, and Monte Carlo. It then publishes the result to every dashboard on `/api/live/stream` (all projects) and to listeners on `/api/live/<id>/stream`.
- Delivery is made reliable in three layers:
  1. **Push:** one `EventSource` per dashboard on the all-projects stream. A named `ping` event every 10 s lets the browser detect a silent, dead connection and reopen it.
  2. **Catch-up:** every update has an id. The dashboard polls `/api/live/<id>/updates?after=<last id>` every 6 s and after every reconnect, and ignores ids it has already applied. An update sent while the connection was down is applied exactly once.
  3. **Phone-side queue:** with no signal, the phone stores the update and sends it when the server can be reached again.
- Presence: the phone posts `/api/live/<id>/presence` every 15 s; dashboards show "site phone connected". The phone's own stream (`?client=site`) is not counted as a dashboard.
- The server sends `Cache-Control: no-cache` for the dashboard and its scripts, and never gzips event streams (some Starlette versions buffer compressed streams).
- Mapping a live reading onto models trained at 25% and 50%:

| Reading | How it enters the model |
|---|---|
| Model choice | Before 50% elapsed the G25 model; from 50% the G50 model (the latest reading fills that checkpoint's slot) |
| Value certified | Rescaled to the checkpoint: cert_25 = cert × 25 / elapsed |
| Event counts | Per quarter of contract time: count × 25 / max(elapsed, 25), then banded like the survey |

- A single uvicorn worker is assumed (the push channel is in-process). For several workers, replace `Broker` with Redis pub/sub.

## 11. Monte Carlo finish-date risk
- 2,000 runs through the same CPM network, with two sources of variation:
  - the ML forecast error, resampled from the cross-validation residuals;
  - each remaining activity multiplied by a triangular factor (0.92 / 1.00 / 1.12, config `simulation`).
- Crash days from the LP are applied proportionally, giving P50/P80 finish and the chance of meeting the target with and without the plan.
- The simulated P50 sits later than the single-point forecast. This is the merge-event bias of parallel paths, a known effect in probabilistic scheduling.

## 12. Baseline schedule as the backbone, BIM as an optional layer
- Every calculation runs from the baseline schedule and the site reports:
  - forecast and explanation;
  - Earned Schedule status;
  - LP recovery;
  - Monte Carlo;
  - live monitoring and weather.
- The IFC model adds three things when it is connected:
  - quantities for the form and the carbon figures;
  - the 3D, 4D and recovery views;
  - the IFC write-back.
- With no model connected (`/api/bim/disconnect`, or `bim.start_with_demo_model: false`):
  - `get_bim()` returns None;
  - recovery reports `bim_connected: false`;
  - rework carbon is not computed;
  - the export answers with a clear error.
- **P6 import** (`schedule_import.py`) reads the TASK, TASKPRED and PROJWBS tables of an `.xer` export.
  - Durations are `target_drtn_hr_cnt / hours_per_day`.
  - LOE and WBS-summary tasks are skipped.
  - Non-FS links are treated as FS and lags are ignored (both counted in the report).
  - Crash data uses defaults that must be calibrated.

## 13. Live weather
- **Source:** Open-Meteo `/v1/forecast` with `daily=precipitation_sum,temperature_2m_max,temperature_2m_min,wind_speed_10m_max`, `past_days=14`, `forecast_days=16`, `timezone=auto`. Responses are cached for 30 minutes.
- **Lost-day rule** (config `weather.lost_day_rules`, marked VERIFY): rain ≥ 10 mm, wind ≥ 50 km/h, maximum temperature ≥ 45 °C, or minimum ≤ 2 °C.
- **Observed days enter the model as a suggestion.** The phone page pre-fills "working days lost to weather" with the lost days since the last update. The engineer confirms it, and it feeds the model's weather input.
- **Forecast days enter the schedule.** When enabled, each forecast lost day (offset 0 = today = checkpoint) adds one day to every remaining weather-sensitive activity on site that day. CPM is then re-run, before the LP and the Monte Carlo.
- **Possible double count.** The ML forecast already contains the average weather effect of the training projects, so adding the outlook is an explicit scenario (a tick box), not the default.
- **Network failures never block the app.** The API returns `available: false` with a reason, and manual entry continues.

## 14. API
See http://localhost:8000/docs when the server runs. Main endpoints:

| Endpoint | Purpose |
|---|---|
| `/api/predict` | Forecast for one project |
| `/api/recovery` | Schedule forecast and LP recovery plan |
| `/api/portfolio` | Dataset projects with out-of-fold forecasts, plus saved assessments |
| `/api/bim/geometry` | IFC geometry for the 3D viewer |
| `/api/bim/upload` | Upload an IFC model |
| `/api/bim/export` | Download the IFC with risk data |
| `/api/assessments` | Save and list assessments |
| `/api/model-card` | Performance, comparison and robustness results |
| `/api/insights` | Delay-cause ranking and dataset composition |
| `/api/live` | Create a monitored project or list them |
| `/api/live/{id}/update` | Send a site update (used by the phone page) |
| `/api/live/stream` | Server-Sent Events for every monitored project (used by dashboards) |
| `/api/live/{id}/stream` | Server-Sent Events for one project (`?client=site` from the phone page) |
| `/api/live/{id}/updates?after=` | Updates newer than an id, for catch-up after a dropped connection |
| `/api/live/{id}/presence` | The phone page reports it is open |
| `/api/ping` | Cheap liveness check used by the dashboard's reconnect logic |
| `/api/live/{id}/qr.svg` | QR code linking to the phone page |
| `/api/live/{id}/weather` | Site weather and suggested lost days since the last update |
| `/api/weather` | Weather outlook for a location |
| `/api/schedule/upload` | Upload the baseline schedule (`.xer` or `.csv`) |
| `/api/bim/disconnect`, `/api/bim/demo` | Run without a model, or connect the demo model |
