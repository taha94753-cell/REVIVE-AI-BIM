"""
Sustainability impact of an early, optimised recovery.

Two quantities are reported, and kept separate on purpose:
  * AVOIDED  - site diesel and time-related overheads that are not spent because the
               project finishes N days earlier than the forecast (N from the optimiser).
  * AT RISK  - embodied carbon of the structure (concrete + rebar from the IFC model)
               that rework at the current rework rate would repeat. This is an
               exposure figure, not a saving, and is labelled that way in the UI.
Every factor comes from config.yaml and is listed back with the result, so the
numbers can be checked and cited.
"""
from __future__ import annotations

from .config import load_config
from .schema import norm


def rework_share(label: str | None) -> float:
    table = load_config()["sustainability"]["rework_share_by_band"]
    key = norm(label)
    if not key:
        return 0.0
    for k, v in table.items():
        nk = norm(k)
        if key == nk or key.startswith(nk) or nk.startswith(key):
            return float(v)
    return 0.0


def impact(optimisation: dict, quantities: dict, rework_label: str | None = None) -> dict:
    s = load_config()["sustainability"]
    ok = optimisation.get("status") == "Optimal"
    days = max(0.0, float(optimisation.get("days_recovered", 0))) if ok else 0.0
    diesel = days * s["diesel_l_per_site_day"]
    co2_diesel_t = diesel * s["ef_diesel_kgco2_per_l"] / 1000
    overhead = days * s["site_overhead_pkr_per_day"]
    ld_avoided = (optimisation.get("ld_before_pkr", 0) - optimisation.get("ld_after_pkr", 0)) if ok else 0
    crash = optimisation.get("crash_cost_pkr", 0) if ok else 0

    has_bim = bool(quantities) and "concrete_m3" in (quantities or {})
    concrete_m3 = float(quantities.get("concrete_m3", 0) or 0) if has_bim else None
    rebar_t = float(quantities.get("rebar_t_estimate", 0) or 0) if has_bim else 0.0
    structure_t = ((concrete_m3 * s["concrete_density_kg_m3"] * s["ef_concrete_kgco2e_per_kg"]
                    + rebar_t * 1000 * s["ef_steel_kgco2e_per_kg"]) / 1000) if has_bim else None
    share = rework_share(rework_label)
    return {
        "days_recovered": round(days, 1),
        "diesel_l_avoided": round(diesel),
        "co2_diesel_t_avoided": round(co2_diesel_t, 1),
        "overheads_pkr_avoided": round(overhead),
        "ld_pkr_avoided": round(ld_avoided),
        "crash_cost_pkr": round(crash),
        "net_benefit_pkr": round(ld_avoided + overhead - crash),
        "structure_embodied_t": None if structure_t is None else round(structure_t, 1),
        "rework_share": share,
        "rework_carbon_at_risk_t": None if structure_t is None else round(structure_t * share, 1),
        "assumptions": [
            {"item": "Site diesel (generators, idle plant)", "value": s["diesel_l_per_site_day"], "unit": "L/day", "verify": True},
            {"item": "Diesel emission factor", "value": s["ef_diesel_kgco2_per_l"], "unit": "kgCO2/L", "verify": True},
            {"item": "Concrete emission factor", "value": s["ef_concrete_kgco2e_per_kg"], "unit": "kgCO2e/kg", "verify": True},
            {"item": "Reinforcement emission factor", "value": s["ef_steel_kgco2e_per_kg"], "unit": "kgCO2e/kg", "verify": True},
            {"item": "Reinforcement rate", "value": s["rebar_kg_per_m3_concrete"], "unit": "kg/m3", "verify": True},
            {"item": "Time-related site overheads", "value": s["site_overhead_pkr_per_day"], "unit": "PKR/day", "verify": True},
        ] + ([{"item": "Concrete volume (from IFC)", "value": concrete_m3, "unit": "m3", "verify": False}] if has_bim else []),
    }
