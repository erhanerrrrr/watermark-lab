from __future__ import annotations

import argparse
import csv
import json
import platform
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from watermark_lab.attacks.protocol import AttackCase, apply_attack_case, load_attack_protocol
from watermark_lab.core.registry import create_model
from watermark_lab.datasets.manifest import iter_manifest_images, read_manifest
from watermark_lab.metrics.image_quality import psnr
from watermark_lab.metrics.message import ber, bit_accuracy, complete_recovery
from watermark_lab.models.wam_adapter import OFFICIAL_COMMIT, OFFICIAL_WEIGHT_SHA256, WamModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_ATTACKS = {"local_splice", "copy_move", "local_inpaint"}
SUMMARY_METRICS = (
    "detected",
    "bit_accuracy",
    "ber",
    "complete_recovery",
    "embed_psnr_db",
    "post_attack_psnr_db",
    "encode_ms",
    "decode_ms",
    "detected_fraction",
    "mean_detection_probability",
    "maximum_detection_probability",
    "detection_centroid_x",
    "detection_centroid_y",
    "border_detection_probability",
    "center_detection_probability",
    "inside_tamper_detection_probability",
    "outside_tamper_detection_probability",
    "outside_minus_inside_detection",
    "localization_proxy_precision",
    "localization_proxy_recall",
    "localization_proxy_f1",
    "localization_proxy_iou",
)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"expected mapping in {path}")
    return value


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty result: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _local_mask(case: AttackCase, shape: tuple[int, int]) -> tuple[np.ndarray, float] | None:
    height, width = shape
    for step in case.steps:
        if step.name not in LOCAL_ATTACKS:
            continue
        ratio = float(step.parameters.get("mask_ratio", 0.1))
        side_ratio = ratio**0.5
        patch_width = max(1, round(width * side_ratio))
        patch_height = max(1, round(height * side_ratio))
        left = (width - patch_width) // 2
        top = (height - patch_height) // 2
        mask = np.zeros((height, width), dtype=bool)
        mask[top : top + patch_height, left : left + patch_width] = True
        return mask, ratio
    return None


def _safe_ratio(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator > 0 else 0.0


def _spatial_metrics(
    probabilities: np.ndarray,
    threshold: float,
    case: AttackCase,
) -> dict[str, float | str]:
    height, width = probabilities.shape
    binary = probabilities > threshold
    weights = np.maximum(probabilities, 0.0)
    total_weight = float(np.sum(weights))
    x_axis = np.linspace(0.0, 1.0, width, dtype=np.float32)
    y_axis = np.linspace(0.0, 1.0, height, dtype=np.float32)
    centroid_x = _safe_ratio(float(np.sum(weights * x_axis[None, :])), total_weight)
    centroid_y = _safe_ratio(float(np.sum(weights * y_axis[:, None])), total_weight)

    border_width = max(1, round(min(height, width) * 0.1))
    border = np.ones((height, width), dtype=bool)
    border[border_width:-border_width, border_width:-border_width] = False
    center = ~border
    result: dict[str, float | str] = {
        "detected_fraction": float(np.mean(binary)),
        "mean_detection_probability": float(np.mean(probabilities)),
        "maximum_detection_probability": float(np.max(probabilities)),
        "detection_centroid_x": centroid_x,
        "detection_centroid_y": centroid_y,
        "border_detection_probability": float(np.mean(probabilities[border])),
        "center_detection_probability": float(np.mean(probabilities[center])),
        "tamper_ratio": "",
        "inside_tamper_detection_probability": "",
        "outside_tamper_detection_probability": "",
        "outside_minus_inside_detection": "",
        "localization_proxy_precision": "",
        "localization_proxy_recall": "",
        "localization_proxy_f1": "",
        "localization_proxy_iou": "",
    }

    local = _local_mask(case, probabilities.shape)
    if local is None:
        return result
    tamper_mask, ratio = local
    expected_watermark = ~tamper_mask
    true_positive = float(np.sum(binary & expected_watermark))
    false_positive = float(np.sum(binary & tamper_mask))
    false_negative = float(np.sum((~binary) & expected_watermark))
    precision = _safe_ratio(true_positive, true_positive + false_positive)
    recall = _safe_ratio(true_positive, true_positive + false_negative)
    result.update(
        {
            "tamper_ratio": ratio,
            "inside_tamper_detection_probability": float(
                np.mean(probabilities[tamper_mask])
            ),
            "outside_tamper_detection_probability": float(
                np.mean(probabilities[expected_watermark])
            ),
            "outside_minus_inside_detection": float(
                np.mean(probabilities[expected_watermark])
                - np.mean(probabilities[tamper_mask])
            ),
            "localization_proxy_precision": precision,
            "localization_proxy_recall": recall,
            "localization_proxy_f1": _safe_ratio(
                2.0 * precision * recall,
                precision + recall,
            ),
            "localization_proxy_iou": _safe_ratio(
                true_positive,
                true_positive + false_positive + false_negative,
            ),
        }
    )
    return result


def _numeric(row: dict[str, Any], field: str) -> float | None:
    value = row[field]
    if value == "" or value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    return float(value)


def _summary_row(group: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"group": group, "records": len(rows)}
    output_names = {
        "detected": "detection_rate",
        "bit_accuracy": "mean_bit_accuracy",
        "complete_recovery": "complete_recovery_rate",
    }
    for field in SUMMARY_METRICS:
        values = [number for row in rows if (number := _numeric(row, field)) is not None]
        result[output_names.get(field, f"mean_{field}")] = (
            float(np.mean(values)) if values else ""
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run WAM Debug10 spatial diagnostics")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs/debug_suite.yaml")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "results/m3_wam_debug",
    )
    parser.add_argument("--device", default="auto", help="auto, cpu, cuda, or cuda:N")
    args = parser.parse_args()

    config = _load_yaml(args.config.resolve())
    calibration_path = (PROJECT_ROOT / config["outputs"]["calibration"]).resolve()
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    protocol_path = (PROJECT_ROOT / config["attacks"]["config"]).resolve()
    protocol = load_attack_protocol(protocol_path)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    first_dataset_id = str(config["datasets"][0]["id"])
    first_strength = float(
        calibration["models"]["wam"]["datasets"][first_dataset_id]["selected"][
            "strength"
        ]
    )
    model = create_model("wam", strength=first_strength, device=args.device)
    if not isinstance(model, WamModel):
        raise TypeError("registry returned a non-WAM model")

    all_rows: list[dict[str, Any]] = []
    dataset_summaries: list[dict[str, Any]] = []
    started_at = time.perf_counter()
    for dataset in config["datasets"]:
        dataset_id = str(dataset["id"])
        strength = float(
            calibration["models"]["wam"]["datasets"][dataset_id]["selected"][
                "strength"
            ]
        )
        model.strength = strength
        manifest_path = (PROJECT_ROOT / dataset["manifest"]).resolve()
        dataset_root = (PROJECT_ROOT / dataset["root"]).resolve()
        manifest_count = len(read_manifest(manifest_path))
        expected_records = manifest_count * len(protocol.cases)
        generator = np.random.default_rng(protocol.seed)
        dataset_rows: list[dict[str, Any]] = []
        print(f"running WAM on {dataset_id}: {expected_records} records", flush=True)

        for image_index, sample in enumerate(
            iter_manifest_images(manifest_path, dataset_root, verify_sha256=True),
            start=1,
        ):
            message = generator.integers(0, 2, size=model.message_bits, dtype=np.uint8)
            encode_started = time.perf_counter()
            embedded = model.encode(sample.image, message)
            encode_ms = (time.perf_counter() - encode_started) * 1000.0
            embed_quality = psnr(sample.image, embedded.image)

            for case in protocol.cases:
                attacked = apply_attack_case(embedded.image, case, generator)
                decode_started = time.perf_counter()
                decoded = model.decode(attacked)
                decode_ms = (time.perf_counter() - decode_started) * 1000.0
                if decoded.localization is None:
                    raise RuntimeError("WAM decode did not return a localization map")
                row: dict[str, Any] = {
                    "dataset": dataset_id,
                    "image_id": sample.sample_id,
                    "model": model.name,
                    "strength": strength,
                    "attack": case.case_id,
                    "category": case.category,
                    "attack_parameters": json.dumps(
                        case.parameters_for_record(),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "message_bits": model.message_bits,
                    "detected": decoded.detected,
                    "decode_confidence": decoded.confidence,
                    "bit_accuracy": bit_accuracy(message, decoded.message),
                    "ber": ber(message, decoded.message),
                    "complete_recovery": complete_recovery(message, decoded.message),
                    "embed_psnr_db": embed_quality,
                    "post_attack_psnr_db": psnr(sample.image, attacked),
                    "encode_ms": encode_ms,
                    "decode_ms": decode_ms,
                    **_spatial_metrics(
                        decoded.localization,
                        model.detection_threshold,
                        case,
                    ),
                }
                dataset_rows.append(row)
            print(
                f"  {image_index:02d}/{manifest_count}: {sample.sample_id}",
                flush=True,
            )

        if len(dataset_rows) != expected_records:
            raise RuntimeError(
                f"record count mismatch for {dataset_id}: "
                f"{len(dataset_rows)} != {expected_records}"
            )
        _write_rows(output_dir / "by_dataset" / f"{dataset_id}.csv", dataset_rows)
        dataset_summaries.append(_summary_row(dataset_id, dataset_rows))
        all_rows.extend(dataset_rows)

    _write_rows(output_dir / "all_records.csv", all_rows)
    _write_rows(output_dir / "summary_by_dataset.csv", dataset_summaries)
    category_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    attack_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in all_rows:
        category_groups[str(row["category"])].append(row)
        attack_groups[str(row["attack"])].append(row)
    category_rows = [
        _summary_row(category, category_groups[category])
        for category in ("control", "single", "compound")
    ]
    attack_rows = [
        _summary_row(attack, attack_groups[attack]) for attack in sorted(attack_groups)
    ]
    _write_rows(output_dir / "summary_by_category.csv", category_rows)
    _write_rows(output_dir / "summary_by_attack.csv", attack_rows)

    metadata = {
        "suite_id": config["suite"]["id"],
        "created_at": datetime.now().astimezone().isoformat(),
        "elapsed_seconds": time.perf_counter() - started_at,
        "platform": platform.platform(),
        "device": model._backend.device_name,
        "official_commit": OFFICIAL_COMMIT,
        "checkpoint_sha256": OFFICIAL_WEIGHT_SHA256,
        "protocol_id": protocol.protocol_id,
        "protocol_version": protocol.version,
        "protocol_seed": protocol.seed,
        "record_count": len(all_rows),
        "calibration": calibration["models"]["wam"],
        "localization_note": (
            "Local-attack precision/recall/F1/IoU use the unmodified region as a proxy "
            "watermark-presence target; splice and copy-move may retain transformed watermark."
        ),
    }
    (output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"WAM diagnostics complete: {len(all_rows)} records", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
