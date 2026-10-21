"""
Inference: one project in -> forecast, risk, health score and explanation out.

Every prediction is split into (average prediction) + one contribution per
input field, in percentage points of time overrun, and the contributions add
up exactly. For the linear production model that is coefficient x
standardised input; for an XGBoost model (training.model: xgboost) it is
TreeSHAP. Both are SHAP values, so the panels read the same either way.
One-hot columns of the same field (e.g. all "project_type=..." columns) are
summed so a manager sees one line per question, not per encoded column.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache

import numpy as np
import pandas as pd
from .actions import actions_for
from .config import load_config, models_dir
from .data import load_clean
from .features import column_to_field, display_value, encode_one, gate_fields
from .modeling import contributions, load_model
from .schema import FIELD_BY_KEY, FIELDS


def _clip01(x):
    return max(0.0, min(1.0, x))


def risk_band(overrun_pct: float) -> dict:
    bands = load_config()["risk_bands"]
    b = next((b for b in bands if overrun_pct <= b["max"]), bands[-1])
    return {"name": b["name"], "color": b["color"]}


def health_score(spi, cpi, forecast_overrun) -> dict:
    h = load_config()["health_score"]
    w = h["weights"]
    parts = {}
    if spi is not None and not math.isnan(spi):
        parts["spi"] = _clip01((spi - h["spi_floor"]) / (1 - h["spi_floor"]))
    if cpi is not None and not math.isnan(cpi):
        parts["cpi"] = _clip01((cpi - h["cpi_floor"]) / (1 - h["cpi_floor"]))
    parts["forecast"] = 1 - _clip01(forecast_overrun / h["forecast_ceiling_pct"])
    total_w = sum(w[k] for k in parts)
    score = 100 * sum(w[k] * v for k, v in parts.items()) / total_w
    return {"score": round(score, 1), "components": {k: round(v * 100, 1) for k, v in parts.items()},
            "weights": {k: w[k] for k in parts}}


def recovery_triggers(phs: float, spi, cpi) -> list[str]:
    t = load_config()["health_score"]["recovery_trigger"]
    out = []
    if phs < t["phs_below"]:
        out.append(f"Health score {phs:.0f} is below {t['phs_below']}")
    if spi is not None and not math.isnan(spi) and spi < t["spi_below"]:
        out.append(f"SPI {spi:.2f} is below {t['spi_below']}")
    if cpi is not None and not math.isnan(cpi) and cpi < t["cpi_below"]:
        out.append(f"CPI {cpi:.2f} is below {t['cpi_below']}")
    return out


class Predictor:
    def __init__(self):
        root = models_dir()
        self.card = json.loads((root / "model_card.json").read_text())
        self.gates = {}
        for gate in load_config()["gates"]:
            gdir = root / gate
            time_m = load_model(gdir / "time.json", "reg")
            cost_m = load_model(gdir / "cost.json", "reg")
            risk_m = load_model(gdir / "risk.json", "clf")
            meta = json.loads((gdir / "meta.json").read_text())
            self.gates[gate] = {
                "time": time_m, "cost": cost_m, "risk": risk_m, "meta": meta,
                "global": json.loads((gdir / "shap_global.json").read_text()),
            }
        oof_path = root / "oof_predictions.csv"
        self.oof = pd.read_csv(oof_path) if oof_path.exists() else pd.DataFrame()
        try:
            self.dataset = load_clean()
        except FileNotFoundError:
            self.dataset = pd.DataFrame()

    # ------------------------------------------------------------------
    @staticmethod
    def choose_gate(inputs: dict) -> str:
        v = inputs.get("spi_50")
        return "G50" if v not in (None, "") else "G25"

    def _explain(self, model, X, inputs, top=8) -> dict:
        base, sv = contributions(model, X)
        sv = np.asarray(sv)[0]
        agg: dict[str, float] = {}
        for col, val in zip(X.columns, sv):
            k = column_to_field(col)
            agg[k] = agg.get(k, 0.0) + float(val)
        items = sorted(agg.items(), key=lambda kv: -abs(kv[1]))
        contribs = [{"key": k, "label": FIELD_BY_KEY[k]["label"], "value": display_value(k, inputs),
                     "shap": round(v, 2)} for k, v in items[:top]]
        rest = sum(v for _, v in items[top:])
        if items[top:]:
            contribs.append({"key": "_other", "label": f"{len(items) - top} other factors", "value": "",
                             "shap": round(rest, 2)})
        return {"base_value": round(base, 2), "contributions": contribs}

    def predict(self, inputs: dict, gate: str | None = None, source_project_id: str | None = None) -> dict:
        gate = gate or self.choose_gate(inputs)
        g = self.gates[gate]
        X = encode_one(inputs, gate)
        t = float(g["time"].predict(X)[0])
        c = float(g["cost"].predict(X)[0])
        p = float(g["risk"].predict_proba(X)[0, 1])
        lo, hi = g["meta"]["time_interval_residuals"]
        clo, chi = g["meta"]["cost_interval_residuals"]

        spi = _num(inputs.get("spi_50" if gate == "G50" else "spi_25"))
        cpi = _num(inputs.get("cpi_50" if gate == "G50" else "cpi_25"))
        phs = health_score(spi, cpi, t)
        planned = _num(inputs.get("planned_months"))
        forecast_months = planned * (1 + t / 100) if planned and not math.isnan(planned) else None

        missing = [f["label"] for f in gate_fields(gate)
                   if inputs.get(f["key"]) in (None, "") and f["key"] not in ("floor_area_m2", "storeys", "length_km")]
        result = {
            "gate": gate, "gate_label": load_config()["gates"][gate]["label"],
            "time_overrun_pct": round(t, 1),
            "time_interval_pct": [round(t + lo, 1), round(t + hi, 1)],
            "cost_overrun_pct": round(c, 1),
            "cost_interval_pct": [round(c + clo, 1), round(c + chi, 1)],
            "high_risk_probability": round(p, 3),
            "high_risk_threshold_pct": load_config()["training"]["high_risk_threshold_pct"],
            "band": risk_band(t),
            "health": phs,
            "recovery_triggers": recovery_triggers(phs["score"], spi, cpi),
            "planned_months": planned,
            "forecast_months": round(forecast_months, 1) if forecast_months else None,
            "explanation": self._explain(g["time"], X, inputs),
            "cost_explanation": self._explain(g["cost"], X, inputs, top=5),
            "missing_inputs": missing,
        }
        result["recovery_recommended"] = bool(result["recovery_triggers"]) or result["band"]["name"] in ("At risk", "Critical")
        result["actions"] = actions_for(result["explanation"])
        if source_project_id and not self.oof.empty:
            row = self.oof[self.oof["project_id"] == source_project_id]
            if len(row):
                r = row.iloc[0]
                result["training_record"] = {
                    "note": "This project is in the training data, so the figures above are in-sample. "
                            "The cross-validated (out-of-fold) estimate below is the honest one.",
                    "oof_time_overrun_pct": _safe(r.get(f"{gate}_time")),
                    "oof_high_risk_probability": _safe(r.get(f"{gate}_prob")),
                    "actual_time_overrun_pct": _safe(r.get("actual_time_overrun_pct")),
                }
        return result

    # ------------------------------------------------------------------
    def portfolio(self) -> list[dict]:
        if self.dataset.empty:
            return []
        df = self.dataset.merge(self.oof, on="project_id", how="left") if not self.oof.empty else self.dataset
        rows = []
        for _, r in df.iterrows():
            gate = "G50" if pd.notna(r.get("spi_50")) else "G25"
            pred = _safe(r.get(f"{gate}_time"))
            in_training = pred is not None
            prob = _safe(r.get(f"{gate}_prob"))
            if not in_training:
                # Not used for training (ongoing or hypothetical): the production model never saw
                # it, so its plain prediction is already an out-of-sample forecast.
                X = encode_one({f["key"]: r.get(f["key"]) for f in FIELDS}, gate)
                pred = _safe(float(self.gates[gate]["time"].predict(X)[0]))
                prob = _safe(float(self.gates[gate]["risk"].predict_proba(X)[0, 1]))
            rows.append({
                "project_id": r["project_id"], "project_type": r.get("project_type"),
                "province": r.get("province"), "contract_value": r.get("contract_value"),
                "status": r.get("status"), "planned_months": _safe(r.get("planned_months")),
                "spi": _safe(r.get("spi_50") if gate == "G50" else r.get("spi_25")),
                "cpi": _safe(r.get("cpi_50") if gate == "G50" else r.get("cpi_25")),
                "gate": gate, "predicted_time_overrun_pct": pred,
                "high_risk_probability": prob, "in_training": in_training,
                "actual_time_overrun_pct": _safe(r.get("time_overrun_pct")),
                "band": risk_band(pred) if pred is not None else None,
                "hypothetical": bool(r.get("is_hypothetical")), "source_group": r.get("source_group"),
            })
        return rows

    def inputs_for(self, project_id: str) -> dict | None:
        if self.dataset.empty:
            return None
        row = self.dataset[self.dataset["project_id"] == project_id]
        if row.empty:
            return None
        r = row.iloc[0]
        return {f["key"]: _safe(r.get(f["key"])) if f["kind"] == "number" else
                (None if pd.isna(r.get(f["key"])) else r.get(f["key"])) for f in FIELDS}


def _num(v):
    try:
        return float(v) if v not in (None, "") else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def _safe(v):
    try:
        f = float(v)
        return None if math.isnan(f) else round(f, 3)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def get_predictor() -> Predictor:
    return Predictor()
