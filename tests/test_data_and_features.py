import numpy as np
import pandas as pd

from revive.data import load_clean
from revive.features import encode, encode_one, gate_columns
from revive.schema import FIELDS, match_option


def test_clean_dataset_has_targets_and_no_identifiers():
    df = load_clean()
    assert len(df) >= 100
    assert df["time_overrun_pct"].notna().sum() >= 100
    for banned in ("CONTACT", "email", "Timestamp", "project_code", "B5b"):
        assert banned not in df.columns


def test_every_answer_maps_to_a_schema_option():
    df = load_clean()
    for f in FIELDS:
        if f["kind"] in ("category", "ordinal"):
            vals = df[f["key"]].dropna().unique()
            assert all(match_option(f, v) for v in vals), f["key"]


def test_single_row_encoding_matches_batch_encoding():
    df = load_clean().head(5)
    for gate in ("G25", "G50"):
        batch = encode(df, gate)
        assert list(batch.columns) == gate_columns(gate)
        one = encode_one({f["key"]: df.iloc[2][f["key"]] for f in FIELDS}, gate)
        np.testing.assert_allclose(one.iloc[0].to_numpy(dtype=float), batch.iloc[2].to_numpy(dtype=float), equal_nan=True)


def test_unknown_answers_become_missing_not_zero():
    X = encode_one({"design_status": "Something else", "spi_25": None}, "G25")
    assert np.isnan(X["design_status"].iloc[0]) and np.isnan(X["spi_25"].iloc[0])
