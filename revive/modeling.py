"""
Model training.

For every gate (G25, G50) three XGBoost models are trained:
  time  - regression of time overrun (percentage points)
  cost  - regression of cost overrun (percentage points)
  risk  - classifier: probability that time overrun exceeds the high-risk threshold

How performance is measured when the FINAL model is trained on every record
  Repeated k-fold cross-validation (5 folds x 3 repeats). Each project is held
  out once per repeat, predicted by a model that never saw it, and those
  "out-of-fold" (OOF) predictions give the reported metrics. The production
  model is then refitted on all records. This is standard practice for small
  datasets and uses the data more efficiently than a single 80:20 split.
  When new projects arrive, `python -m revive evaluate --file new.xlsx`
  scores them as a true external test set.
"""
from __future__ import annotations

import json
import platform
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import shap
import sklearn
import xgboost as xgb
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (accuracy_score, f1_score, mean_absolute_error, mean_squared_error,
                             precision_score, r2_score, recall_score, roc_auc_score)
from sklearn.model_selection import RepeatedKFold, RepeatedStratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC, SVR

from .config import load_config, models_dir, reports_dir
from .data import load_clean
from .features import column_to_field, encode, gate_columns
from .schema import FIELD_BY_KEY, LEAKAGE_EXCLUDED


# ---------------------------------------------------------------------------
def training_frame(df: pd.DataFrame | None = None) -> pd.DataFrame:
    cfg = load_config()["training"]
    df = load_clean() if df is None else df
    df = df[df["time_overrun_pct"].notna()].copy()
    if not cfg.get("include_ongoing", True):
        df = df[df["status"].ne("Still ongoing")]
    if not cfg.get("include_hypothetical", True):
        df = df[~df["is_hypothetical"].astype(bool)]
    return df.reset_index(drop=True)


def targets(df: pd.DataFrame) -> dict:
    cfg = load_config()["training"]
    y_time = df["time_overrun_pct"].clip(upper=cfg["time_overrun_clip_pct"])
    lo, hi = cfg["cost_overrun_clip_pct"]
    y_cost = df["cost_overrun_pct"].clip(lower=lo, upper=hi)
    y_risk = (df["time_overrun_pct"] > cfg["high_risk_threshold_pct"]).astype(int)
    return {"time": y_time, "cost": y_cost, "risk": y_risk}


def _reg(params=None):
    p = dict(load_config()["training"]["xgb_regressor"])
    p.update(params or {})
    return xgb.XGBRegressor(random_state=load_config()["training"]["random_state"], n_jobs=1, **p)


def _clf(params=None):
    p = dict(load_config()["training"]["xgb_classifier"])
    p.update(params or {})
    return xgb.XGBClassifier(random_state=load_config()["training"]["random_state"], n_jobs=1,
                             eval_metric="logloss", **p)


def _alt_models(kind: str) -> dict:
    rs = load_config()["training"]["random_state"]
    imp = SimpleImputer(strategy="median", keep_empty_features=True)
    if kind == "reg":
        return {
            "Random Forest": make_pipeline(imp, RandomForestRegressor(n_estimators=400, min_samples_leaf=2, random_state=rs, n_jobs=1)),
            "SVM (RBF)": make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True), StandardScaler(), SVR(C=30, epsilon=2.0)),
            "Ridge regression": make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True), StandardScaler(), Ridge(alpha=3.0)),
        }
    return {
        "Random Forest": make_pipeline(imp, RandomForestClassifier(n_estimators=400, min_samples_leaf=2, random_state=rs, n_jobs=1)),
        "SVM (RBF)": make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True), StandardScaler(), SVC(C=3, probability=True, random_state=rs)),
        "Logistic regression": make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True), StandardScaler(), LogisticRegression(C=0.5, max_iter=2000)),
    }


# ---------------------------------------------------------------------------
def _cv_regression(make_model, X, y, repeats, folds, seed):
    rkf = RepeatedKFold(n_splits=folds, n_repeats=repeats, random_state=seed)
    oof = np.zeros((repeats, len(y)))
    for i, (tr, te) in enumerate(rkf.split(X)):
        m = make_model()
        m.fit(X.iloc[tr], y.iloc[tr])
        oof[i // folds, te] = m.predict(X.iloc[te])
    per_rep = [dict(mae=mean_absolute_error(y, o), rmse=float(np.sqrt(mean_squared_error(y, o))),
                    r2=r2_score(y, o)) for o in oof]
    return _summarise(per_rep), oof.mean(axis=0)


def _cv_classification(make_model, X, y, repeats, folds, seed):
    rskf = RepeatedStratifiedKFold(n_splits=folds, n_repeats=repeats, random_state=seed)
    oof = np.zeros((repeats, len(y)))
    for i, (tr, te) in enumerate(rskf.split(X, y)):
        m = make_model()
        m.fit(X.iloc[tr], y.iloc[tr])
        oof[i // folds, te] = m.predict_proba(X.iloc[te])[:, 1]
    per_rep = []
    for o in oof:
        pred = (o >= 0.5).astype(int)
        per_rep.append(dict(auc=roc_auc_score(y, o), f1=f1_score(y, pred, zero_division=0),
                            accuracy=accuracy_score(y, pred), precision=precision_score(y, pred, zero_division=0),
                            recall=recall_score(y, pred, zero_division=0)))
    return _summarise(per_rep), oof.mean(axis=0)


def _summarise(per_rep: list[dict]) -> dict:
    keys = per_rep[0].keys()
    return {k: {"mean": float(np.mean([r[k] for r in per_rep])), "std": float(np.std([r[k] for r in per_rep]))}
            for k in keys}


def tune_regressor(X, y, seed) -> dict:
    """Small, transparent grid search on CV MAE (run with --tune)."""
    grid = [dict(max_depth=d, learning_rate=lr, n_estimators=n, min_child_weight=m)
            for d in (2, 3, 4) for lr in (0.03, 0.06) for n in (300, 600) for m in (1, 3)]
    best, best_mae = None, np.inf
    for g in grid:
        res, _ = _cv_regression(lambda: _reg(g), X, y, repeats=1, folds=5, seed=seed)
        if res["mae"]["mean"] < best_mae:
            best, best_mae = g, res["mae"]["mean"]
    return best


# ---------------------------------------------------------------------------
def _group_shap(values: np.ndarray, columns: list[str]) -> tuple[np.ndarray, list[str]]:
    fields, idx = [], {}
    for j, c in enumerate(columns):
        k = column_to_field(c)
        if k not in idx:
            idx[k] = len(fields)
            fields.append(k)
    grouped = np.zeros((values.shape[0], len(fields)))
    for j, c in enumerate(columns):
        grouped[:, idx[column_to_field(c)]] += values[:, j]
    return grouped, fields


def _field_numeric_value(df: pd.DataFrame, X: pd.DataFrame, key: str) -> np.ndarray:
    """0-1 scaled feature value used to colour beeswarm dots (NaN = grey)."""
    if key in X.columns:
        v = X[key].to_numpy(dtype=float)
        lo, hi = np.nanmin(v) if np.isfinite(v).any() else 0, np.nanmax(v) if np.isfinite(v).any() else 1
        return (v - lo) / (hi - lo) if hi > lo else np.zeros_like(v)
    return np.full(len(X), np.nan)


def global_explanation(model, X: pd.DataFrame, df: pd.DataFrame, top: int = 12) -> dict:
    explainer = shap.TreeExplainer(model)
    sv = explainer.shap_values(X)
    grouped, fields = _group_shap(np.asarray(sv), list(X.columns))
    importance = np.abs(grouped).mean(axis=0)
    order = np.argsort(-importance)
    ranking = [{"key": fields[i], "label": FIELD_BY_KEY[fields[i]]["label"],
                "mean_abs_shap": round(float(importance[i]), 3)} for i in order]
    swarm = []
    for i in order[:top]:
        k = fields[i]
        vals = _field_numeric_value(df, X, k)
        swarm.append({"key": k, "label": FIELD_BY_KEY[k]["label"],
                      "points": [[round(float(s), 3), None if not np.isfinite(v) else round(float(v), 3)]
                                 for s, v in zip(grouped[:, i], vals)]})
    return {"base_value": float(np.ravel(explainer.expected_value)[0]), "ranking": ranking, "beeswarm": swarm}


# ---------------------------------------------------------------------------
def train(compare: bool = True, tune: bool = False, verbose: bool = True) -> dict:
    cfg = load_config()
    tcfg = cfg["training"]
    df = training_frame()
    T = targets(df)
    seed, folds, reps = tcfg["random_state"], tcfg["cv_folds"], tcfg["cv_repeats"]
    out_dir = models_dir()
    started = time.time()
    card = {
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "training_scope": {"include_ongoing": tcfg["include_ongoing"],
                           "include_hypothetical": tcfg["include_hypothetical"]},
        "dataset": _dataset_summary(df),
        "high_risk_threshold_pct": tcfg["high_risk_threshold_pct"],
        "validation": f"Repeated {folds}-fold cross-validation x {reps} repeats (out-of-fold predictions); "
                      "final models refitted on all records.",
        "excluded_for_leakage": LEAKAGE_EXCLUDED,
        "versions": {"python": platform.python_version(), "xgboost": xgb.__version__,
                     "scikit-learn": sklearn.__version__, "shap": shap.__version__},
        "gates": {},
    }
    oof_rows = pd.DataFrame({"project_id": df["project_id"], "actual_time_overrun_pct": df["time_overrun_pct"],
                             "actual_cost_overrun_pct": df["cost_overrun_pct"]})
    comparison = []

    for gate, gcfg in cfg["gates"].items():
        X = encode(df, gate)
        gdir = out_dir / gate
        gdir.mkdir(exist_ok=True)
        reg_params = tune_regressor(X, T["time"], seed) if tune else {}
        if verbose:
            print(f"[{gate}] {len(X)} projects x {X.shape[1]} encoded columns" + (f", tuned {reg_params}" if tune else ""))

        # ---- time overrun -----------------------------------------------
        m_time, oof_time = _cv_regression(lambda: _reg(reg_params), X, T["time"], reps, folds, seed)
        resid = T["time"].to_numpy() - oof_time
        q_lo, q_hi = np.quantile(resid, [0.10, 0.90])
        base_mae = mean_absolute_error(T["time"], np.full(len(T["time"]), T["time"].median()))

        # ---- cost overrun -----------------------------------------------
        cmask = T["cost"].notna().to_numpy()
        Xc, yc = X[cmask].reset_index(drop=True), T["cost"][cmask].reset_index(drop=True)
        m_cost, oof_cost_part = _cv_regression(lambda: _reg(), Xc, yc, reps, folds, seed)
        oof_cost = np.full(len(X), np.nan)
        oof_cost[cmask] = oof_cost_part
        cres = yc.to_numpy() - oof_cost_part
        c_lo, c_hi = np.quantile(cres, [0.10, 0.90])

        # ---- high-risk classifier ---------------------------------------
        m_risk, oof_prob = _cv_classification(lambda: _clf(), X, T["risk"], reps, folds, seed)
        majority = max(T["risk"].mean(), 1 - T["risk"].mean())

        # ---- final fits on every record ---------------------------------
        final_time = _reg(reg_params).fit(X, T["time"])
        final_cost = _reg().fit(Xc, yc)
        final_risk = _clf().fit(X, T["risk"])
        final_time.save_model(gdir / "time.json")
        final_cost.save_model(gdir / "cost.json")
        final_risk.save_model(gdir / "risk.json")

        glob = global_explanation(final_time, X, df)
        (gdir / "shap_global.json").write_text(json.dumps(glob))
        meta = {"gate": gate, "label": gcfg["label"], "columns": list(X.columns),
                "time_interval_residuals": [float(q_lo), float(q_hi)],
                "time_residuals": [round(float(v), 2) for v in resid],
                "cost_interval_residuals": [float(c_lo), float(c_hi)],
                "time_params": reg_params, "n_train": int(len(X)), "n_train_cost": int(cmask.sum())}
        (gdir / "meta.json").write_text(json.dumps(meta, indent=2))

        card["gates"][gate] = {
            "label": gcfg["label"], "n_projects": int(len(X)), "n_encoded_columns": int(X.shape[1]),
            "time_overrun": {**_round(m_time), "baseline_median_mae": round(float(base_mae), 2),
                             "interval_80pct_residuals": [round(float(q_lo), 2), round(float(q_hi), 2)]},
            "cost_overrun": _round(m_cost),
            "high_risk": {**_round(m_risk), "positives": int(T["risk"].sum()),
                          "majority_class_accuracy": round(float(majority), 3)},
            "top_drivers": glob["ranking"][:8],
        }
        oof_rows[f"{gate}_time"] = oof_time.round(2)
        oof_rows[f"{gate}_cost"] = np.round(oof_cost, 2)
        oof_rows[f"{gate}_prob"] = oof_prob.round(4)

        # ---- model comparison (for the report) --------------------------
        if compare:
            comparison.append(_comparison_row(gate, "Median baseline", {"mae": {"mean": base_mae, "std": 0}}, None))
            comparison.append(_comparison_row(gate, "XGBoost (production)", m_time, m_risk))
            for name, model in _alt_models("reg").items():
                r, _ = _cv_regression(lambda: sklearn.base.clone(model), X, T["time"], 1, folds, seed)
                c_model = _alt_models("clf")[{"Ridge regression": "Logistic regression"}.get(name, name)]
                c, _ = _cv_classification(lambda: sklearn.base.clone(c_model), X, T["risk"], 1, folds, seed)
                comparison.append(_comparison_row(gate, name if name != "Ridge regression" else "Linear (Ridge / Logistic)", r, c))

    oof_rows.to_csv(out_dir / "oof_predictions.csv", index=False)
    if comparison:
        comp = pd.DataFrame(comparison)
        comp.to_csv(reports_dir() / "model_comparison.csv", index=False)
        card["model_comparison"] = comp.to_dict(orient="records")
    card["training_seconds"] = round(time.time() - started, 1)
    (out_dir / "model_card.json").write_text(json.dumps(card, indent=2))
    _figures(df, oof_rows)
    if verbose:
        for g, v in card["gates"].items():
            t, r = v["time_overrun"], v["high_risk"]
            print(f"[{g}] time MAE {t['mae']['mean']:.1f} pts (median baseline {t['baseline_median_mae']:.1f}), "
                  f"R2 {t['r2']['mean']:.2f} | high-risk AUC {r['auc']['mean']:.3f}, F1 {r['f1']['mean']:.3f}")
        print(f"Saved models to {out_dir}  ({card['training_seconds']} s)")
    return card


def _round(m: dict) -> dict:
    return {k: {"mean": round(v["mean"], 3), "std": round(v["std"], 3)} for k, v in m.items()}


def _comparison_row(gate, name, reg, clf):
    row = {"gate": gate, "model": name, "time_MAE": round(reg["mae"]["mean"], 2)}
    row["time_R2"] = round(reg["r2"]["mean"], 3) if "r2" in reg else None
    row["risk_AUC"] = round(clf["auc"]["mean"], 3) if clf else None
    row["risk_F1"] = round(clf["f1"]["mean"], 3) if clf else None
    return row


def _dataset_summary(df: pd.DataFrame) -> dict:
    return {
        "n_projects": int(len(df)),
        "by_source": df["source_group"].value_counts().to_dict(),
        "hypothetical": int(df["is_hypothetical"].astype(bool).sum()),
        "by_status": df["status"].fillna("Unknown").value_counts().to_dict(),
        "by_type": df["project_type"].fillna("Unknown").value_counts().to_dict(),
        "time_overrun_pct": {k: round(float(v), 1) for k, v in
                             df["time_overrun_pct"].describe()[["mean", "50%", "min", "max"]].items()},
        "cost_overrun_pct": {k: round(float(v), 1) for k, v in
                             df["cost_overrun_pct"].describe()[["mean", "50%", "min", "max"]].items()},
    }


def _figures(df: pd.DataFrame, oof: pd.DataFrame) -> None:
    """Static figures for the written report (reports/figures)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # pragma: no cover
        return
    fig_dir = reports_dir() / "figures"
    for gate in load_config()["gates"]:
        if f"{gate}_time" not in oof:
            continue
        fig, ax = plt.subplots(figsize=(5, 5))
        y = oof["actual_time_overrun_pct"].clip(upper=load_config()["training"]["time_overrun_clip_pct"])
        ax.scatter(y, oof[f"{gate}_time"], s=18, alpha=0.7)
        lim = [min(y.min(), oof[f"{gate}_time"].min()) - 5, max(y.max(), oof[f"{gate}_time"].max()) + 5]
        ax.plot(lim, lim, "k--", lw=1)
        ax.set_xlabel("Actual time overrun (%)")
        ax.set_ylabel("Out-of-fold predicted overrun (%)")
        ax.set_title(f"{gate}: predicted vs actual (cross-validated)")
        fig.tight_layout()
        fig.savefig(fig_dir / f"{gate}_oof_scatter.png", dpi=160)
        plt.close(fig)
        try:
            model = xgb.XGBRegressor()
            model.load_model(models_dir() / gate / "time.json")
            X = encode(df, gate)
            sv = shap.TreeExplainer(model)(X)
            plt.figure()
            shap.plots.beeswarm(sv, max_display=15, show=False)
            plt.tight_layout()
            plt.savefig(fig_dir / f"{gate}_shap_beeswarm.png", dpi=160)
            plt.close("all")
        except Exception as exc:  # pragma: no cover
            print(f"(skipped beeswarm figure: {exc})")


# ---------------------------------------------------------------------------
def sensitivity(verbose: bool = True) -> pd.DataFrame:
    """How much do the results depend on the data scope and on SPI/CPI?
    Answers the two examiner questions: 'what if you drop the hypothetical rows?'
    and 'is the model just reading SPI?'."""
    tcfg = load_config()["training"]
    base = load_clean()
    base = base[base["time_overrun_pct"].notna()]
    scopes = {
        "All records (production setting)": dict(ongoing=True, hyp=True, evm=True),
        "Completed projects only": dict(ongoing=False, hyp=True, evm=True),
        "Without hypothetical rows": dict(ongoing=True, hyp=False, evm=True),
        "All records, SPI/CPI removed": dict(ongoing=True, hyp=True, evm=False),
    }
    rows = []
    for name, sc in scopes.items():
        df = base.copy()
        if not sc["ongoing"]:
            df = df[df["status"].eq("Completed")]
        if not sc["hyp"]:
            df = df[~df["is_hypothetical"].astype(bool)]
        df = df.reset_index(drop=True)
        T = targets(df)
        for gate in load_config()["gates"]:
            X = encode(df, gate)
            if not sc["evm"]:
                X = X[[c for c in X.columns if not c.startswith(("spi_", "cpi_"))]]
            r, _ = _cv_regression(lambda: _reg(), X, T["time"], 2, tcfg["cv_folds"], tcfg["random_state"])
            auc = None
            if 5 <= T["risk"].sum() <= len(T["risk"]) - 5:
                c, _ = _cv_classification(lambda: _clf(), X, T["risk"], 2, tcfg["cv_folds"], tcfg["random_state"])
                auc = round(c["auc"]["mean"], 3)
            rows.append({"scope": name, "gate": gate, "n": len(df),
                         "time_MAE": round(r["mae"]["mean"], 2), "time_R2": round(r["r2"]["mean"], 3),
                         "baseline_MAE": round(float(np.mean(np.abs(T["time"] - T["time"].median()))), 2),
                         "risk_AUC": auc})
    out = pd.DataFrame(rows)
    out.to_csv(reports_dir() / "sensitivity.csv", index=False)
    (models_dir() / "sensitivity.json").write_text(out.to_json(orient="records"))
    if verbose:
        print(out.to_string(index=False))
    return out
