# Data notes — read before quoting any number

## What the workbook contains (122 rows)

| Group | Rows | Notes |
|---|---|---|
| Contractor A records (C01) | 26 | project records |
| Contractor B records (C02) | 26 | project records; includes one terminated contract |
| Contractor C records (C03) | 24 | project records |
| External sources (EXT) | 12 | |
| **Hypothetical scenarios (SYN)** | **32** | coded SYN-01 to SYN-32 in the private key sheet; all "still ongoing"; disclose them |
| Uncoded | 2 | one has no completion date |

- **120 rows are used for training**: 81 completed and 39 still ongoing (for these the "completion" is a reported forecast).
- Excluded from the targets:
  - one row with no completion date;
  - one **terminated** contract (PRJ-052). Its termination date read as "finished 40% early". Leaving it in cut the completed-only R² from about 0.65 to 0.26.
- 89% of projects overran by more than 10%. A yes/no "delayed" label would be meaningless. REVIVE predicts the size of the overrun, plus the probability of exceeding 40%.

## Findings that shape the design
1. **Contract data alone does not predict overrun.** Cross-validated R² was about −0.1. REVIVE therefore forecasts at 25% and 50% of contract time.
2. **SPI at 75% looks back-calculated from the outcome.** Spearman correlation with final overrun is −0.985, so it is excluded.
3. **The hypothetical rows are unusually easy to predict.** Their SPI at 25% correlates −0.97 with the final overrun, against about −0.5 for contractors B and C. Within-group R² is 0.92. They raise the headline score; they do not lower it.
4. **Within-company overruns are very uniform.** Contractor C: standard deviation 6 points. R² is low inside such groups even though the error (about 4 points) is small, because there is little variation to explain.

## Production setting (from October 2026)

The examiner's question was fair: *can a model be trained on this kind of data?*
The answer after re-testing is **yes, but only a small one, and only on the
real completed projects**. Three changes follow from the evidence below.

1. **Train on the 81 real completed projects only.** The 32 hypothetical rows are
   made up and unusually easy to predict, and the 7 real ongoing projects have a
   reported forecast instead of an outcome. Both stay in the dataset, labelled,
   and the app scores them out-of-sample in the Benchmark sheet.
2. **Ask 10 questions at 25% and 13 at 50% instead of 36** (`schema.CORE_KEYS`).
   Every one comes from the contract or the monthly progress report.
3. **Use a regularised linear model** (ridge for time and cost, logistic for high
   risk) instead of XGBoost. Its explanation is exact: coefficient x standardised
   answer, which is the SHAP value of a linear model.

### How it was tested
- **Repeated 5-fold** cross-validation (5 folds x 3 repeats), as before.
- **Leave-one-company-out (LOCO)**: train on three of Contractor A, B, C and the
  external group, predict the fourth. Random folds put a contractor's projects on
  both sides of the split, so they flatter any model that learns a contractor's
  habits. LOCO answers "will it work for a company it has never seen?".
- Baselines: always guess the median, and a linear model on **SPI alone**.

### Results on the 81 real completed projects (time overrun, percentage points)

| At | Model | MAE | R² | LOCO MAE | LOCO R² | High-risk AUC | LOCO AUC |
|---|---|---|---|---|---|---|---|
| 25% | Median guess | 9.75 | — | — | — | — | — |
| 25% | **Linear, 10 core questions (production)** | **6.31** | **0.82** | **8.27** | **0.43** | **0.90** | **0.91** |
| 25% | Linear, SPI only | 6.81 | 0.74 | 7.55 | 0.58 | — | — |
| 25% | XGBoost, all 33 answers (old design) | 6.28 | 0.64 | 7.83 | 0.28 | 0.80 | 0.75 |
| 25% | XGBoost, 10 core questions | 6.57 | 0.63 | 7.73 | 0.29 | 0.82 | 0.82 |
| 50% | Median guess | 9.75 | — | — | — | — | — |
| 50% | **Linear, 13 core questions (production)** | **3.68** | **0.93** | **5.41** | **0.71** | **0.92** | **0.92** |
| 50% | Linear, SPI only | 3.99 | 0.91 | 4.56 | 0.83 | — | — |
| 50% | XGBoost, all 36 answers (old design) | 5.27 | 0.77 | 6.99 | 0.35 | 0.88 | 0.87 |
| 50% | XGBoost, 13 core questions | 4.72 | 0.79 | 6.59 | 0.38 | 0.89 | 0.88 |

Cost overrun (linear, core questions): R² **0.03** at 25% (MAE 4.4 points) and
**0.79** at 50% (MAE 2.4 points). **The 25% cost forecast is not better than the
average and must be presented as indicative only.** The old 0.82 came from the
hypothetical rows.

### What this means (say it this way in the defence)
- **On this data, a small model on the progress-report signals beats a big model
  on every survey answer.** More questions added noise, not skill, and the old
  XGBoost set collapses on an unseen contractor (LOCO R² 0.28 at 25%).
- **SPI carries most of the signal.** SPI alone transfers to a new contractor
  better than the 10/13-question model (LOCO R² 0.58 vs 0.43 at 25%). The other
  questions help inside a contractor and give the explanation its reasons (late
  IPCs, how the duration was set, design status), but they do not yet transfer.
  With only four company groups this comparison is itself noisy.
- **The high-risk classifier transfers well** (LOCO AUC 0.91 at 25%, 0.92 at 50%):
  "will this project overrun by more than 40%?" is the most dependable output.
- Old headline figures (R² 0.77/0.81 on all 120 records) were inflated by the
  hypothetical rows and by random folds. Do not quote them.

### Robustness (`python -m revive train --sensitivity`, linear core model)

| Data used | At | n | MAE | LOCO MAE | R² | LOCO R² | AUC |
|---|---|---|---|---|---|---|---|
| Real completed (production) | 25% | 81 | 6.20 | 8.27 | 0.82 | 0.43 | 0.90 |
| Real completed (production) | 50% | 81 | 3.61 | 5.41 | 0.93 | 0.71 | 0.92 |
| Real incl. ongoing | 25% | 88 | 9.39 | 11.05 | 0.66 | 0.54 | 0.90 |
| Real incl. ongoing | 50% | 88 | 7.79 | 9.80 | 0.76 | 0.67 | 0.92 |
| All records incl. hypothetical | 25% | 120 | 7.41 | 10.22 | 0.77 | 0.64 | 0.92 |
| All records incl. hypothetical | 50% | 120 | 5.92 | 8.69 | 0.84 | 0.74 | 0.93 |
| Real completed, SPI/CPI removed | 25% | 81 | 7.98 | 10.24 | 0.70 | 0.23 | 0.87 |
| Real completed, SPI/CPI removed | 50% | 81 | 7.26 | 9.16 | 0.76 | 0.35 | 0.88 |

### Limits that remain
- 81 projects from three contractors plus a few external records. That is a
  pilot study, not a model for the industry.
- 33 records mix project records with recall. SPI at 75% was already found to
  be back-calculated; SPI at 25% for Contractor A correlates −0.92 with the
  final overrun (Contractor C: −0.58), which should be checked against records.
- The way to stronger claims is more completed projects from more companies,
  scored with `evaluate` before they are merged.

## Earlier setting (kept for the record)
The first version trained XGBoost on all 120 records (incl. hypothetical and
ongoing) with all answers, validated with random folds only. Its figures:
MAE 6.79 / R² 0.765 at 25% and MAE 5.86 / R² 0.810 at 50%; AUC 0.907 / 0.943.

## What was tried to raise R² (and did not help)
All tested under the same repeated cross-validation:
- **Engineered features** (SPI drop 25→50%, value-certified gap, CPI−SPI gap): +0.00 to +0.01.
- **Monotone constraints on SPI/CPI**: −0.01 to +0.01.
- **Log-transformed target**: +0.03 at 25% on completed projects, but −0.03 to −0.12 elsewhere.

None was adopted. The remaining gains are in the data, not the model:
- more completed projects with a wide spread of outcomes;
- complete SPI/CPI records (PRJ-121 has none and is the worst-predicted completed project);
- checking the extreme external records (PRJ-084: 222% overrun).

## Next data step
Collect completed projects and score them before merging:

    python -m revive evaluate --file data/raw/new_projects.xlsx
