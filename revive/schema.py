"""
Field schema: the single contract between the survey data, the model and the web form.

Every model input is declared once here with
  * the survey item code it comes from (e.g. "B12", "D2_q1", "E2"),
  * the stage at which it becomes known (award / q1 / evm25 / evm50),
  * how it is encoded (one-hot category, ordinal number, or plain number).

The web form is generated from this file (GET /api/schema), so the options
a user can pick are always exactly the options the model was trained on.
"""
from __future__ import annotations

import math
import re

# ---------------------------------------------------------------------------
# text normalisation (curly quotes, en dashes and stray spaces differ between
# Google Forms, Excel and hand entry, so every comparison goes through norm())
# ---------------------------------------------------------------------------
_DASHES = dict.fromkeys(map(ord, "\u2013\u2014\u2212"), "-")
_QUOTES = {ord("\u2019"): "'", ord("\u2018"): "'", ord("\u201c"): '"', ord("\u201d"): '"'}


def norm(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    s = str(value).translate(_DASHES).translate(_QUOTES)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


UNKNOWN = None  # ordinal value meaning "don't know" -> NaN (XGBoost handles missing natively)

# band midpoints turn count ranges into interpretable numbers
COUNT_SMALL = [("0", 0), ("1-2", 1.5), ("3-5", 4), ("6-10", 8), ("More than 10", 12)]
VARIATIONS = [("0", 0), ("1-3", 2), ("4-6", 5), ("7-10", 8.5), ("More than 10", 12)]
RFIS = [("0", 0), ("1-5", 3), ("6-15", 10.5), ("16-30", 23), ("More than 30", 35)]
WEATHER = [("0", 0), ("1-10", 5.5), ("11-30", 20.5), ("31-60", 45.5), ("More than 60", 70)]
RATING = [("1 - very poor", 1), ("2", 2), ("3", 3), ("4", 4), ("5 - very good", 5)]

FIELDS: list[dict] = [
    # ---------------- known at contract award -------------------------------
    dict(key="project_type", code="B1", stage="award", kind="category", label="Project type",
         options=["Residential building", "Commercial building", "Public building", "Industrial",
                  "Highway", "Bridge", "Water & sanitation"]),
    dict(key="contract_type", code="B2", stage="award", kind="category", label="Contract type",
         options=["Item-rate", "Lump-sum", "Design-build", "EPC", "Cost-plus"]),
    dict(key="client_sector", code="B4", stage="award", kind="category", label="Client and funding",
         options=["Public - federal PSDP", "Public - provincial ADP", "Public - autonomous body",
                  "Private", "Donor-funded", "Public-private partnership"]),
    dict(key="province", code="B5", stage="award", kind="category", label="Province",
         options=["Punjab", "Sindh", "Khyber Pakhtunkhwa", "Balochistan", "Islamabad Capital Territory",
                  "Gilgit-Baltistan", "Azad Jammu & Kashmir"]),
    dict(key="contract_value", code="B3", stage="award", kind="ordinal", label="Contract value (PKR)",
         options=[("< 50 million", 0), ("50-200 million", 1), ("200-500 million", 2),
                  ("500 million - 1 billion", 3), ("1-5 billion", 4), ("> 5 billion", 5)]),
    dict(key="planned_months", code="C1C2", stage="award", kind="number", label="Original contract duration",
         unit="months", min=1, max=120, step=1,
         help="From commencement to the completion date in the original signed contract."),
    dict(key="floor_area_m2", code="B6a", stage="award", kind="number", label="Floor area", unit="m\u00b2",
         min=0, max=500000, step=100, bim=True, help="Buildings only. Filled automatically from the IFC model."),
    dict(key="storeys", code="B7", stage="award", kind="number", label="Storeys", min=0, max=80, step=1,
         bim=True, help="Buildings only. Filled automatically from the IFC model."),
    dict(key="length_km", code="B6b", stage="award", kind="number", label="Length", unit="km",
         min=0, max=1000, step=0.5, help="Roads, pipelines and canals only."),
    dict(key="pec_category", code="B9", stage="award", kind="ordinal", label="Contractor PEC category",
         help="Lower number = higher PEC capacity (C-A is the highest).",
         options=[("C-A", 0), ("C-B", 1), ("C-1", 2), ("C-2", 3), ("C-3", 4), ("C-4", 5), ("C-5", 6),
                  ("C-6", 7), ("Don't know", UNKNOWN)]),
    dict(key="bidders", code="B10", stage="award", kind="ordinal", label="Responsive bidders",
         options=[("1 (single-source / negotiated)", 1), ("2", 2), ("3", 3), ("4-5", 4.5),
                  ("6-10", 8), ("More than 10", 12)]),
    dict(key="bid_vs_estimate", code="B11", stage="award", kind="ordinal",
         label="Winning bid vs engineer's estimate",
         options=[("More than 15% below", -20), ("5-15% below", -10), ("Within \u00b15%", 0),
                  ("5-15% above", 10), ("More than 15% above", 20), ("Don't know", UNKNOWN)]),
    dict(key="design_status", code="B12", stage="award", kind="ordinal", label="Design status at award",
         options=[("Preliminary drawings", 0), ("Partial IFC drawings", 1), ("Full IFC drawings issued", 2)]),
    dict(key="site_handover", code="B13", stage="award", kind="ordinal", label="Site handed over at start",
         options=[("Not at all", 0), ("Partially", 1), ("Fully handed over", 2)]),
    dict(key="utility_noc", code="B14", stage="award", kind="ordinal",
         label="Utility relocation or NOC needed",
         options=[("No", 0), ("Yes - obtained before start", 1), ("Yes - obtained after start", 2),
                  ("Yes - never fully resolved", 3)]),
    dict(key="supervision", code="B15", stage="award", kind="ordinal", label="Independent supervision",
         options=[("No", 0), ("Client's own staff only", 1), ("Yes", 2)]),
    dict(key="funding", code="B16", stage="award", kind="ordinal", label="Funding committed at award",
         options=[("Year-by-year allocation only", 0), ("Partially", 1), ("Fully", 2)]),
    dict(key="prior_work", code="B17", stage="award", kind="ordinal", label="Contractor worked for this client before",
         options=[("No", 0), ("Yes", 1), ("Don't know", UNKNOWN)]),
    dict(key="mobilisation_advance", code="B18", stage="award", kind="ordinal", label="Mobilisation advance in contract",
         options=[("No", 0), ("Yes", 1)]),
    dict(key="duration_setting", code="B19", stage="award", kind="ordinal", label="How the duration was set",
         options=[("Client-imposed and not achievable", 0), ("Client-imposed and achievable", 1),
                  ("Negotiated with the contractor", 2)]),
    dict(key="feasibility", code="B20", stage="award", kind="ordinal", label="Feasibility / PC-I before award",
         options=[("No", 0), ("Partially completed", 1), ("Yes - complete and approved", 2), ("Don't know", UNKNOWN)]),
    # ---------------- first-quarter signals (by 25 % of time) ----------------
    dict(key="variations_q1", code="D1_q1", stage="q1", kind="ordinal", label="Variation orders so far",
         options=VARIATIONS),
    dict(key="rfis_q1", code="D8_q1", stage="q1", kind="ordinal", label="Design changes or RFIs so far",
         options=RFIS),
    dict(key="late_payments_q1", code="D2_q1", stage="q1", kind="ordinal",
         label="IPCs paid more than 30 days late", options=COUNT_SMALL),
    dict(key="material_events_q1", code="D3_q1", stage="q1", kind="ordinal",
         label="Material shortages that stopped work", options=COUNT_SMALL),
    dict(key="weather_days_q1", code="D4_q1", stage="q1", kind="ordinal", label="Working days lost to weather",
         options=WEATHER),
    dict(key="labour_q1", code="D5_q1", stage="q1", kind="ordinal", label="Labour availability and productivity",
         options=RATING),
    dict(key="subcontractor_q1", code="D6_q1", stage="q1", kind="ordinal", label="Subcontractor performance",
         options=RATING),
    dict(key="rework_q1", code="D7_q1", stage="q1", kind="ordinal", label="Rework so far (share of contract value)",
         options=[("None", 0), ("Under 2% of contract value", 1), ("2-5%", 3.5), ("Over 5%", 6)]),
    dict(key="mobilised_q1", code="D9_q1", stage="q1", kind="ordinal", label="Contractor fully mobilised on time",
         options=[("No", 0), ("Yes", 1)]),
    # ---------------- earned value at 25 % ----------------------------------
    dict(key="spi_25", code="E2", stage="evm25", kind="number", label="SPI at 25% of time", min=0.2, max=1.5, step=0.01),
    dict(key="cpi_25", code="E5", stage="evm25", kind="number", label="CPI at 25% of time", min=0.2, max=1.5, step=0.01),
    dict(key="cert_25", code="E8", stage="evm25", kind="number", label="Value certified at 25% of time",
         unit="% of contract", min=0, max=100, step=0.5),
    # ---------------- earned value at 50 % ----------------------------------
    dict(key="spi_50", code="E3", stage="evm50", kind="number", label="SPI at 50% of time", min=0.2, max=1.5, step=0.01),
    dict(key="cpi_50", code="E6", stage="evm50", kind="number", label="CPI at 50% of time", min=0.2, max=1.5, step=0.01),
    dict(key="cert_50", code="E9", stage="evm50", kind="number", label="Value certified at 50% of time",
         unit="% of contract", min=0, max=100, step=0.5),
]

# The compact "core" question set (training.feature_set: core in config.yaml).
# Chosen by cross-validation, not by taste: on the real completed projects,
# models on these questions predict a held-out contractor's projects as well
# as or better than models on all 35 answers (docs/DATA_NOTES.md). Every one
# is in a monthly progress report or the contract, so a planning engineer can
# answer it in about two minutes. The other fields stay in the dataset for
# the descriptive analysis and can be switched back on with feature_set: all.
CORE_KEYS = (
    "planned_months", "design_status", "funding", "duration_setting",          # contract
    "variations_q1", "late_payments_q1", "subcontractor_q1",                  # first quarter
    "spi_25", "cpi_25", "cert_25",                                            # progress report at 25%
    "spi_50", "cpi_50", "cert_50",                                            # progress report at 50%
)
# The direction each core answer is allowed to move the forecast when its value
# goes UP (+1 = more overrun, -1 = less). Ordinal answers are coded so that a
# higher value means a better situation (complete design, committed funding,
# negotiated duration, better subcontractors), except the event counts.
# The linear model may set an effect to zero but never flip it.
CORE_DIRECTION = {
    "design_status": -1, "funding": -1, "duration_setting": -1,
    "variations_q1": +1, "late_payments_q1": +1, "subcontractor_q1": -1,
    "spi_25": -1, "cpi_25": -1, "cert_25": -1, "spi_50": -1, "cpi_50": -1, "cert_50": -1,
    # planned_months is left free: long jobs can drift more or absorb slips better.
}
for _f in FIELDS:
    _f["core"] = _f["key"] in CORE_KEYS

FIELD_BY_KEY = {f["key"]: f for f in FIELDS}

STAGE_LABELS = {
    "award": "Contract and site",
    "q1": "First-quarter signals",
    "evm25": "Performance at 25%",
    "evm50": "Performance at 50%",
}

# Survey items kept for descriptive analysis only (never model inputs, because
# they are only known after the project ends or are retrospective opinions).
DELAY_CAUSES = {
    "G1": "Slow client decisions or approvals", "G2": "Client's financial position",
    "G3": "Client interference in methods or specification", "G4": "Contractor cash-flow strain",
    "G5": "Weak site management and supervision", "G6": "Inadequate planning and programme control",
    "G7": "Plant and equipment shortage or breakdown", "G8": "Errors or omissions in issued design",
    "G9": "Consultant inexperience or slow approvals", "G10": "Poor client-consultant-contractor coordination",
    "G11": "Material price escalation", "G12": "Bureaucratic or regulatory obstruction",
    "G13": "Political interference", "G14": "Unforeseen ground or site conditions",
}
CAUSE_FAMILY = {"G1": "Client", "G2": "Client", "G3": "Client", "G4": "Contractor", "G5": "Contractor",
                "G6": "Contractor", "G7": "Contractor", "G8": "Design & supervision",
                "G9": "Design & supervision", "G10": "Design & supervision", "G11": "External",
                "G12": "External", "G13": "External", "G14": "External"}

# Columns deliberately EXCLUDED from the model because they leak the outcome.
LEAKAGE_EXCLUDED = {
    "D*_tot": "whole-project totals are only known at completion",
    "D10": "biggest cause of delay is judged after the fact",
    "G1-G14": "retrospective ratings of what caused the delay",
    "C3/C3b": "extension of time granted is a consequence of delay",
    "C5/C7/C8": "status, final cost and disputes are outcomes",
    "E4/E7": "SPI/CPI at 75% sit too close to completion to be an early warning",
    "F1-F5": "BIM case-study eligibility, not project performance",
    "A1-A8": "respondent information, not project attributes",
    "B8a/B8b": "award date mainly identifies the data batch, not a cause",
}


def fields_for_stages(stages, feature_set: str = "all") -> list[dict]:
    stages = set(stages)
    return [f for f in FIELDS if f["stage"] in stages and (feature_set != "core" or f["core"])]


def option_labels(field: dict) -> list[str]:
    if field["kind"] == "category":
        return list(field["options"])
    if field["kind"] == "ordinal":
        return [lab for lab, _ in field["options"]]
    return []


def match_option(field: dict, raw) -> str | None:
    """Return the canonical option label that matches a raw answer, or None."""
    key = norm(raw)
    if not key:
        return None
    for lab in option_labels(field):
        if norm(lab) == key:
            return lab
    # tolerant prefix match, e.g. "Under 2% of contract value" vs "Under 2%"
    for lab in option_labels(field):
        n = norm(lab)
        if key.startswith(n) or n.startswith(key):
            return lab
    return None


def ordinal_value(field: dict, label):
    for lab, val in field["options"]:
        if lab == label:
            return float("nan") if val is None else float(val)
    return float("nan")


def public_schema(gates: dict, feature_set: str = "all") -> dict:
    """JSON-safe description of the form, grouped by stage, for the frontend.
    Only the questions the model uses are sent, so the form never asks for more."""
    groups = []
    for stage, title in STAGE_LABELS.items():
        items = []
        for f in fields_for_stages([stage], feature_set):
            item = {k: f[k] for k in ("key", "label", "kind") if k in f}
            item["help"] = f.get("help", "")
            item["bim"] = bool(f.get("bim"))
            if f["kind"] in ("category", "ordinal"):
                item["options"] = option_labels(f)
            else:
                item.update({k: f[k] for k in ("min", "max", "step", "unit") if k in f})
            items.append(item)
        if items:
            groups.append({"stage": stage, "title": title, "fields": items})
    return {
        "groups": groups,
        "feature_set": feature_set,
        "gates": {g: {"label": v["label"], "stages": v["stages"], "elapsed_fraction": v["elapsed_fraction"]}
                  for g, v in gates.items()},
    }
