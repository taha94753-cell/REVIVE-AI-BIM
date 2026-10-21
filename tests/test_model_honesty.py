"""The compact question set, the linear model's explanations and the honest validation figures."""
import json

import numpy as np
import pandas as pd

from revive.config import load_config, models_dir
from revive.features import encode, gate_columns, gate_fields
from revive.linear import LinearModel
from revive.schema import CORE_KEYS, FIELDS, public_schema


def _toy(n=60, seed=0):
    rng = np.random.default_rng(seed)
    X = pd.DataFrame({"a": rng.normal(size=n), "b": rng.normal(size=n), "c": rng.normal(size=n)})
    X.loc[::7, "b"] = np.nan
    y = 3 * X["a"].fillna(0) - 2 * X["b"].fillna(0) + rng.normal(scale=0.1, size=n)
    return X, y


def test_linear_contributions_add_up_and_blank_answers_contribute_nothing():
    X, y = _toy()
    m = LinearModel("reg").fit(X, y)
    base, c = m.contributions(X)
    np.testing.assert_allclose(base + c.sum(axis=1), m.predict(X), atol=1e-9)
    assert abs(base - y.mean()) < 1e-6                    # base = average training prediction
    blank = X.iloc[[0]].copy()
    blank["b"] = np.nan
    assert m.contributions(blank)[1][0, 1] == 0.0


def test_linear_model_round_trips_through_json(tmp_path):
    X, y = _toy()
    for kind, target in (("reg", y), ("clf", (y > 0).astype(int))):
        m = LinearModel(kind).fit(X, target)
        m.save_model(tmp_path / f"{kind}.json")
        back = LinearModel.load_model(tmp_path / f"{kind}.json")
        if kind == "reg":
            np.testing.assert_allclose(back.predict(X), m.predict(X))
        else:
            np.testing.assert_allclose(back.predict_proba(X), m.predict_proba(X))


def test_form_asks_only_the_core_questions():
    cfg = load_config()
    assert cfg["training"]["feature_set"] == "core"
    sent = [f["key"] for g in public_schema(cfg["gates"], "core")["groups"] for f in g["fields"]]
    assert set(sent) == set(CORE_KEYS)
    assert len(gate_fields("G25")) <= 10 and len(gate_fields("G50")) <= 13
    assert len(sent) < len(FIELDS) / 2
    # the full question set is still available for comparison
    assert len(gate_columns("G25", "all")) > len(gate_columns("G25"))


def test_saved_models_use_the_configured_columns():
    for gate in load_config()["gates"]:
        meta = json.loads((models_dir() / gate / "meta.json").read_text())
        assert meta["columns"] == gate_columns(gate)


def test_model_card_reports_leave_company_out_and_baselines():
    card = json.loads((models_dir() / "model_card.json").read_text())
    assert card["training_scope"] == {"include_ongoing": False, "include_hypothetical": False}
    assert card["dataset"]["hypothetical"] == 0
    assert len(card["dataset"]["companies"]) >= 3
    for gate in card["gates"].values():
        loco = gate["leave_company_out"]
        assert {"mae", "r2"} <= set(loco["time_overrun"]) and 0 <= loco["high_risk_auc"] <= 1
        assert "r2" in loco["spi_only_linear"]
    names = {row["model"] for row in card["model_comparison"]}
    assert "Linear, SPI only" in names and any(n.startswith("XGBoost, all") for n in names)


def test_benchmark_scores_untrained_records_out_of_sample():
    from revive.inference import get_predictor
    rows = get_predictor().portfolio()
    hyp = [r for r in rows if r["hypothetical"]]
    assert hyp and all(not r["in_training"] and r["predicted_time_overrun_pct"] is not None for r in hyp)
    assert any(r["in_training"] for r in rows)


def test_encoding_of_full_question_set_still_works():
    from revive.data import load_clean
    X = encode(load_clean().head(3), "G50", feature_set="all")
    assert X.shape[1] == len(gate_columns("G50", "all"))


def test_forecast_lists_owned_actions_for_drivers_that_raise_it():
    from revive.inference import get_predictor
    from revive.presets import PRESETS
    pred = get_predictor().predict(PRESETS[0]["inputs"], PRESETS[0]["gate"])
    ups = {c["key"] for c in pred["explanation"]["contributions"] if c["shap"] >= 0.5}
    assert pred["actions"] or not ups
    for a in pred["actions"]:
        assert a["key"] in ups and a["owner_label"] and a["action"] and a["adds_pct_points"] >= 0.5


def test_sign_constraints_hold_and_match_an_unconstrained_fit_when_inactive():
    X, y = _toy()
    free = LinearModel("reg").fit(X, y)
    same = LinearModel("reg", signs={"a": +1, "b": -1}).fit(X, y)         # true signs: a +, b -
    np.testing.assert_allclose(same.coef, free.coef, atol=1e-6)
    wrong = LinearModel("reg", signs={"a": -1}).fit(X, y)                 # forbid a's real direction
    assert wrong.coef[0] == 0.0
    clf = LinearModel("clf", signs={"a": -1, "c": +1}).fit(X, (y > 0).astype(int))
    assert clf.coef[0] <= 0 and clf.coef[2] >= 0
    free_clf = LinearModel("clf").fit(X, (y > 0).astype(int))
    loose = LinearModel("clf", signs={"a": +1}).fit(X, (y > 0).astype(int))
    np.testing.assert_allclose(loose.coef, free_clf.coef, atol=1e-3)


def test_saved_models_respect_the_declared_directions():
    from revive.schema import CORE_DIRECTION
    for gate in load_config()["gates"]:
        for kind in ("time", "cost", "risk"):
            d = json.loads((models_dir() / gate / f"{kind}.json").read_text())
            for col, w in zip(d["columns"], d["coef"]):
                assert w * CORE_DIRECTION.get(col, 0) >= -1e-9, (gate, kind, col, w)
