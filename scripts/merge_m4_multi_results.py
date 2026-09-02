from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"expected mapping in {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _boolean(value: Any) -> float:
    return float(str(value).strip().lower() in {"1", "true", "yes"})


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
                    np.mean([_boolean(row["count_correct"]) for row in group])
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
                    np.mean([_boolean(row["all_messages_recovered"]) for row in group])
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and merge M4.2 dataset shards")
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs/m4_multi_message.yaml",
    )
    parser.add_argument(
        "--parts-root",
        type=Path,
        default=PROJECT_ROOT / "results/m4_multi_message_parts",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "results/m4_multi_message",
    )
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()

    config = _load_mapping(args.config.resolve())
    debug_config = _load_mapping((PROJECT_ROOT / config["inputs"]["debug_suite"]).resolve())
    expected_datasets = {str(item["id"]) for item in debug_config["datasets"]}
    part_paths = sorted(args.parts_root.resolve().glob("*/all_records.csv"))
    if not part_paths:
        raise FileNotFoundError(f"no M4.2 shards under {args.parts_root.resolve()}")

    all_rows: list[dict[str, Any]] = []
    part_records: list[dict[str, Any]] = []
    fieldnames: list[str] | None = None
    for part_path in part_paths:
        with part_path.open("r", newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            current_fields = list(reader.fieldnames or [])
            if fieldnames is None:
                fieldnames = current_fields
            elif current_fields != fieldnames:
                raise ValueError(f"M4.2 shard schema mismatch: {part_path}")
            rows = list(reader)
        metadata_path = part_path.with_name("run_metadata.json")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if len(rows) != int(metadata["expected_record_count"]):
            raise ValueError(f"incomplete M4.2 shard: {part_path}")
        datasets = sorted({str(row["dataset"]) for row in rows})
        if len(datasets) != 1:
            raise ValueError(f"each M4.2 shard must contain one dataset: {part_path}")
        all_rows.extend(rows)
        part_records.append(
            {
                "dataset": datasets[0],
                "path": str(part_path.relative_to(PROJECT_ROOT)),
                "records": len(rows),
                "sha256": _sha256(part_path),
                "device": metadata.get("device"),
                "elapsed_seconds": metadata.get("elapsed_seconds"),
            }
        )

    observed_datasets = {str(row["dataset"]) for row in all_rows}
    missing = sorted(expected_datasets - observed_datasets)
    unexpected = sorted(observed_datasets - expected_datasets)
    if unexpected:
        raise ValueError(f"unexpected M4.2 datasets: {', '.join(unexpected)}")
    if missing and not args.allow_incomplete:
        raise ValueError(f"missing M4.2 datasets: {', '.join(missing)}")
    keys = [
        (
            row["dataset"],
            row["image_id"],
            row["scenario"],
            row["attack"],
            row["decoder"],
        )
        for row in all_rows
    ]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate M4.2 records found across shards")

    output_dir = args.output_dir.resolve()
    _write_rows(output_dir / "all_records.csv", all_rows)
    _write_rows(output_dir / "summary.csv", _summaries(all_rows))
    metadata = {
        "suite_id": config["suite"]["id"],
        "created_at": datetime.now().astimezone().isoformat(),
        "record_count": len(all_rows),
        "image_count": len({(row["dataset"], row["image_id"]) for row in all_rows}),
        "expected_datasets": sorted(expected_datasets),
        "observed_datasets": sorted(observed_datasets),
        "complete": not missing,
        "missing_datasets": missing,
        "parts": part_records,
    }
    (output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"M4.2 merge complete: {len(all_rows)} records from {len(part_paths)} shards",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
