"""One-call setup used by `python -m revive setup` and by the server on first start."""
from __future__ import annotations

from .config import load_config, models_dir, path


def bootstrap(verbose: bool = True) -> dict:
    cfg = load_config()
    done = {}
    clean = path(cfg["data"]["clean_file"])
    if not clean.exists():
        raw = path(cfg["data"]["raw_file"])
        if not raw.exists():
            raise FileNotFoundError(
                f"No data found. Put your survey workbook at {raw} (or a cleaned CSV at {clean}) and run again.")
        from .data import ingest
        _, q = ingest()
        done["ingest"] = q
        if verbose:
            print(f"Ingested {q['rows']} rows -> {clean}")
    if not (models_dir() / "model_card.json").exists():
        from .modeling import train
        if verbose:
            print("Training models (about 20-40 s) ...")
        train(verbose=verbose)
        done["train"] = True
    ifc = path(cfg["bim"]["ifc_file"])
    if cfg["bim"].get("start_with_demo_model", True) and not ifc.exists():
        from .sample_ifc import build
        build(ifc)
        done["sample_ifc"] = str(ifc)
        if verbose:
            print(f"Generated illustrative IFC model -> {ifc}")
    return done
