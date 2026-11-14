"""
Random forest production model (training.model: forest in config.yaml).

Why a forest: on this dataset it has the lowest error of the models compared, on random folds and
on an unseen contractor. It is trained with scikit-learn and stored as plain JSON (every tree as
arrays), so loading a model never unpickles anything.

Explanations
  Each forecast is split into (average prediction) + one contribution per input, and the parts add
  up exactly. The contributions are SHAP values (path-dependent TreeSHAP), computed by the shap
  library straight from the stored tree arrays, so they match what shap gives for the scikit-learn
  forest itself. A blank answer is filled with the training median before the trees are read.

Missing values are filled with the training median of each column (0 for a column that was always
blank), the same rule as the Random Forest row of the model comparison.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import shap
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

from .config import load_config

FORMAT = "revive-forest-1"


class ForestModel:
    def __init__(self, kind: str = "reg", n_estimators: int | None = None, min_samples_leaf: int | None = None,
                 random_state: int | None = None):
        cfg = load_config()["training"]
        p = cfg.get("forest") or {}
        self.kind = kind
        self.n_estimators = int(n_estimators or p.get("n_estimators", 400))
        self.min_samples_leaf = int(min_samples_leaf or p.get("min_samples_leaf", 2))
        self.random_state = cfg["random_state"] if random_state is None else random_state
        self.columns: list[str] = []
        self.fill = np.zeros(0)
        self.trees: list[dict] = []
        self._explainer = None

    # ------------------------------------------------------------------ fit
    def _matrix(self, X: pd.DataFrame) -> np.ndarray:
        A = X[self.columns].to_numpy(float) if isinstance(X, pd.DataFrame) else np.asarray(X, float)
        return np.where(np.isnan(A), self.fill, A)

    def fit(self, X: pd.DataFrame, y) -> "ForestModel":
        self.columns = list(X.columns)
        A = X.to_numpy(float)
        with np.errstate(all="ignore"):
            med = np.nanmedian(A, axis=0) if len(A) else np.zeros(A.shape[1])
        self.fill = np.where(np.isnan(med), 0.0, med)
        A = np.where(np.isnan(A), self.fill, A)
        y = np.asarray(y, float)
        Model = RandomForestRegressor if self.kind == "reg" else RandomForestClassifier
        rf = Model(n_estimators=self.n_estimators, min_samples_leaf=self.min_samples_leaf,
                   random_state=self.random_state, n_jobs=1)
        rf.fit(A, y if self.kind == "reg" else y.astype(int))
        self.trees = []
        for est in rf.estimators_:
            t = est.tree_
            if self.kind == "reg":
                value = t.value[:, 0, 0]
            else:       # share of the positive class in the node (a one-class fit has a single column)
                v = t.value[:, 0, :]
                pos = list(rf.classes_).index(1) if 1 in rf.classes_ else None
                value = v[:, pos] / v.sum(axis=1) if pos is not None else np.zeros(len(v))
            self.trees.append({"left": t.children_left.astype(int), "right": t.children_right.astype(int),
                               "feature": t.feature.astype(int), "threshold": t.threshold.astype(float),
                               "value": np.asarray(value, float),
                               "weight": t.weighted_n_node_samples.astype(float)})
        self._explainer = None
        return self

    # ------------------------------------------------------------------ predict
    def _walk(self, A: np.ndarray) -> np.ndarray:
        """Mean leaf value per row."""
        n = len(A)
        out = np.zeros(n)
        rows = np.arange(n)
        for t in self.trees:
            node = np.zeros(n, dtype=int)
            live = t["left"][node] != -1
            while live.any():
                idx = rows[live]
                cur = node[idx]
                feat = t["feature"][cur]
                nxt = np.where(A[idx, feat] <= t["threshold"][cur], t["left"][cur], t["right"][cur])
                node[idx] = nxt
                live = t["left"][node] != -1
            out += t["value"][node]
        return out / (len(self.trees) or 1)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        val = self._walk(self._matrix(X))
        return val if self.kind == "reg" else (val >= 0.5).astype(int)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        p = self._walk(self._matrix(X))
        return np.column_stack([1 - p, p])

    def contributions(self, X: pd.DataFrame) -> tuple[float, np.ndarray]:
        """(base value, per-column contributions); base + row sum = prediction (probability for a classifier)."""
        if self._explainer is None:
            k = len(self.trees) or 1
            self._explainer = shap.TreeExplainer({"trees": [
                {"children_left": t["left"], "children_right": t["right"], "children_default": t["left"],
                 "features": t["feature"], "thresholds": t["threshold"], "values": (t["value"] / k).reshape(-1, 1),
                 "node_sample_weight": t["weight"]} for t in self.trees]})
        sv = np.asarray(self._explainer.shap_values(self._matrix(X), check_additivity=False))
        return float(np.ravel(self._explainer.expected_value)[0]), sv.reshape(len(sv), -1)

    # ------------------------------------------------------------------ JSON
    def to_dict(self) -> dict:
        return {"format": FORMAT, "kind": self.kind, "columns": self.columns, "fill": [round(float(v), 6) for v in self.fill],
                "n_estimators": self.n_estimators, "min_samples_leaf": self.min_samples_leaf,
                "trees": [{"left": t["left"].tolist(), "right": t["right"].tolist(), "feature": t["feature"].tolist(),
                           "threshold": [round(float(v), 6) for v in t["threshold"]],
                           "value": [round(float(v), 5) for v in t["value"]],
                           "weight": [round(float(v), 3) for v in t["weight"]]} for t in self.trees]}

    def save_model(self, path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), separators=(",", ":")))

    @classmethod
    def from_dict(cls, d: dict) -> "ForestModel":
        m = cls(d.get("kind", "reg"), n_estimators=d.get("n_estimators"), min_samples_leaf=d.get("min_samples_leaf"))
        m.columns = list(d["columns"])
        m.fill = np.asarray(d["fill"], float)
        m.trees = [{"left": np.asarray(t["left"], int), "right": np.asarray(t["right"], int),
                    "feature": np.asarray(t["feature"], int), "threshold": np.asarray(t["threshold"], float),
                    "value": np.asarray(t["value"], float), "weight": np.asarray(t["weight"], float)} for t in d["trees"]]
        return m
