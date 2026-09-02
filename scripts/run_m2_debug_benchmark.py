from __future__ import annotations

import argparse
import csv
import json
import platform
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from watermark_lab.attacks.protocol import load_attack_protocol
from watermark_lab.core.registry import create_model
from watermark_lab.datasets.manifest import iter_manifest_images, read_manifest
from watermark_lab.experiments.runner import ExperimentRecord, run_experiment, write_results_csv

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"expected mapping in {path}")
    return value


def _mean(records: list[ExperimentRecord], field: str) -> float:
    return float(np.mean([float(getattr(record, field)) for record in records]))


def _summary_row(
    model_name: str,
    strength: float | str,
    group_name: str,
    records: list[ExperimentRecord],
) -> dict[str, Any]:
    return {
        "model": model_name,
        "strength": strength,
        "group": group_name,
        "records": len(records),
        "detection_rate": _mean(records, "detected"),
        "mean_bit_accuracy": _mean(records, "bit_accuracy"),
        "mean_ber": _mean(records, "ber"),
        "complete_recovery_rate": _mean(records, "complete_recovery"),
        "mean_embed_psnr_db": _mean(records, "embed_psnr_db"),
        "mean_post_attack_psnr_db": _mean(records, "post_attack_psnr_db"),
        "mean_encode_ms": _mean(records, "encode_ms"),
        "mean_decode_ms": _mean(records, "decode_ms"),
    }


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write empty summary")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the complete M2 debug benchmark")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs/debug_suite.yaml")
    parser.add_argument(
        "--models",
        nargs="+",
        help="optional configured model names; default: every model in the suite",
    )
    args = parser.parse_args()

    config = _load_yaml(args.config.resolve())
    calibration_path = (PROJECT_ROOT / config["outputs"]["calibration"]).resolve()
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    protocol_path = (PROJECT_ROOT / config["attacks"]["config"]).resolve()
    protocol = load_attack_protocol(protocol_path)
    output_root = (PROJECT_ROOT / config["outputs"]["results_dir"]).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    configured_models = config["models"]
    selected_models = args.models or list(configured_models)
    unknown_models = sorted(set(selected_models) - set(configured_models))
    if unknown_models:
        raise ValueError(f"models are missing from debug config: {', '.join(unknown_models)}")

    dataset_rows: list[dict[str, Any]] = []
    all_records: list[ExperimentRecord] = []
    for model_name in selected_models:
        first_dataset_id = str(config["datasets"][0]["id"])
        first_selected = calibration["models"][model_name]["datasets"][first_dataset_id][
            "selected"
        ]
        model = create_model(model_name, strength=float(first_selected["strength"]))
        for dataset in config["datasets"]:
            dataset_id = str(dataset["id"])
            selected = calibration["models"][model_name]["datasets"][dataset_id][
                "selected"
            ]
            strength = float(selected["strength"])
            model.strength = strength
            manifest = (PROJECT_ROOT / dataset["manifest"]).resolve()
            dataset_root = (PROJECT_ROOT / dataset["root"]).resolve()
            expected_records = len(read_manifest(manifest)) * len(protocol.cases)
            samples = (
                (sample.sample_id, sample.image)
                for sample in iter_manifest_images(
                    manifest,
                    dataset_root,
                    verify_sha256=True,
                )
            )
            print(
                f"running {model_name} on {dataset_id}: {expected_records} records",
                flush=True,
            )
            records = run_experiment(
                model,
                samples,
                protocol.cases,
                seed=protocol.seed,
            )
            if len(records) != expected_records:
                raise RuntimeError(
                    f"record count mismatch for {model_name}/{dataset_id}: "
                    f"{len(records)} != {expected_records}"
                )
            result_path = output_root / model_name / f"{dataset_id}.csv"
            write_results_csv(records, result_path)
            dataset_rows.append(_summary_row(model_name, strength, dataset_id, records))
            all_records.extend(records)
            print(f"saved {result_path}", flush=True)

    attack_groups: dict[tuple[str, str], list[ExperimentRecord]] = defaultdict(list)
    for record in all_records:
        attack_groups[(record.model, record.attack)].append(record)
    attack_rows = []
    for (model_name, attack_name), records in sorted(attack_groups.items()):
        attack_rows.append(_summary_row(model_name, "per_dataset", attack_name, records))

    _write_rows(output_root / "summary_by_dataset.csv", dataset_rows)
    _write_rows(output_root / "summary_by_attack.csv", attack_rows)
    write_results_csv(all_records, output_root / "all_records.csv")
    metadata = {
        "suite_id": config["suite"]["id"],
        "created_at": datetime.now().astimezone().isoformat(),
        "platform": platform.platform(),
        "protocol_id": protocol.protocol_id,
        "protocol_version": protocol.version,
        "protocol_seed": protocol.seed,
        "models": {
            name: calibration["models"][name]
            for name in selected_models
        },
        "datasets": config["datasets"],
        "record_count": len(all_records),
    }
    (output_root / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"benchmark complete: {len(all_records)} records", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
