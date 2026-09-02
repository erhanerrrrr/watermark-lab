from __future__ import annotations

import pandas as pd

from scripts.analyze_formal_results import (
    METRICS,
    _bootstrap_model_summaries,
    _paired_comparisons,
)


def _analysis_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for model, offset in (("am_wam", 0.1), ("wam", 0.0)):
        for image_id, base in (("a", 1.0), ("b", 0.0)):
            for attack in ("clean", "jpeg"):
                row: dict[str, object] = {
                    "model": model,
                    "dataset": "dataset",
                    "image_id": image_id,
                    "attack": attack,
                    "category": "control" if attack == "clean" else "compression",
                }
                row.update({metric: base + offset for metric in METRICS})
                rows.append(row)
    return pd.DataFrame(rows)


def test_model_bootstrap_uses_image_units() -> None:
    summaries = _bootstrap_model_summaries(
        _analysis_frame(),
        iterations=20,
        seed=7,
    )
    row = summaries[
        (summaries["model"] == "wam")
        & (summaries["scope"] == "overall")
        & (summaries["metric"] == "bit_accuracy")
    ].iloc[0]
    assert row["records"] == 4
    assert row["bootstrap_image_units"] == 2
    assert row["mean"] == 0.5


def test_paired_comparisons_cover_all_reported_metrics() -> None:
    comparisons = _paired_comparisons(
        _analysis_frame(),
        reference="am_wam",
        iterations=20,
        seed=7,
    )
    overall = comparisons[comparisons["scope"] == "overall"]
    assert set(overall["metric"]) == set(METRICS)
    assert set(overall["bootstrap_image_units"]) == {2}
