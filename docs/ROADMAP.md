# Roadmap: from this repository to the final defence

Each step says what to do, how to do it, and what "done" looks like. Steps 1–3 take a day; the rest run in parallel over the remaining weeks.

## 1. Run it and learn it (day 1)
- Run `setup.bat`, then `run.bat`, then `python -m pytest -q`. Done = 16 tests pass and the dashboard opens.
- Click through all seven sheets with each example project.
- Read `docs/ARCHITECTURE.md` until you can explain every step without notes.

## 2. Put it under version control (day 1)
- Create a **private** GitHub repository.
- Run `git init`, `git add .`, `git commit -m "REVIVE v1"`, then push. `.gitignore` already keeps the raw workbook out.
- Give your three teammates access and agree who owns what:

| Area | Files |
|---|---|
| BIM | `bim/`, `revive/bim.py` |
| Data and model | `revive/data.py`, `revive/modeling.py` |
| Optimiser and sustainability | `revive/optimizer.py`, `revive/simulation.py`, `revive/sustainability.py` |
| Dashboard | `web/` |

## 3. Rehearse the live link (day 2)
- Start monitoring a project, then send updates from your phone over a hotspot. Fix any firewall prompt.
- Done = the projector reacts within about a second, three times in a row.

## 4. Replace the demo BIM with your case study (weeks 1–3)
1. In Revit, add a shared parameter `WBS_Code` and fill it with your activity ids.
2. Export IFC4 with user-defined property sets.
3. Export the baseline programme from Primavera P6 as `.xer` and upload it on the Recovery sheet. MS Project users export to the `bim/schedule.csv` columns instead. Set crash limits and crash costs per day with a QS or planner, and the liquidated-damages rate from the contract.
4. Upload both on the Digital twin sheet.

Done = every structural element is linked, and the planned months match the contract.

## 5. Get the external test data (weeks 1–4)
- Collect **completed** projects only, through the same form.
- Run `python -m revive evaluate --file data/raw/new.xlsx` **before** merging. Keep the report in `reports/`.
- Done = at least 20 new completed projects scored, and the MAE compared against the median baseline.
- Only then merge and retrain: `python -m revive ingest` and `python -m revive train --sensitivity`.

## 6. Verify every assumption (week 2)
- Every `VERIFY` line in `config/config.yaml` gets a cited source (RICS / ICE / DEFRA edition, contract LD clause, site overhead from a QS).
- Record each source in the report's assumptions table.

## 7. Pilot on one live project (weeks 3–6)
- A site engineer sends weekly updates through the phone page for 4+ weeks.
- At the end, run the 5-point Likert evaluation from your proposal (usefulness, clarity, recovery practicality, trust) with 5–8 practitioners.
- Done = a real trajectory in the app and signed feedback.

## 8. Write the report (weeks 4–8)
Use these ready-made sources:

| Report content | Source |
|---|---|
| Methodology | `docs/ARCHITECTURE.md` |
| Data and results | `docs/DATA_NOTES.md` |
| Figures | `reports/figures/` |
| Comparison and robustness tables | `reports/*.csv` |

State the limitations yourself before the examiners do: hypothetical rows, ongoing projects, no award-stage prediction, and single-worker live channel.

## 9. Optional public link (week 6)
- Deploy to Hugging Face Spaces (`docs/DEPLOY.md`) for the conference paper, LinkedIn and your master's applications.
- Keep the offline laptop version for the defence.

## 10. Mock defence (last 2 weeks)
- Run `docs/DEFENCE_GUIDE.md` twice with a teammate playing a hostile examiner.
- Time the 7-minute script. Practise the live moment until it cannot surprise you.

## Using Claude Code along the way
Open the folder in Claude Code and give it one task at a time, for example:
- "Replace bim/schedule.csv with this P6 export and map the columns."
- "/evaluate-new-data data/raw/new.xlsx"
- "Add a weekly trajectory export to Excel for the report."

Claude Code reads `CLAUDE.md` first, which keeps it inside the project's rules: no leakage features, no fabricated numbers, and hypothetical data stays labelled.
