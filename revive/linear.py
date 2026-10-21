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

Sign constraints: with few projects and correlated inputs (SPI, CPI and value
certified move together), a free fit can give a coefficient the wrong sign,
e.g. "complete drawings at award add delay". Each core question therefore
declares the direction engineering sense allows (schema.CORE_DIRECTION); the
fit keeps every coefficient on that side of zero or sets it to zero. This is
the linear equivalent of XGBoost's monotone constraints.

Saved with to_json()/load_model() as numbers only: no pickle, nothing
executable is loaded from disk.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import lsq_linear, minimize
from sklearn.linear_model import LogisticRegression, Ridge


class LinearModel:
    def __init__(self, kind: str = "reg", alpha: float = 3.0, C: float = 0.5, signs: dict | None = None):
        """signs: {column: +1 | -1} = the direction a higher value may push the target
        (for a classifier, the log-odds of the positive class); columns not listed are free."""
        if kind not in ("reg", "clf"):
            raise ValueError("kind must be 'reg' or 'clf'")
        self.kind, self.alpha, self.C = kind, float(alpha), float(C)
        self.signs = dict(signs or {})
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
        bounds = self._bounds()
        if bounds is not None:
            self.coef, self.intercept = (self._fit_ridge_bounded(Z, y, bounds) if self.kind == "reg"
                                         else self._fit_logistic_bounded(Z, y.astype(int), bounds))
            return self
        if self.kind == "reg":
            m = Ridge(alpha=self.alpha).fit(Z, y)
        else:
            m = LogisticRegression(C=self.C, max_iter=2000).fit(Z, y.astype(int))
        self.coef = np.ravel(m.coef_).astype(float)
        self.intercept = float(np.ravel(m.intercept_)[0])
        return self

    def _bounds(self):
        if not any(self.signs.get(c) for c in self.columns):
            return None
        lo = np.array([0.0 if self.signs.get(c, 0) > 0 else -np.inf for c in self.columns])
        hi = np.array([0.0 if self.signs.get(c, 0) < 0 else np.inf for c in self.columns])
        return lo, hi

    def _fit_ridge_bounded(self, Z, y, bounds):
        """min ||Zw - (y - mean y)||^2 + alpha ||w||^2 within the sign bounds (same objective as Ridge;
        the intercept is mean y because every column of Z averages zero)."""
        k = Z.shape[1]
        A = np.vstack([Z, np.sqrt(self.alpha) * np.eye(k)])
        t = np.concatenate([y - y.mean(), np.zeros(k)])
        res = lsq_linear(A, t, bounds=bounds, method="bvls")
        return np.asarray(res.x, dtype=float), float(y.mean())

    def _fit_logistic_bounded(self, Z, y, bounds):
        """min C * logloss + ||w||^2 / 2 within the sign bounds (same objective as LogisticRegression)."""
        k = Z.shape[1]
        s = 2.0 * y - 1.0

        def f(theta):
            w, b = theta[:k], theta[k]
            m = s * (Z @ w + b)
            loss = np.logaddexp(0.0, -m).sum()
            g = -s / (1.0 + np.exp(m))
            return self.C * loss + 0.5 * w @ w, np.concatenate([self.C * (Z.T @ g) + w, [self.C * g.sum()]])

        lo, hi = bounds
        bnds = [(None if np.isinf(a) else a, None if np.isinf(b) else b) for a, b in zip(lo, hi)] + [(None, None)]
        p = np.clip(y.mean(), 1e-6, 1 - 1e-6)
        res = minimize(f, np.concatenate([np.zeros(k), [np.log(p / (1 - p))]]), jac=True,
                       method="L-BFGS-B", bounds=bnds)
        return np.asarray(res.x[:k], dtype=float), float(res.x[k])

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
                "signs": self.signs,
                "columns": self.columns, "mean": [float(v) for v in self.mean],
                "scale": [float(v) for v in self.scale], "coef": [float(v) for v in self.coef],
                "intercept": self.intercept}

    def save_model(self, path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1))

    @classmethod
    def from_dict(cls, d: dict) -> "LinearModel":
        if d.get("format") != "revive-linear-1":
            raise ValueError("not a REVIVE linear model file")
        m = cls(d["kind"], d.get("alpha", 3.0), d.get("C", 0.5), d.get("signs"))
        m.columns = list(d["columns"])
        m.mean, m.scale, m.coef = (np.asarray(d[k], dtype=float) for k in ("mean", "scale", "coef"))
        m.intercept = float(d["intercept"])
        return m

    @classmethod
    def load_model(cls, path) -> "LinearModel":
        return cls.from_dict(json.loads(Path(path).read_text()))
