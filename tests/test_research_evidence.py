from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.build_research_evidence import (
    MODELS,
    build_snapshot,
    comparison,
    image_bootstrap,
    validate_records,
)


def fixture_records() -> pd.DataFrame:
    rows = []
    for model in MODELS:
        for image, attack, before, after in (
            ("a", "clean", 1, 1),
            ("a", "rotation_10", 0, 1),
            ("b", "clean", 1, 0),
            ("b", "rotation_10", 0, 0),
        ):
            recovered = after if model == "am_wam" else before
            rows.append({
                "dataset": "sample", "model": model, "image_id": image, "attack": attack,
                "complete_recovery": recovered, "bit_accuracy": 0.5 + 0.5 * recovered,
                "embed_psnr_db": 40.0, "decode_ms": 20.0 if model == "am_wam" else 10.0,
            })
    return pd.DataFrame(rows)


def validate(frame: pd.DataFrame) -> None:
    validate_records(frame, expected_images={"sample": ["a", "b"]},
                     attacks=["clean", "rotation_10"])


def test_audit_rejects_count_preserving_duplicate_or_wrong_keys() -> None:
    original = fixture_records()
    validate(original)
    duplicate = original.copy()
    duplicate.iloc[1] = duplicate.iloc[0]
    with pytest.raises(ValueError, match="duplicate"):
        validate(duplicate)
    wrong = original.copy()
    wrong.loc[0, "image_id"] = "not-in-manifest"
    with pytest.raises(ValueError, match="key mismatch"):
        validate(wrong)
    invalid = original.copy()
    invalid.loc[0, "bit_accuracy"] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        validate(invalid)


def test_transition_counts_retain_benefit_and_harm_at_equal_mean() -> None:
    values = comparison(fixture_records(), iterations=100, seed=7)
    assert values["rescued"] == values["regressed"] == 1
    assert values["both_recovered"] == values["both_failed"] == 1
    assert values["recovery_gain_pp"] == 0
    assert values["decode_overhead_ms"] == 10
    assert values["recovery_ci95_pp"][0] < 0 < values["recovery_ci95_pp"][1]


def test_bootstrap_preserves_within_image_dependence_and_dataset_mix() -> None:
    # Each image's attack-average is fixed at +/- 0.5. Replicating its rows
    # must not narrow the CI by falsely adding independent samples.
    values = pd.DataFrame({"dataset": ["x", "x", "y", "y"],
                           "image_id": ["a", "a", "b", "b"],
                           "difference": [0, 1, 0, -1]})
    expected = image_bootstrap(values, iterations=100, seed=11)
    replicated = image_bootstrap(pd.concat([values] * 20), iterations=100, seed=11)
    assert expected == replicated == (0.0, [0.0, 0.0])


def test_attack_sensitivity_exposes_a_hidden_regression() -> None:
    snapshot = build_snapshot(fixture_records(),
                              categories={"clean": "control", "rotation_10": "single"},
                              iterations=100, seed=7)
    assert len(snapshot["rows"]) == 6
    excluded = next(row for row in snapshot["sensitivity"]
                    if row["excluded_attack"] == "rotation_10")
    assert excluded["recovery_gain_pp"] == -50
    assert excluded["paired_records"] == 2
    assert snapshot["rows"][0]["comparison"]["recovery_gain_pp"] == 0


def test_stratified_overall_is_weighted_by_images_not_equal_dataset_means() -> None:
    values = pd.DataFrame({"dataset": ["x", "x", "y"], "image_id": ["a", "b", "c"],
                           "difference": [1.0, 1.0, -1.0]})
    mean, bounds = image_bootstrap(values, iterations=100, seed=7)
    assert mean == pytest.approx(100 / 3)
    assert bounds == pytest.approx([100 / 3, 100 / 3])


def test_unpaired_models_are_rejected_instead_of_inner_join_dropping_rows() -> None:
    frame = fixture_records()
    with pytest.raises(ValueError, match="incomplete paired"):
        comparison(frame.iloc[:-1], iterations=100, seed=7)
