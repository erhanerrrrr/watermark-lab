from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from watermark_lab.core.registry import create_model
from watermark_lab.datasets.manifest import iter_manifest_images, read_manifest
from watermark_lab.metrics.image_quality import psnr

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class DatasetSpec:
    dataset_id: str
    manifest: Path
    root: Path


def _load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict):
        raise ValueError("debug suite config must be a mapping")
    return config


def _dataset_specs(config: dict[str, Any]) -> tuple[DatasetSpec, ...]:
    return tuple(
        DatasetSpec(
            dataset_id=str(item["id"]),
            manifest=(PROJECT_ROOT / item["manifest"]).resolve(),
            root=(PROJECT_ROOT / item["root"]).resolve(),
        )
        for item in config["datasets"]
    )


def _message_for(seed: int, dataset_id: str, sample_id: str, bits: int) -> np.ndarray:
    digest = hashlib.sha256(f"{seed}:{dataset_id}:{sample_id}".encode()).digest()
    generator = np.random.default_rng(int.from_bytes(digest[:8], "big"))
    return generator.integers(0, 2, size=bits, dtype=np.uint8)


def _evaluate_strength(
    model: Any,
    strength: float,
    dataset: DatasetSpec,
    seed: int,
) -> dict[str, Any]:
    model.strength = float(strength)
    scores: list[float] = []
    for sample in iter_manifest_images(
        dataset.manifest,
        dataset.root,
        verify_sha256=True,
    ):
        message = _message_for(seed, dataset.dataset_id, sample.sample_id, model.message_bits)
        embedded = model.encode(sample.image, message)
        scores.append(psnr(sample.image, embedded.image))
    result = {
        "strength": float(strength),
        "mean_psnr_db": float(np.mean(scores)),
        "std_psnr_db": float(np.std(scores)),
        "minimum_psnr_db": float(np.min(scores)),
        "maximum_psnr_db": float(np.max(scores)),
    }
    print(
        f"{model.name}/{dataset.dataset_id}: strength={strength:.6f}, "
        f"mean PSNR={result['mean_psnr_db']:.4f} dB",
        flush=True,
    )
    return result


def _calibrate_model(
    model: Any,
    bounds: dict[str, Any],
    dataset: DatasetSpec,
    seed: int,
    target_psnr: float,
    iterations: int,
) -> dict[str, Any]:
    lower = float(bounds["minimum_strength"])
    upper = float(bounds["maximum_strength"])
    evaluations: list[dict[str, Any]] = []
    evaluations.append(_evaluate_strength(model, lower, dataset, seed))
    evaluations.append(_evaluate_strength(model, upper, dataset, seed))
    for _ in range(iterations):
        midpoint = (lower + upper) / 2.0
        evaluation = _evaluate_strength(model, midpoint, dataset, seed)
        evaluations.append(evaluation)
        if evaluation["mean_psnr_db"] > target_psnr:
            lower = midpoint
        else:
            upper = midpoint
    best = min(
        evaluations,
        key=lambda item: abs(float(item["mean_psnr_db"]) - target_psnr),
    )
    return {
        "selected": best,
        "target_error_db": abs(float(best["mean_psnr_db"]) - target_psnr),
        "target_bracketed": (
            float(evaluations[0]["mean_psnr_db"]) >= target_psnr
            >= float(evaluations[1]["mean_psnr_db"])
        ),
        "evaluations": evaluations,
    }


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _environment() -> dict[str, str]:
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "torch": _package_version("torch"),
        "trustmark": _package_version("trustmark"),
        "opencv-python": _package_version("opencv-python"),
    }


def _write_calibration(
    output_path: Path,
    *,
    suite: dict[str, Any],
    target_psnr: float,
    seed: int,
    datasets: tuple[DatasetSpec, ...],
    results: dict[str, Any],
) -> None:
    dataset_counts = {
        item.dataset_id: len(read_manifest(item.manifest))
        for item in datasets
        if item.manifest.is_file()
    }
    payload = {
        "suite_id": suite["id"],
        "created_at": datetime.now().astimezone().isoformat(),
        "target_psnr_db": target_psnr,
        "seed": seed,
        "image_count": sum(dataset_counts.values()),
        "dataset_image_counts": dataset_counts,
        "environment": _environment(),
        "models": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(output_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate debug models to equal mean PSNR")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs/debug_suite.yaml")
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument(
        "--models",
        nargs="+",
        help="optional model names to calibrate; existing results for other models are preserved",
    )
    parser.add_argument(
        "--datasets",
        nargs="+",
        help="optional dataset IDs; each completed dataset is checkpointed",
    )
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()
    if args.iterations < 1:
        raise ValueError("iterations must be positive")

    config_path = args.config.resolve()
    config = _load_config(config_path)
    configured_datasets = _dataset_specs(config)
    datasets = configured_datasets
    if args.datasets:
        known_datasets = {item.dataset_id for item in configured_datasets}
        unknown_datasets = sorted(set(args.datasets) - known_datasets)
        if unknown_datasets:
            raise ValueError(
                f"datasets are missing from calibration config: {', '.join(unknown_datasets)}"
            )
        selected_dataset_ids = set(args.datasets)
        datasets = tuple(
            item for item in configured_datasets if item.dataset_id in selected_dataset_ids
        )
    suite = config["suite"]
    target_psnr = float(suite["target_psnr_db"])
    seed = int(suite["seed"])

    configured_models = config["models"]
    selected_models = args.models or list(configured_models)
    unknown_models = sorted(set(selected_models) - set(configured_models))
    if unknown_models:
        raise ValueError(f"models are missing from debug config: {', '.join(unknown_models)}")

    output_path = (PROJECT_ROOT / config["outputs"]["calibration"]).resolve()
    existing: dict[str, Any] = {}
    if output_path.is_file():
        previous = json.loads(output_path.read_text(encoding="utf-8"))
        existing = dict(previous.get("models", {}))

    results: dict[str, Any] = existing
    for model_name in selected_models:
        bounds = configured_models[model_name]
        model_options: dict[str, Any] = {
            "strength": float(bounds["minimum_strength"]),
        }
        if model_name == "wam":
            model_options["device"] = args.device
        model = create_model(
            model_name,
            **model_options,
        )
        previous_model = results.get(model_name, {})
        model_result = {
            "environment": {
                **_environment(),
                "model_device": str(
                    getattr(getattr(model, "_backend", None), "device_name", args.device)
                ),
            },
            "search_bounds": {
                "minimum_strength": float(bounds["minimum_strength"]),
                "maximum_strength": float(bounds["maximum_strength"]),
            },
            "datasets": dict(previous_model.get("datasets", {})),
        }
        results[model_name] = model_result
        for dataset in datasets:
            model_result["datasets"][dataset.dataset_id] = _calibrate_model(
                model,
                bounds,
                dataset,
                seed,
                target_psnr,
                args.iterations,
            )
            _write_calibration(
                output_path,
                suite=suite,
                target_psnr=target_psnr,
                seed=seed,
                datasets=configured_datasets,
                results=results,
            )
            print(
                f"calibration checkpoint: {model_name}/{dataset.dataset_id}",
                flush=True,
            )

    _write_calibration(
        output_path,
        suite=suite,
        target_psnr=target_psnr,
        seed=seed,
        datasets=configured_datasets,
        results=results,
    )
    print(f"calibration saved: {output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
