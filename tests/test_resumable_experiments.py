from __future__ import annotations

import csv
from pathlib import Path

from scripts.run_formal_benchmark import _result_matches, _stable_sample_seed
from scripts.run_m4_multi_message import _partial_matches


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_formal_sample_seed_is_stable_and_image_specific() -> None:
    first = _stable_sample_seed(42, "dataset", "image-a")
    assert first == _stable_sample_seed(42, "dataset", "image-a")
    assert first != _stable_sample_seed(42, "dataset", "image-b")
    assert first != _stable_sample_seed(43, "dataset", "image-a")


def test_formal_checkpoint_requires_exact_image_attack_pairs(tmp_path: Path) -> None:
    path = tmp_path / "result.csv"
    _write_csv(
        path,
        [
            {"image_id": "a", "attack": "clean"},
            {"image_id": "a", "attack": "jpeg"},
        ],
    )
    assert _result_matches(path, image_ids=["a"], attack_ids=["clean", "jpeg"])
    assert not _result_matches(path, image_ids=["a"], attack_ids=["clean"])


def test_m4_checkpoint_requires_full_cross_product(tmp_path: Path) -> None:
    path = tmp_path / "partial.csv"
    rows = [
        {
            "dataset": "dataset",
            "image_id": "image",
            "scenario": scenario,
            "attack": "clean",
            "decoder": decoder,
        }
        for scenario in ("two", "three")
        for decoder in ("official", "adaptive")
    ]
    _write_csv(path, rows)
    assert _partial_matches(
        path,
        dataset_id="dataset",
        image_id="image",
        scenario_ids=["two", "three"],
        attack_ids=["clean"],
        decoder_ids=["official", "adaptive"],
    )
    rows.pop()
    _write_csv(path, rows)
    assert not _partial_matches(
        path,
        dataset_id="dataset",
        image_id="image",
        scenario_ids=["two", "three"],
        attack_ids=["clean"],
        decoder_ids=["official", "adaptive"],
    )
