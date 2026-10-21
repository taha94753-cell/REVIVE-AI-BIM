"""
Linear models with exact additive explanations, stored as plain JSON.

Why a linear model: with 81 completed projects from three contractors, a
regularised linear model on a few strong signals generalises to an unseen
contractor better than a tree ensemble on every survey answer
(see docs/DATA_NOTES.md, "Leave-one-company-out").

How the explanation works: inputs are standardised with the training mean
and spread, so every column averages zero on the training data. A
prediction is then

    intercept + sum_j coef_j * z_j

and coef_j * z_j is column j's contribution. The intercept equals the
average training prediction, so the contributions add up exactly to
(prediction - average), the same contract TreeSHAP gives for trees (it is
the SHAP value of a linear model with independent inputs). A blank answer
is filled with the training mean and therefore contributes exactly zero.

Saved with to_json()/load_model() as numbers only: no pickle, nothing
executable is loaded from disk.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge


class LinearModel:
    def __init__(self, kind: str = "reg", alpha: float = 3.0, C: float = 0.5):
        if kind not in ("reg", "clf"):
            raise ValueError("kind must be 'reg' or 'clf'")
        self.kind, self.alpha, self.C = kind, float(alpha), float(C)
        self.columns: list[str] = []
        self.mean = self.scale = self.coef = None
        self.intercept = 0.0

    # ------------------------------------------------------------------
    def _z(self, X: pd.DataFrame) -> np.ndarray:
        A = X[self.columns].to_numpy(dtype=float)
        A = np.where(np.isnan(A), self.mean, A)
        return (A - self.mean) / self.scale

    def fit(self, X: pd.DataFrame, y) -> "LinearModel":
        self.columns = list(X.columns)
        A = X.to_numpy(dtype=float)
        with np.errstate(all="ignore"):
            mean = np.nanmean(A, axis=0)
        mean = np.where(np.isfinite(mean), mean, 0.0)
        A = np.where(np.isnan(A), mean, A)
        scale = A.std(axis=0)
        scale = np.where(scale > 1e-12, scale, 1.0)
        self.mean, self.scale = mean, scale
        Z = (A - mean) / scale
        y = np.asarray(y, dtype=float)
        if self.kind == "reg":
            m = Ridge(alpha=self.alpha).fit(Z, y)
        else:
            m = LogisticRegression(C=self.C, max_iter=2000).fit(Z, y.astype(int))
        self.coef = np.ravel(m.coef_).astype(float)
        self.intercept = float(np.ravel(m.intercept_)[0])
        return self

    def decision(self, X: pd.DataFrame) -> np.ndarray:
        return self._z(X) @ self.coef + self.intercept

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        d = self.decision(X)
        return d if self.kind == "reg" else (d >= 0).astype(int)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        p = 1.0 / (1.0 + np.exp(-self.decision(X)))
        return np.column_stack([1 - p, p])

    def contributions(self, X: pd.DataFrame) -> tuple[float, np.ndarray]:
        """(base value, one contribution per column per row); base + row sum = decision."""
        return self.intercept, self._z(X) * self.coef

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {"format": "revive-linear-1", "kind": self.kind, "alpha": self.alpha, "C": self.C,
                "columns": self.columns, "mean": [float(v) for v in self.mean],
                "scale": [float(v) for v in self.scale], "coef": [float(v) for v in self.coef],
                "intercept": self.intercept}

    def save_model(self, path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1))

    @classmethod
    def from_dict(cls, d: dict) -> "LinearModel":
        if d.get("format") != "revive-linear-1":
            raise ValueError("not a REVIVE linear model file")
        m = cls(d["kind"], d.get("alpha", 3.0), d.get("C", 0.5))
        m.columns = list(d["columns"])
        m.mean, m.scale, m.coef = (np.asarray(d[k], dtype=float) for k in ("mean", "scale", "coef"))
        m.intercept = float(d["intercept"])
        return m

    @classmethod
    def load_model(cls, path) -> "LinearModel":
        return cls.from_dict(json.loads(Path(path).read_text()))
