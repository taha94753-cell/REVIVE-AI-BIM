"""
Feature encoding: human-readable answers -> numeric matrix for XGBoost.

* category  -> one-hot columns, e.g. "project_type=Highway"
* ordinal   -> one number (band midpoint or rank); "Don't know" -> NaN
* number    -> as entered; blank -> NaN

Missing values are left as NaN on purpose: XGBoost learns a default branch
direction for missing data, so no imputation (and no invented values) is needed.
The same function encodes the training table and a single web-form submission,
which guarantees identical columns at training and inference time.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import load_config
from .schema import FIELD_BY_KEY, fields_for_stages, match_option, ordinal_value


def gate_fields(gate: str) -> list[dict]:
    stages = load_config()["gates"][gate]["stages"]
    return fields_for_stages(stages)


def gate_columns(gate: str) -> list[str]:
    cols = []
    for f in gate_fields(gate):
        if f["kind"] == "category":
            cols += [f"{f['key']}={opt}" for opt in f["options"]]
        else:
            cols.append(f["key"])
    return cols


def column_to_field(col: str) -> str:
    return col.split("=", 1)[0]


def _as_float(v):
    try:
        if v is None or v == "":
            return np.nan
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def encode(df: pd.DataFrame, gate: str) -> pd.DataFrame:
    """Encode a DataFrame whose columns are schema keys holding labels/numbers."""
    data = {}
    n = len(df)
    for f in gate_fields(gate):
        key = f["key"]
        col = df[key] if key in df else pd.Series([None] * n, index=df.index)
        if f["kind"] == "category":
            labels = col.map(lambda v: match_option(f, v))
            for opt in f["options"]:
                data[f"{key}={opt}"] = (labels == opt).astype(float).where(labels.notna(), np.nan)
        elif f["kind"] == "ordinal":
            labels = col.map(lambda v: match_option(f, v))
            data[key] = labels.map(lambda lab: ordinal_value(f, lab) if lab else np.nan).astype(float)
        else:
            data[key] = col.map(_as_float).astype(float)
    X = pd.DataFrame(data, index=df.index)
    return X[gate_columns(gate)]


def encode_one(inputs: dict, gate: str) -> pd.DataFrame:
    return encode(pd.DataFrame([inputs]), gate)


def display_value(key: str, inputs: dict) -> str:
    """Readable value of a field for explanation panels."""
    f = FIELD_BY_KEY[key]
    v = inputs.get(key)
    if v is None or v == "" or (isinstance(v, float) and np.isnan(v)):
        return "not given"
    if f["kind"] == "number":
        unit = f.get("unit", "")
        v = float(v)
        txt = f"{v:,.0f}" if float(v).is_integer() or abs(v) >= 10 else f"{v:,.2f}"
        return f"{txt}{unit}" if unit.startswith("%") else f"{txt} {unit}".strip()
    return str(match_option(f, v) or v)
