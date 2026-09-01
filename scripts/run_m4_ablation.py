from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from watermark_lab.attacks.protocol import apply_attack_case, load_attack_protocol
from watermark_lab.datasets.manifest import iter_manifest_images
from watermark_lab.innovations.content_adaptive import (
    AdaptiveStrengthConfig,
    ContentAdaptiveStrengthController,
)
from watermark_lab.innovations.geometry_sync import GeometrySyncConfig, GeometrySyncDecoder
from watermark_lab.metrics.image_quality import psnr
from watermark_lab.metrics.message import bit_accuracy, complete_recovery
from watermark_lab.models.wam_adapter import OFFICIAL_COMMIT, OFFICIAL_WEIGHT_SHA256, WamModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VARIANTS = (
    ("A0_fixed_identity", "fixed", False),
    ("A1_fixed_geometry", "fixed", True),
    ("A2_adaptive_identity", "adaptive", False),
    ("A3_adaptive_geometry", "adaptive", True),
)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        result = yaml.safe_load(stream)
    if not isinstance(result, dict):
        raise ValueError(f"expected a mapping in {path}")
    return result


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _fixed_message(dataset_id: str, sample_id: str) -> np.ndarray:
    digest = hashlib.sha256(f"m4:{dataset_id}:{sample_id}".encode()).digest()
    return np.unpackbits(np.frombuffer(digest[:4], dtype=np.uint8)).astype(np.uint8)


def _attack_rng(seed: int, dataset_id: str, sample_id: str, attack_id: str):
    digest = hashlib.sha256(
        f"{seed}:{dataset_id}:{sample_id}:{attack_id}".encode()
    ).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "little"))


def _mean(rows: list[dict[str, Any]], field: str) -> float:
    return float(np.mean([float(row[field]) for row in rows]))


def _summaries(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_variant_attack: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_variant[str(row["variant"])].append(row)
        by_variant_attack[(str(row["variant"]), str(row["attack"]))].append(row)

    def summarize(group: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "records": len(group),
            "images": len({(row["dataset"], row["image_id"]) for row in group}),
            "mean_embed_psnr_db": _mean(group, "embed_psnr_db"),
            "minimum_embed_psnr_db": min(float(row["embed_psnr_db"]) for row in group),
            "mean_selected_strength": _mean(group, "selected_strength"),
            "mean_bit_accuracy": _mean(group, "bit_accuracy"),
            "complete_recovery_rate": _mean(group, "complete_recovery"),
            "mean_decode_ms": _mean(group, "decode_ms"),
            "non_identity_selection_rate": float(
                np.mean([row["selected_transform"] != "identity" for row in group])
            ),
        }

    overall = [
        {"variant": variant, **summarize(by_variant[variant])}
        for variant, _, _ in VARIANTS
    ]
    by_attack = [
        {"variant": variant, "attack": attack, **summarize(group)}
        for (variant, attack), group in sorted(by_variant_attack.items())
    ]
    return overall, by_attack


def main() -> int:
    parser = argparse.ArgumentParser(description="Run M4 WAM geometry/adaptive ablation")
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs/m4_ablation.yaml",
    )
    parser.add_argument("--device", default="auto")
    parser.add_argument(
        "--limit-per-dataset",
        type=int,
        help="optional deterministic pilot limit; default uses all manifest images",
    )
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.limit_per_dataset is not None and args.limit_per_dataset < 1:
        raise ValueError("--limit-per-dataset must be positive")

    config = _load_yaml(args.config.resolve())
    debug = _load_yaml((PROJECT_ROOT / config["inputs"]["debug_suite"]).resolve())
    calibration = json.loads(
        (PROJECT_ROOT / config["inputs"]["calibration"])
        .resolve()
        .read_text(encoding="utf-8")
    )
    protocol = load_attack_protocol(
        (PROJECT_ROOT / config["inputs"]["attack_protocol"]).resolve()
    )
    focus_ids = list(config["focus_attacks"])
    cases_by_id = {case.case_id: case for case in protocol.cases}
    missing = set(focus_ids) - set(cases_by_id)
    if missing:
        raise ValueError(f"unknown focus attack IDs: {sorted(missing)}")
    focus_cases = [cases_by_id[case_id] for case_id in focus_ids]

    adaptive_config = AdaptiveStrengthConfig(**config["adaptive_strength"])
    geometry_raw = config["geometry_sync"]
    geometry_config = GeometrySyncConfig(
        rotation_corrections=tuple(geometry_raw["rotation_corrections"]),
        perspective_corrections=tuple(geometry_raw["perspective_corrections"]),
        fusion_top_k=int(geometry_raw["fusion_top_k"]),
        score_temperature=float(geometry_raw["score_temperature"]),
        minimum_score_improvement=float(geometry_raw["minimum_score_improvement"]),
        minimum_border_evidence=float(geometry_raw["minimum_border_evidence"]),
        search_strategy=str(geometry_raw["search_strategy"]),
    )
    first_dataset = str(debug["datasets"][0]["id"])
    first_strength = float(
        calibration["models"]["wam"]["datasets"][first_dataset]["selected"]["strength"]
    )
    model = WamModel(strength=first_strength, device=args.device)
    synchronizer = GeometrySyncDecoder(model, config=geometry_config)
    rows: list[dict[str, Any]] = []
    started = time.perf_counter()

    for dataset in debug["datasets"]:
        dataset_id = str(dataset["id"])
        fixed_strength = float(
            calibration["models"]["wam"]["datasets"][dataset_id]["selected"]["strength"]
        )
        controller = ContentAdaptiveStrengthController(
            model,
            base_strength=fixed_strength,
            config=adaptive_config,
        )
        samples = list(
            iter_manifest_images(
                (PROJECT_ROOT / dataset["manifest"]).resolve(),
                (PROJECT_ROOT / dataset["root"]).resolve(),
                verify_sha256=True,
            )
        )
        if args.limit_per_dataset is not None:
            samples = samples[: args.limit_per_dataset]
        print(f"M4 {dataset_id}: {len(samples)} images", flush=True)

        for index, sample in enumerate(samples, start=1):
            message = _fixed_message(dataset_id, sample.sample_id)
            model.strength = fixed_strength
            fixed_started = time.perf_counter()
            fixed = model.encode(sample.image, message)
            fixed_encode_ms = (time.perf_counter() - fixed_started) * 1000.0
            fixed_psnr = psnr(sample.image, fixed.image)

            adaptive_started = time.perf_counter()
            adaptive = controller.encode(sample.image, message)
            adaptive_encode_ms = (time.perf_counter() - adaptive_started) * 1000.0
            adaptive_psnr = psnr(sample.image, adaptive.image)
            selected_strength = float(adaptive.metadata["selected_strength"])

            for case in focus_cases:
                attacked_images = {
                    "fixed": apply_attack_case(
                        fixed.image,
                        case,
                        _attack_rng(
                            int(config["suite"]["seed"]),
                            dataset_id,
                            sample.sample_id,
                            case.case_id,
                        ),
                    ),
                    "adaptive": apply_attack_case(
                        adaptive.image,
                        case,
                        _attack_rng(
                            int(config["suite"]["seed"]),
                            dataset_id,
                            sample.sample_id,
                            case.case_id,
                        ),
                    ),
                }
                for variant, embedding_mode, use_sync in VARIANTS:
                    attacked = attacked_images[embedding_mode]
                    decode_started = time.perf_counter()
                    decoded = synchronizer.decode(attacked) if use_sync else model.decode(attacked)
                    decode_ms = (time.perf_counter() - decode_started) * 1000.0
                    metadata = decoded.metadata
                    rows.append(
                        {
                            "dataset": dataset_id,
                            "image_id": sample.sample_id,
                            "variant": variant,
                            "embedding_mode": embedding_mode,
                            "geometry_sync": use_sync,
                            "base_strength": fixed_strength,
                            "selected_strength": (
                                fixed_strength if embedding_mode == "fixed" else selected_strength
                            ),
                            "embed_psnr_db": (
                                fixed_psnr if embedding_mode == "fixed" else adaptive_psnr
                            ),
                            "encode_ms": (
                                fixed_encode_ms
                                if embedding_mode == "fixed"
                                else adaptive_encode_ms
                            ),
                            "attack": case.case_id,
                            "bit_accuracy": bit_accuracy(message, decoded.message),
                            "complete_recovery": complete_recovery(message, decoded.message),
                            "detected": decoded.detected,
                            "decode_ms": decode_ms,
                            "selected_transform": metadata.get(
                                "selected_transform",
                                "identity",
                            ),
                            "candidate_count": metadata.get("candidate_count", 1),
                            "configured_candidate_count": metadata.get(
                                "configured_candidate_count",
                                1,
                            ),
                            "search_strategy": metadata.get(
                                "search_strategy",
                                "identity",
                            ),
                            "refinement_family": metadata.get(
                                "refinement_family",
                                "none",
                            ),
                            "geometry_search_skipped": metadata.get(
                                "geometry_search_skipped",
                                True,
                            ),
                            "selected_score": metadata.get("selected_score", ""),
                            "identity_score": metadata.get("identity_score", ""),
                            "geometry_candidate_accepted": metadata.get(
                                "geometry_candidate_accepted",
                                False,
                            ),
                            "border_geometry_evidence": metadata.get(
                                "border_geometry_evidence",
                                "",
                            ),
                            "minimum_bit_margin": metadata.get(
                                "minimum_absolute_bit_margin",
                                "",
                            ),
                            "quality_budget_spent_db": (
                                0.0
                                if embedding_mode == "fixed"
                                else adaptive.metadata["quality_budget_spent_db"]
                            ),
                        }
                    )
            print(
                f"  {index:02d}/{len(samples)} {sample.sample_id}: "
                f"fixed={fixed_psnr:.2f}dB adaptive={adaptive_psnr:.2f}dB "
                f"strength={selected_strength:.3f}",
                flush=True,
            )

    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else (PROJECT_ROOT / config["outputs"]["results_dir"]).resolve()
    )
    overall, by_attack = _summaries(rows)
    _write_csv(output_dir / "all_records.csv", rows)
    _write_csv(output_dir / "summary_overall.csv", overall)
    _write_csv(output_dir / "summary_by_attack.csv", by_attack)
    metadata = {
        "suite_id": config["suite"]["id"],
        "created_at": datetime.now().astimezone().isoformat(),
        "elapsed_seconds": time.perf_counter() - started,
        "platform": platform.platform(),
        "device": model._backend.device_name,
        "official_commit": OFFICIAL_COMMIT,
        "checkpoint_sha256": OFFICIAL_WEIGHT_SHA256,
        "record_count": len(rows),
        "images": len({(row["dataset"], row["image_id"]) for row in rows}),
        "limit_per_dataset": args.limit_per_dataset,
        "config": config,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"M4 ablation complete: {len(rows)} records -> {output_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
