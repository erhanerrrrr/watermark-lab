from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GEOMETRY_ATTACKS = {
    "resize_roundtrip",
    "crop_resize",
    "horizontal_flip",
    "rotation",
    "perspective",
}
LOCAL_ATTACKS = {"local_splice", "copy_move", "local_inpaint"}


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _attack_metadata(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    with path.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    categories: dict[str, str] = {}
    families: dict[str, str] = {}
    for case in config["cases"]:
        attack_id = str(case["id"])
        category = str(case["category"])
        step_names = {str(step["name"]) for step in case["pipeline"]}
        categories[attack_id] = category
        if category == "control":
            families[attack_id] = "control"
        elif category == "compound":
            families[attack_id] = "compound"
        elif step_names & LOCAL_ATTACKS:
            families[attack_id] = "local"
        elif step_names & GEOMETRY_ATTACKS:
            families[attack_id] = "geometry"
        else:
            families[attack_id] = "value"
    return categories, families


def _number(row: dict[str, str], field: str) -> float:
    if field in {"detected", "complete_recovery"}:
        return float(row[field].strip().lower() == "true")
    return float(row[field])


def _summary(model: str, group: str, rows: list[dict[str, str]]) -> dict[str, Any]:
    if not rows:
        raise ValueError(f"empty group: {model}/{group}")
    return {
        "model": model,
        "group": group,
        "attack_count": len({row["attack"] for row in rows}),
        "records": len(rows),
        "detection_rate": float(np.mean([_number(row, "detected") for row in rows])),
        "mean_bit_accuracy": float(
            np.mean([_number(row, "bit_accuracy") for row in rows])
        ),
        "mean_ber": float(np.mean([_number(row, "ber") for row in rows])),
        "complete_recovery_rate": float(
            np.mean([_number(row, "complete_recovery") for row in rows])
        ),
        "mean_embed_psnr_db": float(
            np.mean([_number(row, "embed_psnr_db") for row in rows])
        ),
        "mean_post_attack_psnr_db": float(
            np.mean([_number(row, "post_attack_psnr_db") for row in rows])
        ),
        "mean_encode_ms": float(np.mean([_number(row, "encode_ms") for row in rows])),
        "mean_decode_ms": float(np.mean([_number(row, "decode_ms") for row in rows])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare M3 WAM with matched-PSNR M2 baselines")
    parser.add_argument(
        "--m2-records",
        type=Path,
        default=PROJECT_ROOT / "results/m2_debug/all_records.csv",
    )
    parser.add_argument(
        "--wam-records",
        type=Path,
        default=PROJECT_ROOT / "results/m3_wam_debug/all_records.csv",
    )
    parser.add_argument(
        "--attacks",
        type=Path,
        default=PROJECT_ROOT / "configs/attacks.yaml",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "results/m3_wam_debug",
    )
    args = parser.parse_args()

    categories, families = _attack_metadata(args.attacks.resolve())
    rows = _read_rows(args.m2_records.resolve()) + _read_rows(args.wam_records.resolve())
    for row in rows:
        attack = row["attack"]
        row["category"] = categories[attack]
        row["family"] = families[attack]

    models = ("dwt_dct", "trustmark_q", "wam")
    expected_records = len(models) * len(categories) * 40
    if len(rows) != expected_records:
        raise RuntimeError(f"expected {expected_records} records, got {len(rows)}")

    overall_rows: list[dict[str, Any]] = []
    family_rows: list[dict[str, Any]] = []
    attack_rows: list[dict[str, Any]] = []
    for model in models:
        model_rows = [row for row in rows if row["model"] == model]
        overall_rows.append(_summary(model, "all_44", model_rows))
        overall_rows.append(
            _summary(
                model,
                "attacked_only_43",
                [row for row in model_rows if row["attack"] != "clean"],
            )
        )
        for family in ("control", "value", "geometry", "local", "compound"):
            family_rows.append(
                _summary(
                    model,
                    family,
                    [row for row in model_rows if row["family"] == family],
                )
            )
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in model_rows:
            grouped[row["attack"]].append(row)
        for attack in sorted(grouped):
            attack_rows.append(
                {
                    **_summary(model, attack, grouped[attack]),
                    "category": categories[attack],
                    "family": families[attack],
                }
            )

    output_dir = args.output_dir.resolve()
    _write_rows(output_dir / "comparison_overall.csv", overall_rows)
    _write_rows(output_dir / "comparison_by_family.csv", family_rows)
    _write_rows(output_dir / "comparison_all_models_by_attack.csv", attack_rows)

    print("matched-PSNR comparison by attack family:")
    for row in family_rows:
        print(
            f"  {row['model']:11s} {row['group']:8s} "
            f"n={row['attack_count']:2d} "
            f"bit_acc={row['mean_bit_accuracy']:.4f} "
            f"complete={row['complete_recovery_rate']:.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
