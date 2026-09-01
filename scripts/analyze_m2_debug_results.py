from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]

METRIC_FIELDS = (
    "detected",
    "bit_accuracy",
    "ber",
    "complete_recovery",
    "embed_psnr_db",
    "post_attack_psnr_db",
    "encode_ms",
    "decode_ms",
)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _load_attack_categories(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    return {str(case["id"]): str(case["category"]) for case in config["cases"]}


def _number(row: dict[str, str], field: str) -> float:
    if field in {"detected", "complete_recovery"}:
        return float(row[field].strip().lower() == "true")
    return float(row[field])


def _summarize(
    model: str,
    group: str,
    rows: Iterable[dict[str, str]],
    *,
    attack_count: int,
) -> dict[str, Any]:
    materialized = list(rows)
    if not materialized:
        raise ValueError(f"cannot summarize empty group: {model}/{group}")
    result: dict[str, Any] = {
        "model": model,
        "group": group,
        "attack_count": attack_count,
        "records": len(materialized),
    }
    output_names = {
        "detected": "detection_rate",
        "bit_accuracy": "mean_bit_accuracy",
        "ber": "mean_ber",
        "complete_recovery": "complete_recovery_rate",
        "embed_psnr_db": "mean_embed_psnr_db",
        "post_attack_psnr_db": "mean_post_attack_psnr_db",
        "encode_ms": "mean_encode_ms",
        "decode_ms": "mean_decode_ms",
    }
    for field in METRIC_FIELDS:
        result[output_names[field]] = float(
            np.mean([_number(row, field) for row in materialized])
        )
    return result


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze completed M2 debug benchmark CSV")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=PROJECT_ROOT / "results/m2_debug",
    )
    parser.add_argument(
        "--attacks",
        type=Path,
        default=PROJECT_ROOT / "configs/attacks.yaml",
    )
    args = parser.parse_args()

    results_dir = args.results_dir.resolve()
    rows = _read_rows(results_dir / "all_records.csv")
    categories = _load_attack_categories(args.attacks.resolve())
    for row in rows:
        attack = row["attack"]
        if attack not in categories:
            raise KeyError(f"attack {attack!r} is missing from protocol")
        row["attack_category"] = categories[attack]

    models = sorted({row["model"] for row in rows})
    protocol_attacks = sorted(categories)
    expected_records = len(models) * len(protocol_attacks) * 40
    if len(rows) != expected_records:
        raise RuntimeError(
            f"expected {expected_records} records for 40 images, got {len(rows)}"
        )
    for model in models:
        for attack in protocol_attacks:
            record_count = sum(
                row["model"] == model and row["attack"] == attack for row in rows
            )
            if record_count != 40:
                raise RuntimeError(
                    f"expected 40 records for {model}/{attack}, got {record_count}"
                )

    overall_rows: list[dict[str, Any]] = []
    category_rows: list[dict[str, Any]] = []
    for model in models:
        model_rows = [row for row in rows if row["model"] == model]
        overall_rows.append(
            _summarize(model, "all_44", model_rows, attack_count=len(protocol_attacks))
        )
        attacked_rows = [row for row in model_rows if row["attack"] != "clean"]
        overall_rows.append(
            _summarize(
                model,
                "attacked_only_43",
                attacked_rows,
                attack_count=len(protocol_attacks) - 1,
            )
        )
        for category in ("control", "single", "compound"):
            selected = [
                row for row in model_rows if row["attack_category"] == category
            ]
            attack_count = len({row["attack"] for row in selected})
            category_rows.append(
                _summarize(model, category, selected, attack_count=attack_count)
            )

    attack_groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        attack_groups[(row["model"], row["attack"])].append(row)
    attack_rows = [
        {
            **_summarize(model, attack, selected, attack_count=1),
            "category": categories[attack],
        }
        for (model, attack), selected in sorted(attack_groups.items())
    ]

    _write_rows(results_dir / "summary_overall.csv", overall_rows)
    _write_rows(results_dir / "summary_by_category.csv", category_rows)
    _write_rows(results_dir / "summary_by_attack_detailed.csv", attack_rows)

    comparison: list[dict[str, Any]] = []
    by_model_attack = {(row["model"], row["group"]): row for row in attack_rows}
    if models == ["dwt_dct", "trustmark_q"]:
        for attack in protocol_attacks:
            dwt = by_model_attack[("dwt_dct", attack)]
            trustmark = by_model_attack[("trustmark_q", attack)]
            comparison.append(
                {
                    "attack": attack,
                    "category": categories[attack],
                    "dwt_detection_rate": dwt["detection_rate"],
                    "trustmark_detection_rate": trustmark["detection_rate"],
                    "trustmark_minus_dwt_detection": (
                        trustmark["detection_rate"] - dwt["detection_rate"]
                    ),
                    "dwt_bit_accuracy": dwt["mean_bit_accuracy"],
                    "trustmark_bit_accuracy": trustmark["mean_bit_accuracy"],
                    "trustmark_minus_dwt_bit_accuracy": (
                        trustmark["mean_bit_accuracy"] - dwt["mean_bit_accuracy"]
                    ),
                    "dwt_complete_recovery_rate": dwt["complete_recovery_rate"],
                    "trustmark_complete_recovery_rate": trustmark[
                        "complete_recovery_rate"
                    ],
                    "trustmark_minus_dwt_complete_recovery": (
                        trustmark["complete_recovery_rate"]
                        - dwt["complete_recovery_rate"]
                    ),
                }
            )
        _write_rows(results_dir / "comparison_by_attack.csv", comparison)

    print(f"verified records: {len(rows)}")
    print("overall:")
    for row in overall_rows:
        print(
            f"  {row['model']:11s} {row['group']:16s} "
            f"det={row['detection_rate']:.4f} "
            f"bit_acc={row['mean_bit_accuracy']:.4f} "
            f"complete={row['complete_recovery_rate']:.4f} "
            f"embed_psnr={row['mean_embed_psnr_db']:.3f}"
        )
    print("by category:")
    for row in category_rows:
        print(
            f"  {row['model']:11s} {row['group']:8s} "
            f"n_attacks={row['attack_count']:2d} "
            f"det={row['detection_rate']:.4f} "
            f"bit_acc={row['mean_bit_accuracy']:.4f} "
            f"complete={row['complete_recovery_rate']:.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
