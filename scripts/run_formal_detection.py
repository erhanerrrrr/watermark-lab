from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from watermark_lab.core.registry import create_model
from watermark_lab.datasets.manifest import iter_manifest_images, read_manifest
from watermark_lab.innovations.content_adaptive import AdaptiveStrengthConfig
from watermark_lab.innovations.geometry_sync import GeometrySyncConfig
from watermark_lab.metrics.message import bit_accuracy, complete_recovery

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIELDS = (
    "split",
    "dataset",
    "image_id",
    "model",
    "label",
    "score_name",
    "detection_score",
    "intrinsic_detected",
    "decode_confidence",
    "message_bits",
    "bit_accuracy",
    "complete_recovery",
    "encode_ms",
    "decode_ms",
)


def _create_model(
    model_name: str,
    *,
    strength: float,
    device: str,
    m4_config: dict[str, Any],
) -> Any:
    if model_name == "wam":
        return create_model(model_name, strength=strength, device=device)
    if model_name == "am_wam":
        return create_model(
            model_name,
            strength=strength,
            device=device,
            adaptive_config=AdaptiveStrengthConfig(**m4_config["adaptive_strength"]),
            geometry_config=GeometrySyncConfig(**m4_config["geometry_sync"]),
        )
    return create_model(model_name, strength=strength)


def _load_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"expected mapping in {path}")
    return value


def _score(decoded: Any) -> tuple[str, float]:
    metadata = decoded.metadata
    if "sync_score" in metadata:
        return "sync_score", float(metadata["sync_score"])
    if "detected_fraction" in metadata:
        return "detected_fraction", float(metadata["detected_fraction"])
    # TrustMark 0.9.0 exposes only a Boolean detection flag. Its ROC-AUC is
    # therefore a coarse two-level estimate and is labelled as such downstream.
    return "official_detection_flag", float(bool(decoded.detected))


def _sample_seed(seed: int, split: str, dataset: str, image_id: str) -> int:
    digest = hashlib.sha256(f"{seed}:{split}:{dataset}:{image_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _evaluate_image(
    model: Any,
    *,
    split: str,
    dataset: str,
    image_id: str,
    image: np.ndarray,
    seed: int,
) -> list[dict[str, Any]]:
    generator = np.random.default_rng(seed)
    message = generator.integers(0, 2, size=model.message_bits, dtype=np.uint8)
    rows: list[dict[str, Any]] = []

    for label, candidate, encode_ms in ((0, image, 0.0),):
        started = time.perf_counter()
        decoded = model.decode(candidate)
        decode_ms = (time.perf_counter() - started) * 1000.0
        score_name, score = _score(decoded)
        rows.append(
            {
                "split": split,
                "dataset": dataset,
                "image_id": image_id,
                "model": model.name,
                "label": label,
                "score_name": score_name,
                "detection_score": score,
                "intrinsic_detected": bool(decoded.detected),
                "decode_confidence": float(decoded.confidence),
                "message_bits": model.message_bits,
                "bit_accuracy": "",
                "complete_recovery": "",
                "encode_ms": encode_ms,
                "decode_ms": decode_ms,
            }
        )

    started = time.perf_counter()
    embedded = model.encode(image, message)
    encode_ms = (time.perf_counter() - started) * 1000.0
    started = time.perf_counter()
    decoded = model.decode(embedded.image)
    decode_ms = (time.perf_counter() - started) * 1000.0
    score_name, score = _score(decoded)
    rows.append(
        {
            "split": split,
            "dataset": dataset,
            "image_id": image_id,
            "model": model.name,
            "label": 1,
            "score_name": score_name,
            "detection_score": score,
            "intrinsic_detected": bool(decoded.detected),
            "decode_confidence": float(decoded.confidence),
            "message_bits": model.message_bits,
            "bit_accuracy": bit_accuracy(message, decoded.message),
            "complete_recovery": complete_recovery(message, decoded.message),
            "encode_ms": encode_ms,
            "decode_ms": decode_ms,
        }
    )
    return rows


def _partial_matches(path: Path, *, model: str, split: str, image_id: str) -> bool:
    if not path.is_file():
        return False
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    return (
        len(rows) == 2
        and {int(row["label"]) for row in rows} == {0, 1}
        and all(row["model"] == model for row in rows)
        and all(row["split"] == split for row in rows)
        and all(row["image_id"] == image_id for row in rows)
    )


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _combine(paths: list[Path], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        for path in paths:
            with path.open("r", newline="", encoding="utf-8-sig") as source:
                writer.writerows(csv.DictReader(source))
    temporary.replace(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run formal clean positive/negative detection")
    parser.add_argument(
        "--config", type=Path, default=PROJECT_ROOT / "configs/formal_detection.yaml"
    )
    parser.add_argument("--models", nargs="+")
    parser.add_argument("--splits", nargs="+", choices=("calibration", "test"))
    parser.add_argument("--datasets", nargs="+")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--limit-per-dataset", type=int)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    if args.limit_per_dataset is not None and args.limit_per_dataset < 1:
        raise ValueError("limit-per-dataset must be positive")

    config = _load_mapping(args.config.resolve())
    configured_models = [str(value) for value in config["models"]]
    selected_models = args.models or configured_models
    unknown = sorted(set(selected_models) - set(configured_models))
    if unknown:
        raise ValueError(f"models are not configured: {', '.join(unknown)}")
    selected_splits = args.splits or ["calibration", "test"]
    calibration = json.loads(
        (PROJECT_ROOT / config["inputs"]["calibration"]).read_text(encoding="utf-8")
    )
    m4_config = _load_mapping((PROJECT_ROOT / config["inputs"]["m4_config"]).resolve())
    output_root = (
        args.output_dir.resolve()
        if args.output_dir
        else (PROJECT_ROOT / config["outputs"]["results_dir"]).resolve()
    )
    output_root.mkdir(parents=True, exist_ok=True)
    run_rows: list[dict[str, Any]] = []

    for model_name in selected_models:
        model = None
        for split in selected_splits:
            datasets = config[f"{split}_datasets"]
            for dataset in datasets:
                dataset_id = str(dataset["id"])
                if args.datasets and dataset_id not in set(args.datasets):
                    continue
                calibration_id = str(dataset.get("calibration_id", dataset_id))
                calibration_model = "wam" if model_name == "am_wam" else model_name
                selected = calibration["models"][calibration_model]["datasets"][
                    calibration_id
                ]["selected"]
                strength = float(selected["strength"])
                if model is None:
                    model = _create_model(
                        model_name,
                        strength=strength,
                        device=args.device,
                        m4_config=m4_config,
                    )
                else:
                    model.strength = strength

                manifest = (PROJECT_ROOT / dataset["manifest"]).resolve()
                root = (PROJECT_ROOT / dataset["root"]).resolve()
                expected = len(read_manifest(manifest))
                if args.limit_per_dataset is not None:
                    expected = min(expected, args.limit_per_dataset)
                samples = list(iter_manifest_images(manifest, root, verify_sha256=True))[:expected]
                partial_root = output_root / ".partials" / model_name / split / dataset_id
                partials: list[Path] = []
                for index, sample in enumerate(samples, start=1):
                    token = hashlib.sha256(sample.sample_id.encode()).hexdigest()[:12]
                    partial = partial_root / f"{index:06d}_{token}.csv"
                    if args.no_resume or not _partial_matches(
                        partial,
                        model=model_name,
                        split=split,
                        image_id=sample.sample_id,
                    ):
                        rows = _evaluate_image(
                            model,
                            split=split,
                            dataset=dataset_id,
                            image_id=sample.sample_id,
                            image=sample.image,
                            seed=_sample_seed(
                                int(config["suite"]["seed"]),
                                split,
                                dataset_id,
                                sample.sample_id,
                            ),
                        )
                        _write_rows(partial, rows)
                    partials.append(partial)
                    if index == 1 or index % 10 == 0 or index == len(samples):
                        print(
                            f"detection {model_name}/{split}/{dataset_id}: "
                            f"{index}/{len(samples)} images",
                            flush=True,
                        )
                destination = output_root / model_name / split / f"{dataset_id}.csv"
                _combine(partials, destination)
                run_rows.append(
                    {
                        "model": model_name,
                        "split": split,
                        "dataset": dataset_id,
                        "images": len(samples),
                        "records": len(samples) * 2,
                        "strength": strength,
                        "path": str(destination.relative_to(PROJECT_ROOT)),
                    }
                )

    metadata = {
        "suite_id": config["suite"]["id"],
        "created_at": datetime.now().astimezone().isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "device_request": args.device,
        "limit_per_dataset": args.limit_per_dataset,
        "models": selected_models,
        "splits": selected_splits,
        "runs": run_rows,
    }
    token = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    metadata_dir = output_root / "run_metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = metadata_dir / f"{token}.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"detection benchmark step complete: {metadata_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
