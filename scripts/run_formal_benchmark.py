from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from watermark_lab.attacks.protocol import load_attack_protocol
from watermark_lab.core.registry import create_model
from watermark_lab.datasets.manifest import iter_manifest_images, read_manifest
from watermark_lab.experiments.runner import run_experiment, write_results_csv
from watermark_lab.innovations.content_adaptive import AdaptiveStrengthConfig
from watermark_lab.innovations.geometry_sync import GeometrySyncConfig

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _command(*command: str) -> str | None:
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _load_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"expected mapping in {path}")
    return value


def _record_count(path: Path) -> int:
    if not path.is_file():
        return -1
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        return sum(1 for _ in csv.DictReader(stream))


def _stable_sample_seed(seed: int, dataset_id: str, image_id: str) -> int:
    """Make each image independent so interrupted runs can resume exactly."""
    digest = hashlib.sha256(f"{seed}:{dataset_id}:{image_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _result_matches(
    path: Path,
    *,
    image_ids: list[str],
    attack_ids: list[str],
) -> bool:
    if not path.is_file():
        return False
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    expected = {(image_id, attack_id) for image_id in image_ids for attack_id in attack_ids}
    observed = {(str(row["image_id"]), str(row["attack"])) for row in rows}
    return len(rows) == len(expected) and observed == expected


def _combine_partial_results(part_paths: list[Path], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    fieldnames: list[str] | None = None
    with temporary.open("w", newline="", encoding="utf-8-sig") as output_stream:
        writer: csv.DictWriter[str] | None = None
        for path in part_paths:
            with path.open("r", newline="", encoding="utf-8-sig") as input_stream:
                reader = csv.DictReader(input_stream)
                if fieldnames is None:
                    fieldnames = list(reader.fieldnames or [])
                    if not fieldnames:
                        raise ValueError(f"partial result has no header: {path}")
                    writer = csv.DictWriter(output_stream, fieldnames=fieldnames)
                    writer.writeheader()
                elif list(reader.fieldnames or []) != fieldnames:
                    raise ValueError(f"partial result schema mismatch: {path}")
                assert writer is not None
                writer.writerows(reader)
    temporary.replace(destination)


def _create_formal_model(
    model_name: str,
    *,
    strength: float,
    device: str,
    m4_config: dict[str, Any],
):
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run resumable formal-v1 benchmark")
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs/formal_benchmark.yaml",
    )
    parser.add_argument("--models", nargs="+")
    parser.add_argument("--datasets", nargs="+")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--limit-per-dataset", type=int)
    parser.add_argument("--attacks", nargs="+")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--shard-index", type=int)
    parser.add_argument("--shard-count", type=int)
    args = parser.parse_args()
    if args.limit_per_dataset is not None and args.limit_per_dataset < 1:
        raise ValueError("limit-per-dataset must be positive")
    if (args.shard_index is None) != (args.shard_count is None):
        raise ValueError("shard-index and shard-count must be provided together")
    if args.shard_count is not None:
        if args.shard_count < 1:
            raise ValueError("shard-count must be positive")
        if not 0 <= args.shard_index < args.shard_count:
            raise ValueError("shard-index must be within [0, shard-count)")

    config = _load_mapping(args.config.resolve())
    configured_models = [str(value) for value in config["models"]]
    selected_models = args.models or configured_models
    unknown_models = sorted(set(selected_models) - set(configured_models))
    if unknown_models:
        raise ValueError(f"models are not configured: {', '.join(unknown_models)}")

    calibration = json.loads(
        (PROJECT_ROOT / config["inputs"]["calibration"]).read_text(encoding="utf-8")
    )
    m4_config = _load_mapping((PROJECT_ROOT / config["inputs"]["m4_config"]).resolve())
    protocol = load_attack_protocol(
        (PROJECT_ROOT / config["attacks"]["config"]).resolve()
    )
    cases_by_id = {case.case_id: case for case in protocol.cases}
    if args.attacks:
        missing_attacks = sorted(set(args.attacks) - set(cases_by_id))
        if missing_attacks:
            raise ValueError(f"unknown attacks: {', '.join(missing_attacks)}")
        cases = [cases_by_id[case_id] for case_id in args.attacks]
    else:
        cases = list(protocol.cases)
    output_root = (
        args.output_dir.resolve()
        if args.output_dir
        else (PROJECT_ROOT / config["outputs"]["results_dir"]).resolve()
    )
    output_root.mkdir(parents=True, exist_ok=True)

    run_rows: list[dict[str, Any]] = []
    for model_name in selected_models:
        model = None
        for dataset in config["datasets"]:
            dataset_id = str(dataset["id"])
            if args.datasets and dataset_id not in set(args.datasets):
                continue
            calibration_id = str(dataset["calibration_id"])
            calibration_model = "wam" if model_name == "am_wam" else model_name
            selected = calibration["models"][calibration_model]["datasets"][calibration_id][
                "selected"
            ]
            strength = float(selected["strength"])
            if model is None:
                model = _create_formal_model(
                    model_name,
                    strength=strength,
                    device=args.device,
                    m4_config=m4_config,
                )
            else:
                model.strength = strength

            manifest = (PROJECT_ROOT / dataset["manifest"]).resolve()
            dataset_root = (PROJECT_ROOT / dataset["root"]).resolve()
            manifest_count = len(read_manifest(manifest))
            configured_limit = dataset.get("limit")
            if configured_limit is not None and int(configured_limit) < 1:
                raise ValueError(f"dataset limit must be positive: {dataset_id}")
            limits = [manifest_count]
            if configured_limit is not None:
                limits.append(int(configured_limit))
            if args.limit_per_dataset is not None:
                limits.append(args.limit_per_dataset)
            full_sample_count = min(limits)
            samples = list(
                iter_manifest_images(
                    manifest,
                    dataset_root,
                    verify_sha256=True,
                )
            )[:full_sample_count]
            indexed_samples = list(enumerate(samples, start=1))
            if args.shard_count is not None:
                indexed_samples = [
                    item
                    for item in indexed_samples
                    if (item[0] - 1) % args.shard_count == args.shard_index
                ]
            sample_count = len(indexed_samples)
            image_ids = [sample.sample_id for sample in samples]
            attack_ids = [case.case_id for case in cases]
            expected_records = full_sample_count * len(cases)
            result_path = output_root / model_name / f"{dataset_id}.csv"
            existing_records = _record_count(result_path)
            if not args.no_resume and _result_matches(
                result_path,
                image_ids=image_ids,
                attack_ids=attack_ids,
            ):
                print(
                    f"resume skip {model_name}/{dataset_id}: {existing_records} records",
                    flush=True,
                )
                run_rows.append(
                    {
                        "model": model_name,
                        "dataset": dataset_id,
                        "strength": strength,
                        "records": existing_records,
                        "status": "reused",
                        "path": str(result_path.relative_to(PROJECT_ROOT)),
                    }
                )
                continue
            print(
                f"formal {model_name}/{dataset_id}: "
                f"{sample_count}/{full_sample_count} images x {len(cases)} attacks"
                + (
                    f" (shard {args.shard_index}/{args.shard_count})"
                    if args.shard_count is not None
                    else ""
                ),
                flush=True,
            )
            partial_root = output_root / ".partials" / model_name / dataset_id
            partial_paths: list[Path] = []
            for completed_index, (sample_index, sample) in enumerate(
                indexed_samples,
                start=1,
            ):
                token = hashlib.sha256(sample.sample_id.encode()).hexdigest()[:12]
                partial_path = partial_root / f"{sample_index:06d}_{token}.csv"
                if args.no_resume or not _result_matches(
                    partial_path,
                    image_ids=[sample.sample_id],
                    attack_ids=attack_ids,
                ):
                    records = run_experiment(
                        model,
                        [(sample.sample_id, sample.image)],
                        cases,
                        seed=_stable_sample_seed(
                            protocol.seed,
                            dataset_id,
                            sample.sample_id,
                        ),
                    )
                    write_results_csv(records, partial_path)
                partial_paths.append(partial_path)
                if (
                    completed_index == 1
                    or completed_index % 10 == 0
                    or completed_index == sample_count
                ):
                    print(
                        f"  {model_name}/{dataset_id}: "
                        f"{completed_index}/{sample_count} shard images checkpointed "
                        f"(global index {sample_index})",
                        flush=True,
                    )
            if args.shard_count is not None:
                shard_records = sample_count * len(cases)
                run_rows.append(
                    {
                        "model": model_name,
                        "dataset": dataset_id,
                        "strength": strength,
                        "records": shard_records,
                        "status": "checkpointed_shard",
                        "path": str(partial_root.relative_to(PROJECT_ROOT)),
                        "shard_index": args.shard_index,
                        "shard_count": args.shard_count,
                    }
                )
                print(
                    f"shard checkpoint complete: {model_name}/{dataset_id} "
                    f"{args.shard_index}/{args.shard_count}",
                    flush=True,
                )
                continue
            partial_paths = [
                partial_root
                / f"{sample_index:06d}_"
                f"{hashlib.sha256(sample.sample_id.encode()).hexdigest()[:12]}.csv"
                for sample_index, sample in enumerate(samples, start=1)
            ]
            _combine_partial_results(partial_paths, result_path)
            actual_records = _record_count(result_path)
            if actual_records != expected_records:
                raise RuntimeError(
                    f"record count mismatch for {model_name}/{dataset_id}: "
                    f"{actual_records} != {expected_records}"
                )
            run_rows.append(
                {
                    "model": model_name,
                    "dataset": dataset_id,
                    "strength": strength,
                    "records": actual_records,
                    "status": "completed",
                    "path": str(result_path.relative_to(PROJECT_ROOT)),
                }
            )
            print(f"saved: {result_path}", flush=True)

    metadata = {
        "suite_id": config["suite"]["id"],
        "created_at": datetime.now().astimezone().isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "watermark_lab_distribution": importlib.metadata.version("watermark-lab"),
        "git_head": _command("git", "rev-parse", "HEAD"),
        "git_status": _command("git", "status", "--short"),
        "protocol_id": protocol.protocol_id,
        "protocol_version": protocol.version,
        "protocol_seed": protocol.seed,
        "device_request": args.device,
        "limit_per_dataset": args.limit_per_dataset,
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "models": selected_models,
        "attacks": [case.case_id for case in cases],
        "runs": run_rows,
    }
    serialized = json.dumps(metadata, ensure_ascii=False, indent=2)
    # Keep an immutable record for every resumed/sharded invocation. The legacy
    # top-level file remains a convenient pointer to the latest invocation.
    metadata_dir = output_root / "run_metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    metadata_token = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    model_token = "-".join(selected_models)
    (metadata_dir / f"{metadata_token}-{model_token}.json").write_text(
        serialized,
        encoding="utf-8",
    )
    (output_root / "run_metadata.json").write_text(serialized, encoding="utf-8")
    print(f"formal benchmark step complete: {len(run_rows)} model/dataset runs", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
