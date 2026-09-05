from __future__ import annotations

import csv
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from watermark_lab.api.storage import project_root
from watermark_lab.attacks.protocol import load_attack_protocol

SHOWCASE_CONFIG = project_root() / "configs" / "showcase.yaml"
ATTACK_CONFIG = project_root() / "configs" / "attacks.yaml"


@lru_cache(maxsize=1)
def load_showcase_config() -> dict[str, Any]:
    with SHOWCASE_CONFIG.open("r", encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise RuntimeError("configs/showcase.yaml must contain a mapping")
    return value


def _manifest_rows(relative_path: str) -> list[dict[str, str]]:
    path = project_root() / relative_path
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _local_count(manifest: str, root: str) -> tuple[int, int]:
    rows = _manifest_rows(manifest)
    root_path = project_root() / root
    found = sum((root_path / row["relative_path"]).is_file() for row in rows)
    return found, len(rows)


def dataset_catalog() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for configured in load_showcase_config()["datasets"]:
        item = dict(configured)
        counts: dict[str, dict[str, int]] = {}
        found_total = 0
        expected_total = 0
        for split in ("debug", "calibration", "test"):
            found, expected = _local_count(item[f"{split}_manifest"], item[f"{split}_root"])
            counts[split] = {"found": found, "expected": expected}
            found_total += found
            expected_total += expected
        item["counts"] = counts
        item["found_images"] = found_total
        item["expected_images"] = expected_total
        item["progress"] = round((found_total / expected_total * 100) if expected_total else 0, 1)
        item["ready"] = found_total == expected_total
        result.append(item)
    return result


def attack_catalog() -> dict[str, Any]:
    protocol = load_attack_protocol(ATTACK_CONFIG)
    return {
        "id": protocol.protocol_id,
        "version": protocol.version,
        "seed": protocol.seed,
        "cases": [
            {
                "id": case.case_id,
                "category": case.category,
                "pipeline": [
                    {"name": step.name, "parameters": dict(step.parameters)} for step in case.steps
                ],
            }
            for case in protocol.cases
        ],
    }


def formal_snapshot() -> dict[str, Any]:
    snapshot = dict(load_showcase_config()["formal_snapshot"])
    snapshot["models"] = {
        model_id: dict(metrics) for model_id, metrics in snapshot["models"].items()
    }
    local_summary = project_root() / "results" / "formal_v1" / "summary_overall.csv"
    local_status = project_root() / "results" / "formal_v1" / "analysis_status.json"
    snapshot["data_source"] = "tracked_snapshot"
    if not (local_summary.is_file() and local_status.is_file()):
        return snapshot
    status = json.loads(local_status.read_text(encoding="utf-8"))
    if not status.get("complete") or status.get("records") != status.get("expected_records"):
        return snapshot
    with local_summary.open("r", newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            snapshot["models"][row["model"]] = {
                "records": int(row["records"]),
                "detected": float(row["mean_detected"]),
                "bit_accuracy": float(row["mean_bit_accuracy"]),
                "complete_recovery": float(row["mean_complete_recovery"]),
                "embed_psnr_db": float(row["mean_embed_psnr_db"]),
                "encode_ms": float(row["mean_encode_ms"]),
                "decode_ms": float(row["mean_decode_ms"]),
            }
    snapshot["data_source"] = "local_formal_results"
    return snapshot


def verify_datasets() -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for dataset in load_showcase_config()["datasets"]:
        missing: list[str] = []
        mismatched: list[str] = []
        verified = 0
        expected = 0
        for split in ("debug", "calibration", "test"):
            root = project_root() / dataset[f"{split}_root"]
            for row in _manifest_rows(dataset[f"{split}_manifest"]):
                expected += 1
                path = root / row["relative_path"]
                if not path.is_file():
                    missing.append(f"{split}/{row['relative_path']}")
                    continue
                digest_builder = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest_builder.update(chunk)
                digest = digest_builder.hexdigest()
                if digest != row["sha256"]:
                    mismatched.append(f"{split}/{row['relative_path']}")
                    continue
                verified += 1
        valid = verified == expected
        # A fresh checkout intentionally does not carry the licensed image files.
        # Keep this distinct from corruption so the UI can explain how to prepare data.
        if valid:
            status = "ready"
        elif mismatched:
            status = "mismatch"
        elif verified == 0:
            status = "not_prepared"
        else:
            status = "partial"
        reports.append(
            {
                "id": dataset["id"],
                "expected": expected,
                "verified": verified,
                "missing": missing,
                "mismatched": mismatched,
                "valid": valid,
                "status": status,
            }
        )
    return reports


def manifest_path(dataset_id: str, split: str) -> Path | None:
    if split not in {"debug", "calibration", "test"}:
        return None
    for dataset in load_showcase_config()["datasets"]:
        if dataset["id"] == dataset_id:
            path = (project_root() / dataset[f"{split}_manifest"]).resolve()
            if project_root() not in path.parents or not path.is_file():
                return None
            return path
    return None
