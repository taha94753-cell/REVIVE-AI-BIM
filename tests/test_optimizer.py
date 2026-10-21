"""Textbook crashing case with a known optimum.

A (4 d, crash 2 d @ 100/d) -> B (3 d, crash 1 d @ 300/d);  C (6 d, crash 2 d @ 150/d) in parallel.
Normal length 7 d. Target 5 d, damages 1000/d.
Cheapest way to 5 d: A -2 d (200) and C -1 d (150) = 350.
"""
from revive.optimizer import optimise
from revive.scheduling import Activity, cpm, forecast, load_schedule


def _net():
    acts = [Activity("A", "A", "A", 4, [], 2, 100), Activity("B", "B", "B", 3, ["A"], 1, 300),
            Activity("C", "C", "C", 6, [], 2, 150)]
    fc = {"active": ["A", "B", "C"], "forecast_durations": {"A": 4, "B": 3, "C": 6}, "t0": 0.0,
          "planned_finish": 7.0, "forecast_finish": 7.0}
    return acts, fc


def test_cpm_finds_critical_path():
    acts, _ = _net()
    r = cpm(acts)
    assert r["finish"] == 7 and set(r["critical"]) == {"A", "B"}


def test_lp_reaches_known_optimum():
    acts, fc = _net()
    o = optimise(acts, fc, ld_per_day=1000, deadline=5)
    assert o["status"] == "Optimal"
    assert abs(o["recovered_finish_day"] - 5) < 1e-6
    assert abs(o["crash_cost_pkr"] - 350) < 1
    assert o["crash_days"]["B"] < 1e-6          # B is the expensive option and is left alone


def test_lp_accepts_delay_when_damages_are_cheaper():
    acts, fc = _net()
    o = optimise(acts, fc, ld_per_day=50, deadline=5)
    assert o["crash_cost_pkr"] == 0 and o["days_late_after"] == 2


def test_budget_cap_is_respected():
    acts, fc = _net()
    o = optimise(acts, fc, ld_per_day=1000, deadline=5, budget=200)
    assert o["crash_cost_pkr"] <= 200 + 1


def test_forecast_matches_ml_finish():
    acts = load_schedule()
    fc = forecast(acts, 0.25, 0.9, 40.0)
    assert abs(fc["forecast_finish"] - fc["planned_finish"] * 1.4) < 1.0
