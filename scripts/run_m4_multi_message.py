from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image

from watermark_lab.attacks.protocol import apply_attack_case, load_attack_protocol
from watermark_lab.datasets.manifest import iter_manifest_images
from watermark_lab.innovations.multi_message import (
    AdaptiveSoftMessageClusterer,
    MultiMessageConfig,
    OfficialHardDbscanDecoder,
    embed_multiple_regions,
    rectangular_region_masks,
    small_patch_region_masks,
)
from watermark_lab.metrics.image_quality import psnr
from watermark_lab.metrics.multi_message import evaluate_multi_message_result
from watermark_lab.models.wam_adapter import OFFICIAL_COMMIT, OFFICIAL_WEIGHT_SHA256, WamModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"expected mapping in {path}")
    return value


def _fixed_messages(
    seed: int,
    dataset_id: str,
    sample_id: str,
    count: int,
    bits: int,
    minimum_hamming: int,
) -> np.ndarray:
    messages: list[np.ndarray] = []
    attempt = 0
    while len(messages) < count:
        digest = hashlib.sha256(
            f"{seed}:{dataset_id}:{sample_id}:{count}:{attempt}".encode()
        ).digest()
        generator = np.random.default_rng(int.from_bytes(digest[:8], "big"))
        candidate = generator.integers(0, 2, size=bits, dtype=np.uint8)
        if all(np.count_nonzero(candidate != existing) >= minimum_hamming for existing in messages):
            messages.append(candidate)
        attempt += 1
        if attempt > 10000:
            raise RuntimeError("failed to generate separated multi-message payloads")
    return np.stack(messages)


def _attack_rng(seed: int, *parts: str) -> np.random.Generator:
    digest = hashlib.sha256(f"{seed}:{':'.join(parts)}".encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "big"))


def _resize_masks(masks: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    height, width = shape
    resized = []
    for mask in masks:
        image = Image.fromarray(mask.astype(np.uint8) * 255)
        output = image.resize((width, height), resample=Image.Resampling.NEAREST)
        resized.append(np.asarray(output, dtype=np.uint8) > 0)
    return np.stack(resized)


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _read_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _partial_matches(
    path: Path,
    *,
    dataset_id: str,
    image_id: str,
    scenario_ids: list[str],
    attack_ids: list[str],
    decoder_ids: list[str],
) -> bool:
    if not path.is_file():
        return False
    rows = _read_rows(path)
    expected = {
        (dataset_id, image_id, scenario, attack, decoder)
        for scenario in scenario_ids
        for attack in attack_ids
        for decoder in decoder_ids
    }
    observed = {
        (
            str(row["dataset"]),
            str(row["image_id"]),
            str(row["scenario"]),
            str(row["attack"]),
            str(row["decoder"]),
        )
        for row in rows
    }
    return len(rows) == len(expected) and observed == expected


def _summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[
            (
                str(row["decoder"]),
                str(row["scenario"]),
                int(row["message_count"]),
                str(row["attack"]),
            )
        ].append(row)
    output: list[dict[str, Any]] = []
    for (decoder, scenario, message_count, attack), group in sorted(grouped.items()):
        output.append(
            {
                "decoder": decoder,
                "scenario": scenario,
                "message_count": message_count,
                "attack": attack,
                "records": len(group),
                "count_accuracy": float(
                    np.mean(
                        [
                            float(str(row["count_correct"]).lower() in {"true", "1"})
                            for row in group
                        ]
                    )
                ),
                "message_precision": float(
                    np.mean([float(row["message_precision"]) for row in group])
                ),
                "message_recall": float(
                    np.mean([float(row["message_recall"]) for row in group])
                ),
                "mean_matched_bit_accuracy": float(
                    np.mean([float(row["mean_matched_bit_accuracy"]) for row in group])
                ),
                "all_messages_recovered_rate": float(
                    np.mean(
                        [
                            float(
                                str(row["all_messages_recovered"]).lower()
                                in {"true", "1"}
                            )
                            for row in group
                        ]
                    )
                ),
                "mean_matched_iou": float(
                    np.mean([float(row["mean_matched_iou"]) for row in group])
                ),
                "mean_cluster_ms": float(
                    np.mean([float(row["cluster_ms"]) for row in group])
                ),
            }
        )
    return output


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the M4.2 multi-message ablation")
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs/m4_multi_message.yaml",
    )
    parser.add_argument("--device", default="auto")
    parser.add_argument("--limit-per-dataset", type=int)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--datasets", nargs="+")
    parser.add_argument("--scenarios", nargs="+")
    parser.add_argument("--attacks", nargs="+")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    if args.limit_per_dataset is not None and args.limit_per_dataset < 1:
        raise ValueError("limit-per-dataset must be positive")

    started = time.perf_counter()
    config = _load_mapping(args.config.resolve())
    debug_config = _load_mapping((PROJECT_ROOT / config["inputs"]["debug_suite"]).resolve())
    calibration = json.loads(
        (PROJECT_ROOT / config["inputs"]["calibration"]).read_text(encoding="utf-8")
    )
    protocol = load_attack_protocol(
        (PROJECT_ROOT / config["inputs"]["attack_protocol"]).resolve()
    )
    attack_ids = list(args.attacks or config["attacks"])
    cases_by_id = {case.case_id: case for case in protocol.cases}
    missing_attacks = sorted(set(attack_ids) - set(cases_by_id))
    if missing_attacks:
        raise ValueError(f"unknown attacks: {', '.join(missing_attacks)}")
    cases = [cases_by_id[case_id] for case_id in attack_ids]

    first_dataset_id = str(debug_config["datasets"][0]["id"])
    first_strength = float(
        calibration["models"]["wam"]["datasets"][first_dataset_id]["selected"]["strength"]
    )
    model = WamModel(strength=first_strength, device=args.device)
    adaptive_config = MultiMessageConfig(**config["adaptive_soft_clustering"])
    adaptive = AdaptiveSoftMessageClusterer(model, config=adaptive_config)
    official = OfficialHardDbscanDecoder(model, **config["official_hard_dbscan"])
    decoders = (
        ("official_hard_dbscan", official),
        ("adaptive_soft", adaptive),
    )

    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else (PROJECT_ROOT / config["outputs"]["results_dir"]).resolve()
    )

    suite = config["suite"]
    seed = int(suite["seed"])
    scenarios = list(config["scenarios"])
    if args.scenarios:
        scenarios = [item for item in scenarios if item["id"] in set(args.scenarios)]
        missing_scenarios = sorted(
            set(args.scenarios) - {str(item["id"]) for item in scenarios}
        )
        if missing_scenarios:
            raise ValueError(f"unknown scenarios: {', '.join(missing_scenarios)}")
    minimum_hamming = int(suite["minimum_generated_message_hamming"])
    scenario_ids = [str(item["id"]) for item in scenarios]
    decoder_ids = [name for name, _ in decoders]
    rows: list[dict[str, Any]] = []
    for dataset in debug_config["datasets"]:
        dataset_id = str(dataset["id"])
        if args.datasets and dataset_id not in set(args.datasets):
            continue
        model.strength = float(
            calibration["models"]["wam"]["datasets"][dataset_id]["selected"]["strength"]
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
        for sample_index, sample in enumerate(samples, start=1):
            token = hashlib.sha256(sample.sample_id.encode()).hexdigest()[:12]
            partial_path = (
                output_dir
                / ".partials"
                / dataset_id
                / f"{sample_index:06d}_{token}.csv"
            )
            if not args.no_resume and _partial_matches(
                partial_path,
                dataset_id=dataset_id,
                image_id=sample.sample_id,
                scenario_ids=scenario_ids,
                attack_ids=attack_ids,
                decoder_ids=decoder_ids,
            ):
                rows.extend(_read_rows(partial_path))
                print(
                    f"resume {dataset_id} {sample_index:02d}/{len(samples)} "
                    f"{sample.sample_id}",
                    flush=True,
                )
                continue
            sample_rows: list[dict[str, Any]] = []
            for scenario in scenarios:
                scenario_id = str(scenario["id"])
                message_count = int(scenario["message_count"])
                messages = _fixed_messages(
                    seed,
                    dataset_id,
                    sample.sample_id,
                    message_count,
                    model.message_bits,
                    minimum_hamming,
                )
                if scenario["layout"] == "balanced":
                    masks = rectangular_region_masks(
                        *sample.image.shape[:2],
                        message_count,
                        **config["embedding"],
                    )
                elif scenario["layout"] == "small_patch":
                    if message_count != 2:
                        raise ValueError("small_patch layout requires two messages")
                    masks = small_patch_region_masks(
                        *sample.image.shape[:2],
                        patch_fraction=float(scenario.get("patch_fraction", 0.04)),
                    )
                else:
                    raise ValueError(f"unknown layout: {scenario['layout']}")
                embed_started = time.perf_counter()
                embedded = embed_multiple_regions(model, sample.image, messages, masks)
                embed_ms = (time.perf_counter() - embed_started) * 1000.0
                embed_psnr = psnr(sample.image, embedded.image)
                for case in cases:
                    attacked = apply_attack_case(
                        embedded.image,
                        case,
                        _attack_rng(
                            seed,
                            dataset_id,
                            sample.sample_id,
                            scenario_id,
                            case.case_id,
                        ),
                    )
                    predict_started = time.perf_counter()
                    prediction = model.predict_spatial(attacked)
                    predict_ms = (time.perf_counter() - predict_started) * 1000.0
                    expected_masks = _resize_masks(
                        masks,
                        prediction.detection_probabilities.shape,
                    )
                    for decoder_name, decoder in decoders:
                        cluster_started = time.perf_counter()
                        decoded = decoder.decode_prediction(prediction)
                        cluster_ms = (time.perf_counter() - cluster_started) * 1000.0
                        metrics = evaluate_multi_message_result(
                            messages,
                            decoded.messages,
                            expected_masks=expected_masks,
                            predicted_localizations=decoded.localizations,
                            localization_threshold=(
                                adaptive_config.localization_threshold
                                if decoder_name == "adaptive_soft"
                                else 0.5
                            ),
                        )
                        sample_rows.append(
                            {
                                "dataset": dataset_id,
                                "image_id": sample.sample_id,
                                "message_count": message_count,
                                "scenario": scenario_id,
                                "attack": case.case_id,
                                "decoder": decoder_name,
                                "predicted_count": metrics.predicted_count,
                                "count_correct": metrics.count_correct,
                                "matched_count": metrics.matched_count,
                                "exact_match_count": metrics.exact_match_count,
                                "message_precision": metrics.message_precision,
                                "message_recall": metrics.message_recall,
                                "mean_matched_bit_accuracy": (
                                    metrics.mean_matched_bit_accuracy
                                ),
                                "all_messages_recovered": metrics.all_messages_recovered,
                                "mean_matched_iou": metrics.mean_matched_iou,
                                "embed_psnr_db": embed_psnr,
                                "embed_ms": embed_ms,
                                "predict_ms": predict_ms,
                                "cluster_ms": cluster_ms,
                                "detected_pixels": decoded.metadata.get(
                                    "detected_pixels", 0
                                ),
                                "minimum_support": decoded.metadata.get(
                                    "minimum_support",
                                    decoded.metadata.get("minimum_samples", ""),
                                ),
                                "seed_count": decoded.metadata.get("seed_count", ""),
                                "seed_supports": json.dumps(
                                    decoded.metadata.get("seed_supports", [])
                                ),
                                "expected_messages": json.dumps(
                                    ["".join(map(str, message)) for message in messages]
                                ),
                                "predicted_messages": json.dumps(
                                    ["".join(map(str, message)) for message in decoded.messages]
                                ),
                                "assignments": json.dumps(metrics.assignments),
                            }
                        )
            _write_rows(partial_path, sample_rows)
            rows.extend(sample_rows)
            print(
                f"{dataset_id} {sample_index:02d}/{len(samples)} "
                f"{sample.sample_id} checkpointed",
                flush=True,
            )

    _write_rows(output_dir / "all_records.csv", rows)
    _write_rows(output_dir / "summary.csv", _summaries(rows))
    metadata = {
        "suite_id": suite["id"],
        "created_at": datetime.now().astimezone().isoformat(),
        "elapsed_seconds": time.perf_counter() - started,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scikit_learn": _package_version("scikit-learn"),
        "torch": _package_version("torch"),
        "device": model._backend.device_name,
        "official_commit": OFFICIAL_COMMIT,
        "checkpoint_sha256": OFFICIAL_WEIGHT_SHA256,
        "record_count": len(rows),
        "image_count": len(
            {(row["dataset"], row["image_id"]) for row in rows}
        ),
        "limit_per_dataset": args.limit_per_dataset,
        "expected_record_count": (
            len({(row["dataset"], row["image_id"]) for row in rows})
            * len(scenarios)
            * len(cases)
            * len(decoders)
        ),
        "config": config,
        "adaptive_config": asdict(adaptive_config),
    }
    (output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if len(rows) != metadata["expected_record_count"]:
        raise RuntimeError("M4.2 record count mismatch")
    print(f"M4.2 complete: {len(rows)} records -> {output_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
