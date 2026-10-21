"""Descriptive analysis of the survey: delay-cause ranking (RII) and dataset composition."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .schema import CAUSE_FAMILY, DELAY_CAUSES

SOURCE_LABELS = {"C01": "Contractor A records", "C02": "Contractor B records", "C03": "Contractor C records",
                 "EXT": "External sources", "SYN": "Hypothetical scenarios", "UNCODED": "Unlabelled"}


def relative_importance(df: pd.DataFrame) -> list[dict]:
    """Relative Importance Index: RII = sum(W) / (A x N), W on a 1-5 scale, A = 5.
    'NE' (not experienced) answers are excluded from N."""
    rows = []
    for code, label in DELAY_CAUSES.items():
        if code not in df:
            continue
        v = pd.to_numeric(df[code], errors="coerce").dropna()
        if len(v) == 0:
            continue
        rows.append({"code": code, "label": label, "family": CAUSE_FAMILY[code],
                     "rii": round(float(v.sum() / (5 * len(v))), 3), "n": int(len(v))})
    rows.sort(key=lambda r: -r["rii"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def composition(df: pd.DataFrame) -> dict:
    src = df["source_group"].fillna("UNCODED").map(lambda s: SOURCE_LABELS.get(s, s)).value_counts()
    bins = [-np.inf, 0, 10, 20, 30, 40, 50, 75, 100, np.inf]
    labels = ["< 0", "0-10", "10-20", "20-30", "30-40", "40-50", "50-75", "75-100", "> 100"]
    hist = pd.cut(df["time_overrun_pct"].dropna(), bins=bins, labels=labels).value_counts().reindex(labels).fillna(0)
    causes = df.get("main_delay_cause", pd.Series(dtype=str)).dropna().value_counts()
    return {
        "n_records": int(len(df)),
        "n_with_outcome": int(df["time_overrun_pct"].notna().sum()),
        "by_source": [{"label": k, "n": int(v)} for k, v in src.items()],
        "by_status": {str(k): int(v) for k, v in df["status"].fillna("Unknown").value_counts().items()},
        "by_type": {str(k): int(v) for k, v in df["project_type"].fillna("Unknown").value_counts().items()},
        "overrun_histogram": [{"bin": k, "n": int(v)} for k, v in hist.items()],
        "main_causes": [{"label": k, "n": int(v)} for k, v in causes.items()],
        "median_time_overrun_pct": round(float(df["time_overrun_pct"].median()), 1),
        "median_cost_overrun_pct": round(float(df["cost_overrun_pct"].median()), 1),
        "share_over_10pct": round(float((df["time_overrun_pct"] > 10).mean()), 3),
    }


def insights(df: pd.DataFrame) -> dict:
    return {"rii": relative_importance(df), "composition": composition(df)}
