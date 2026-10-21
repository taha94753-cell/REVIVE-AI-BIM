Retrain REVIVE and report what changed.

1. Run `python -m revive ingest` if a new workbook is in data/raw/, then `python -m revive train --sensitivity`.
2. Compare models/model_card.json with the previous version (git diff): time MAE, R2, high-risk AUC per gate, and the top drivers.
3. Run `python -m pytest -q`.
4. Summarise the changes in plain language. Never describe in-sample numbers as accuracy; only the cross-validated figures in the model card count.
