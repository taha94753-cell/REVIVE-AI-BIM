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

## Cross-validated performance (production setting: all 120 records)

| Checkpoint | Model | Time error (MAE, pts) | R² | High-risk AUC | F1 |
|---|---|---|---|---|---|
| 25% | Median baseline | 16.22 | — | — | — |
| 25% | **XGBoost (production)** | **6.79** | **0.765** | **0.907** | **0.738** |
| 25% | Random Forest | 7.49 | 0.698 | 0.929 | 0.721 |
| 25% | SVM (RBF) | 10.41 | 0.452 | 0.891 | 0.698 |
| 25% | Ridge / logistic | 12.45 | 0.616 | 0.904 | 0.716 |
| 50% | Median baseline | 16.22 | — | — | — |
| 50% | **XGBoost (production)** | **5.86** | **0.810** | **0.943** | **0.811** |
| 50% | Random Forest | 5.76 | 0.804 | 0.946 | 0.831 |
| 50% | SVM (RBF) | 9.53 | 0.499 | 0.924 | 0.836 |
| 50% | Ridge / logistic | 10.04 | 0.722 | 0.920 | 0.806 |

Cost overrun R² is 0.82 at 25% and 0.94 at 50%.

## Robustness checks (`python -m revive train --sensitivity`, 2 CV repeats)

| Data used | At | n | Time error | Median guess | R² | AUC |
|---|---|---|---|---|---|---|
| All records (production) | 25% | 120 | 6.90 | 16.22 | 0.752 | 0.906 |
| All records (production) | 50% | 120 | 6.06 | 16.22 | 0.798 | 0.942 |
| Completed projects only | 25% | 81 | 6.27 | 9.75 | 0.654 | 0.829 |
| Completed projects only | 50% | 81 | 5.31 | 9.75 | 0.763 | 0.875 |
| Without hypothetical rows | 25% | 88 | 8.55 | 13.68 | 0.649 | 0.856 |
| Without hypothetical rows | 50% | 88 | 6.21 | 13.68 | 0.804 | 0.891 |
| All records, SPI/CPI removed | 25% | 120 | 8.56 | 16.22 | 0.713 | 0.826 |
| All records, SPI/CPI removed | 50% | 120 | 7.42 | 16.22 | 0.784 | 0.860 |

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
