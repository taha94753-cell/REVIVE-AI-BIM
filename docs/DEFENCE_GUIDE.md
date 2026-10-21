# Defence guide

## What wins
Juries remember a product that answers a question they pose live. They also remember a team that knows exactly where its evidence stops. Aim for both.

1. **Live demo on a project the jury invents.** Ask a panel member for a project type and two problems ("a hospital with late payments and design changes"). Enter it at the 25% checkpoint and show the waterfall.
2. **The BIM loop both ways.**
   - "Fill from BIM" pulls floor area, storeys and duration from the IFC.
   - Download the IFC with risk data, open it in Revit or Navisworks and select a column: `Pset_REVIVE_Risk` is there.
   - Rehearse this. It is the single strongest proof that the integration is real.
3. **The recovery in money.** "Accelerate these activities for PKR X M, finish N days earlier, pay PKR Y M less in liquidated damages." Then show the time-cost curve.
4. **One real practitioner.** Get one project manager to use it on a live project and rate it. That rating is worth more than any metric.
5. **Disclose limits before being asked.** Put the hypothetical rows, ongoing projects and completed-only result on one Evidence slide.

## The live moment (rehearse this until it is boring)
1. Bring a phone hotspot and connect the laptop to it, so the venue Wi-Fi does not matter.
2. Start monitoring the jury's project on the Live sheet and put the QR code on the projector.
3. Hand a panel member the phone: "You are the site engineer. Two IPCs were paid late and the rebar arrived late. Tap them and send."
4. Everyone watches the projector:
   - the trajectory jumps;
   - the feed shows their name;
   - the building recolours;
   - the recovery plan and finish-date distribution move.
5. Scroll to the waterfall: "This is why: late payments added N points."

If the network fails, open the phone link in a second browser window on the laptop. The flow is identical.

## Seven-minute demo script

| Time | Step |
|---|---|
| 0:00 | Hero: the building assembles and turns red where the forecast risk sits. One sentence on the problem. |
| 0:40 | Portfolio: 122 projects, cross-validated forecasts, hypothetical rows labelled. |
| 1:20 | Assess: a jury-invented project at 25%. Forecast, 80% range, health score, trigger. |
| 2:30 | Waterfall: "Late IPC payments added N points; SPI took off M." |
| 3:00 | Live: QR code on screen, a panel member sends a site update from the phone, and the dashboard reacts. |
| 3:20 | Digital twin: Risk, then Build sequence (play baseline vs forecast), then Recovery. Select a critical column. |
| 4:30 | Recovery: optimise, then change the LD rate to show the plan changes. Explain the objective in one line. |
| 5:30 | Impact: days, PKR and CO₂ avoided, with the assumptions table. |
| 6:15 | Evidence: metrics vs median guess, robustness table, limitations. |
| 6:50 | Close: next step is the external test on new completed projects. |

## Likely questions and honest answers

- **Why AI? Why not SPI alone?**
  - SPI is the strongest input, but the model adds first-quarter events and contract conditions.
  - With SPI/CPI removed, R² is still 0.71–0.78 and AUC 0.83–0.86. The model also returns a probability, a range and a reason for each forecast.

- **Why not predict at contract award?**
  - We tested it. Award-stage data had no predictive value (R² ≈ −0.1). We report that as a finding rather than sell a model that does not work.

- **You trained on all data. How do you know it generalises?**
  - Repeated 5-fold cross-validation: every project is predicted by models that did not see it.
  - New completed projects are the external test, and `evaluate` excludes duplicates automatically.

- **What about the hypothetical rows?**
  - 32 records, labelled throughout. Without them, R² is 0.65 at 25% and 0.80 at 50%; on completed projects only it is 0.65 and 0.76.

- **Why XGBoost and not Random Forest?**
  - XGBoost has the higher R² at both checkpoints; Random Forest's error is 0.1 pts lower at 50%, which is within cross-validation noise.
  - Native missing-value handling, exact TreeSHAP with missing data, and portable model files.

- **Is the BIM just a viewer?**
  - No. Quantities flow into the model.
  - Risk is computed per activity from the schedule network (float).
  - The recovery acts on those activities, and the results are written into the IFC as a property set.

- **Is the LP just a textbook example?**
  - It is the standard CPM time-cost trade-off. It is driven by the ML forecast and priced against liquidated damages.
  - A unit test checks it against a known optimum. Crash rates come from the schedule file and must be calibrated for a real project.

- **Where do the carbon factors come from?**
  - config.yaml, each marked VERIFY. Cite the source edition you actually used (RICS WLCA / ICE / DEFRA).
  - Rework carbon is shown as exposure, not savings.

- **Is it really live?**
  - Yes. Updates are pushed to every open dashboard the moment site staff send them. They are not polled, and there is no refresh.
  - The model itself was trained on 25% and 50% snapshots; readings in between are mapped to the nearest checkpoint, and the app states this.
  - It is live monitoring driven by site reports, not sensor telemetry. Say exactly that.

- **Does it need a BIM model?**
  - No. It runs on the baseline schedule and site reports. Disconnect the model live to prove it.
  - BIM adds the visual layer, the quantities and the IFC write-back.

- **How is weather handled?**
  - Live data from Open-Meteo. Observed lost days are suggested to the site engineer, who confirms them before they enter the model.
  - Forecast lost days can be added to weather-sensitive activities as a scenario.
  - The lost-day thresholds are stated in the config. Because the model already contains average weather effects, the outlook is an option, not a default.

- **Where does the finish-date probability come from?**
  - 2,000 simulations using the model's own cross-validation errors plus activity-level variation.
  - The spread is measured model error, not an invented number. The activity spread is a stated assumption in config.yaml.

## Do not claim
- Accuracy percentages on the training data.
- "Predicts delay before construction."
- "Real-time."
- Carbon figures without the cited factors.
- That the demo IFC is your case-study building. It is an illustrative model until you replace it.


## v2.0: questions on current delay and security

**"How do you measure current delay without ML?"** Earned Schedule. From the baseline CPM we build the planned-progress curve PV(t). The site reports SPI (or value certified), so EV = SPI x PV(AT). Earned schedule ES is the day the plan reached that EV. Delay to date = AT - ES, confirmed by re-running CPM on the remaining work from the status date (they agree exactly when only SPI is known; a test checks it).

**"Why is SPI(t) different from SPI?"** Cost-based SPI tends to 1.0 at the end of every project, even a late one; SPI(t) = ES/AT stays honest about time. That is Lipke's argument for Earned Schedule.

**"Your forecast and your current delay disagree. Which is right?"** Neither alone. Current delay is a measurement; the to-plan finish is a best case; current pace extrapolates performance; the ML forecast adds what similar projects did after similar first quarters. A large gap between pace and ML means the model expects deterioration (or recovery) that the current pace does not show; that is the conversation to have with the site.

**"Is the window apportionment a delay claim?"** No, and the app says so. Weather days count as days; the remaining slip is shared by event count between client-side and contractor-side events. It flags windows worth a notice and evidence; a forensic analysis (SCL Protocol, AACE 29R-03) would need as-built activity data.

**"How do you stop one company seeing another's data?"** Every row carries company_id and every query filters on it; another company's ids return 404. The live stream is per company. Uploads live in per-company folders. Tests try every route with a second company.

**"What if a phone with the site link is lost?"** Reissue the link on the Live site sheet: the old token stops working immediately (tested).

**"Is it production-secure?"** For a pilot on a site network, yes with HTTPS. The documented residual risks: HTTP on a LAN, single process with SQLite, IFC parsing in-process, no e-mail verification (docs/SECURITY.md).
