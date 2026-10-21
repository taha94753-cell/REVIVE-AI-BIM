"""
Data ingestion: raw survey workbook  ->  anonymised, cleaned, human-readable CSV.

What happens here, in order
  1. Columns are recognised by their survey code ("B12 –", "D2_q1 –", "[G4 ...]"),
     so re-worded question text or a new Google Forms export still loads.
  2. Personal / identifying data is dropped: timestamps, consent text, e-mail
     contacts, city names and the private project-code key. Each row gets a
     neutral id (PRJ-001 ...). Only the source group (C01, EXT, SYN ...) is kept
     so the model card can report data provenance honestly.
  3. Every answer is mapped onto the canonical option list in schema.py.
     Answers that do not match are reported, never silently guessed.
  4. Targets are derived from dates and costs:
        time_overrun_pct = (actual duration / planned duration - 1) x 100
        cost_overrun_pct = (final cost / original cost - 1) x 100
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .config import load_config, path, reports_dir
from .scheduling import DAYS_PER_MONTH
from .schema import CAUSE_FAMILY, FIELDS, match_option, norm

CODE_RE = re.compile(r"^\s*([A-Z]\d+[a-z]?(?:_q1|_tot)?)\s*[\u2013\u2014-]")
GCODE_RE = re.compile(r"\[(G\d+)\b")

CAUSE_OPTIONS = ["Payment delays", "Design changes / incomplete drawings", "Material shortage or price",
                 "Labour issues", "Weather", "Contractor management", "Client decision-making",
                 "Regulatory / approvals", "Land acquisition / right of way", "Funding release",
                 "No significant delay"]


def _code_for(col: str) -> str | None:
    col = str(col)
    if col.strip().lower() == "project code":
        return "project_code"
    m = GCODE_RE.search(col)
    if m:
        return m.group(1)
    m = CODE_RE.match(col)
    return m.group(1) if m else None


def read_raw(file: str | Path | None = None, sheet: str | None = None) -> pd.DataFrame:
    cfg = load_config()["data"]
    file = Path(file) if file else path(cfg["raw_file"])
    xl = pd.ExcelFile(file)
    sheet = sheet or cfg.get("raw_sheet")
    if sheet not in xl.sheet_names:
        sheet = xl.sheet_names[0]
    raw = xl.parse(sheet)
    rename, seen = {}, set()
    for col in raw.columns:
        code = _code_for(col)
        if code and code not in seen:
            rename[col] = code
            seen.add(code)
    df = raw[list(rename)].rename(columns=rename)
    df = df.dropna(how="all")
    return df.reset_index(drop=True)


def _to_date(s):
    return pd.to_datetime(s, errors="coerce")


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def clean(raw: pd.DataFrame, id_prefix: str = "PRJ") -> tuple[pd.DataFrame, dict]:
    out = pd.DataFrame(index=raw.index)
    out["project_id"] = [f"{id_prefix}-{i + 1:03d}" for i in range(len(raw))]
    codes = raw["project_code"].astype(str) if "project_code" in raw else pd.Series([""] * len(raw))
    grp = codes.str.extract(r"^([A-Z]+\d*)", expand=False).fillna("UNCODED")
    out["source_group"] = grp.replace("NA", "UNCODED")
    out["is_hypothetical"] = out["source_group"].eq("SYN")
    out["info_source"] = raw.get("A7")
    out["respondent_role"] = raw.get("A1")

    quality: dict = {"rows": int(len(raw)), "unmatched_answers": {}, "missing_by_field": {}}

    c1, c2, c4 = (_to_date(raw.get(k)) for k in ("C1", "C2", "C4"))
    planned_days = (c2 - c1).dt.days
    actual_days = (c4 - c1).dt.days

    for f in FIELDS:
        key, code = f["key"], f["code"]
        if key == "planned_months":
            out[key] = (planned_days / DAYS_PER_MONTH).round(1)
            continue
        col = raw.get(code)
        if col is None:
            out[key] = np.nan
            quality["missing_by_field"][key] = int(len(raw))
            continue
        if f["kind"] == "number":
            vals = _num(col)
            if key in ("floor_area_m2", "storeys", "length_km"):
                vals = vals.fillna(0.0)
            out[key] = vals
        else:
            labels = col.map(lambda v: match_option(f, v))
            bad = sorted({str(v) for v, lab in zip(col, labels) if lab is None and norm(v)})
            if bad:
                quality["unmatched_answers"][key] = bad
            out[key] = labels
        quality["missing_by_field"][key] = int(pd.isna(out[key]).sum())

    # descriptive-only survey items
    for g in CAUSE_FAMILY:
        out[g] = _num(raw.get(g)) if g in raw else np.nan          # "NE" (not experienced) -> NaN
    if "D10" in raw:
        fake = {"key": "d10", "kind": "category", "options": CAUSE_OPTIONS}
        out["main_delay_cause"] = raw["D10"].map(lambda v: match_option(fake, v) or ("Other / multiple causes" if norm(v) else None))
    out["status"] = raw.get("C5")
    out["award_year"] = _num(raw.get("B8b"))
    out["eot_months"] = _num(raw.get("C3"))

    # targets
    out["actual_months"] = (actual_days / DAYS_PER_MONTH).round(1)
    with np.errstate(divide="ignore", invalid="ignore"):
        out["time_overrun_pct"] = ((actual_days / planned_days) - 1.0) * 100.0
        c6, c7 = _num(raw.get("C6")), _num(raw.get("C7"))
        out["cost_overrun_pct"] = (c7 / c6 - 1.0) * 100.0
        out["original_cost_pkr_m"] = c6
    out.loc[planned_days <= 0, "time_overrun_pct"] = np.nan
    # A terminated contract has no completion outcome: its "completion" date is the
    # termination date, which would read as finishing early. Exclude it from the targets.
    terminated = out["status"].astype(str).str.strip().str.lower().eq("terminated")
    out.loc[terminated, ["time_overrun_pct", "cost_overrun_pct"]] = np.nan
    quality_terminated = int(terminated.sum())
    out["time_overrun_pct"] = out["time_overrun_pct"].round(2)
    out["cost_overrun_pct"] = out["cost_overrun_pct"].round(2)

    quality["rows_with_time_target"] = int(out["time_overrun_pct"].notna().sum())
    quality["rows_with_cost_target"] = int(out["cost_overrun_pct"].notna().sum())
    quality["source_groups"] = out["source_group"].value_counts().to_dict()
    quality["status"] = out["status"].value_counts(dropna=False).rename(str).to_dict() if "status" in out else {}
    quality["hypothetical_rows"] = int(out["is_hypothetical"].sum())
    quality["terminated_excluded_from_targets"] = quality_terminated
    return out, quality


def ingest(file: str | Path | None = None, sheet: str | None = None, save: bool = True) -> tuple[pd.DataFrame, dict]:
    raw = read_raw(file, sheet)
    df, quality = clean(raw)
    if save:
        dest = path(load_config()["data"]["clean_file"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(dest, index=False)
        (reports_dir() / "data_quality.json").write_text(json.dumps(quality, indent=2, default=str))
    return df, quality


def load_clean() -> pd.DataFrame:
    return pd.read_csv(path(load_config()["data"]["clean_file"]))
