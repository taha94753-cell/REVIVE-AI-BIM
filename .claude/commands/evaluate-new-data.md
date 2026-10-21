Score newly collected projects as an external test set.

1. Ask for the path of the new workbook (same survey form) if it is not given: $ARGUMENTS
2. Run `python -m revive evaluate --file <path>`.
3. Report the metrics from the newest reports/external_test_*.json: rows scored, duplicates of training data excluded, MAE against the median baseline, share of actual values inside the 80% range, and AUC if both classes are present.
4. Do not retrain on the new data before this report is saved; after it is saved, offer to merge the data and retrain.
