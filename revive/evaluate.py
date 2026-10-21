"""
External test: score NEW projects the model has never seen.

    python -m revive evaluate --file data/raw/new_projects.xlsx

Rows that are identical to a training record are detected and excluded from the
metrics, so re-submitted projects cannot inflate the result.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, r2_score, roc_auc_score

from .config import load_config, reports_dir
from .data import clean, load_clean, read_raw
from .inference import get_predictor
from .schema import FIELDS

KEYS = [f["key"] for f in FIELDS]


def _fingerprint(row) -> str:
    parts = []
    for k in KEYS:
        v = row.get(k)
        parts.append("" if v is None or (isinstance(v, float) and np.isnan(v)) else str(v).strip().lower())
    return "|".join(parts)


def evaluate_external(file: str | Path, sheet: str | None = None) -> dict:
    raw = read_raw(file, sheet)
    df, quality = clean(raw, id_prefix="NEW")
    try:
        seen = {_fingerprint(r) for _, r in load_clean().iterrows()}
    except FileNotFoundError:
        seen = set()
    P = get_predictor()
    thr = load_config()["training"]["high_risk_threshold_pct"]
    rows = []
    for _, r in df.iterrows():
        inputs = {k: (None if pd.isna(r.get(k)) else r.get(k)) for k in KEYS}
        res = P.predict(inputs)
        rows.append({
            "project_id": r["project_id"], "gate": res["gate"], "duplicate_of_training": _fingerprint(r) in seen,
            "predicted_time_overrun_pct": res["time_overrun_pct"], "range_low": res["time_interval_pct"][0],
            "range_high": res["time_interval_pct"][1], "high_risk_probability": res["high_risk_probability"],
            "band": res["band"]["name"], "actual_time_overrun_pct": r.get("time_overrun_pct"),
            "status": r.get("status"),
        })
    out = pd.DataFrame(rows)
    scored = out[(~out["duplicate_of_training"]) & out["actual_time_overrun_pct"].notna()]
    metrics = {"n_rows": int(len(out)), "n_duplicates_excluded": int(out["duplicate_of_training"].sum()),
               "n_scored": int(len(scored))}
    if len(scored):
        y = scored["actual_time_overrun_pct"].clip(upper=load_config()["training"]["time_overrun_clip_pct"])
        p = scored["predicted_time_overrun_pct"]
        metrics["time_MAE"] = round(float(mean_absolute_error(y, p)), 2)
        metrics["median_baseline_MAE"] = round(float(np.mean(np.abs(y - y.median()))), 2)
        metrics["within_80pct_range"] = round(float(((y >= scored["range_low"]) & (y <= scored["range_high"])).mean()), 3)
        if len(scored) >= 3:
            metrics["time_R2"] = round(float(r2_score(y, p)), 3)
        yb = (scored["actual_time_overrun_pct"] > thr).astype(int)
        if 0 < yb.sum() < len(yb):
            metrics["risk_AUC"] = round(float(roc_auc_score(yb, scored["high_risk_probability"])), 3)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out.to_csv(reports_dir() / f"external_test_{stamp}.csv", index=False)
    (reports_dir() / f"external_test_{stamp}.json").write_text(json.dumps({"metrics": metrics, "data_quality": quality},
                                                                           indent=2, default=str))
    return {"metrics": metrics, "predictions": out}
