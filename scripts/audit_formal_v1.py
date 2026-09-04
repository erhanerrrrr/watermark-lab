from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from watermark_lab.attacks.protocol import load_attack_protocol
from watermark_lab.datasets.manifest import read_manifest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUMMARY_FIELDS = {
    "detected": "mean_detected",
    "bit_accuracy": "mean_bit_accuracy",
    "complete_recovery": "mean_complete_recovery",
    "embed_psnr_db": "mean_embed_psnr_db",
    "encode_ms": "mean_encode_ms",
    "decode_ms": "mean_decode_ms",
}


def _numeric(value: str) -> float:
    normalized = value.strip().lower()
    if normalized == "true":
        return 1.0
    if normalized == "false":
        return 0.0
    return float(value)


def _load_yaml(path: Path) -> dict[str, Any]:
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


def _check_manifests(config: dict[str, Any]) -> dict[str, Any]:
    showcase = _load_yaml(PROJECT_ROOT / "configs/showcase.yaml")
    split_hashes: dict[str, set[str]] = {"debug": set(), "calibration": set(), "test": set()}
    split_counts = {key: 0 for key in split_hashes}
    for dataset in showcase["datasets"]:
        per_dataset: dict[str, set[str]] = {}
        for split in split_hashes:
            entries = read_manifest(PROJECT_ROOT / dataset[f"{split}_manifest"])
            hashes = {entry.sha256 for entry in entries}
            if len(hashes) != len(entries):
                raise RuntimeError(f"duplicate file hash within {dataset['id']} {split}")
            per_dataset[split] = hashes
            split_hashes[split].update(hashes)
            split_counts[split] += len(entries)
        for left, right in (("debug", "calibration"), ("debug", "test"), ("calibration", "test")):
            overlap = per_dataset[left] & per_dataset[right]
            if overlap:
                raise RuntimeError(f"manifest leakage in {dataset['id']}: {left}/{right}")
    expected_test = sum(
        len(read_manifest(PROJECT_ROOT / item["manifest"])) for item in config["datasets"]
    )
    if split_counts["test"] != expected_test:
        raise RuntimeError("showcase and formal benchmark test manifests disagree")
    return {"counts": split_counts, "pairwise_disjoint_per_dataset": True}


def _check_environment(provenance: dict[str, Any]) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    for name, expected in provenance["environments"].items():
        path = PROJECT_ROOT / expected["file"]
        actual = json.loads(path.read_text(encoding="utf-8"))
        if actual["label"] != expected["label"]:
            raise RuntimeError(f"{name} environment label mismatch")
        if actual["python"]["version"] != expected["python"]:
            raise RuntimeError(f"{name} Python version mismatch")
        for package, version in expected["packages"].items():
            if actual["packages"].get(package) != version:
                raise RuntimeError(f"{name} package mismatch: {package}")
        reports[name] = {
            "file": expected["file"],
            "sha256": _sha256(path),
            "python": expected["python"],
            "packages": expected["packages"],
        }
    return reports


def _check_results(
    config: dict[str, Any], results_dir: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    protocol = load_attack_protocol(PROJECT_ROOT / config["attacks"]["config"])
    attack_ids = [case.case_id for case in protocol.cases]
    all_values: dict[str, dict[str, list[float]]] = {
        str(model): {metric: [] for metric in SUMMARY_FIELDS} for model in config["models"]
    }
    files: dict[str, Any] = {}
    total = 0
    for model in config["models"]:
        model_name = str(model)
        for dataset in config["datasets"]:
            dataset_id = str(dataset["id"])
            manifest = read_manifest(PROJECT_ROOT / dataset["manifest"])
            image_ids = [entry.sample_id for entry in manifest]
            expected_keys = {
                (image_id, attack_id)
                for image_id in image_ids
                for attack_id in attack_ids
            }
            path = results_dir / model_name / f"{dataset_id}.csv"
            if not path.is_file():
                raise RuntimeError(f"missing formal result: {path}")
            with path.open("r", newline="", encoding="utf-8-sig") as stream:
                rows = list(csv.DictReader(stream))
            observed_keys = {(row["image_id"], row["attack"]) for row in rows}
            if len(rows) != len(expected_keys) or observed_keys != expected_keys:
                raise RuntimeError(f"incomplete or duplicate formal result keys: {path}")
            if any(row["model"] != model_name or int(row["message_bits"]) != 32 for row in rows):
                raise RuntimeError(f"model/message contract mismatch: {path}")
            for metric in SUMMARY_FIELDS:
                all_values[model_name][metric].extend(_numeric(row[metric]) for row in rows)
            relative = path.relative_to(PROJECT_ROOT).as_posix()
            files[relative] = {"records": len(rows), "sha256": _sha256(path)}
            total += len(rows)
    return {"records": total, "expected_records": total}, {"files": files, "values": all_values}


def _check_summary_and_snapshot(
    details: dict[str, Any], results_dir: Path
) -> dict[str, Any]:
    summary_path = results_dir / "summary_overall.csv"
    with summary_path.open("r", newline="", encoding="utf-8-sig") as stream:
        summary = {row["model"]: row for row in csv.DictReader(stream)}
    showcase = _load_yaml(PROJECT_ROOT / "configs/showcase.yaml")
    snapshot = showcase["formal_snapshot"]
    for model, metrics in details["values"].items():
        if model not in summary or model not in snapshot["models"]:
            raise RuntimeError(f"model missing from summary/showcase snapshot: {model}")
        for metric, summary_field in SUMMARY_FIELDS.items():
            calculated = float(np.mean(np.asarray(metrics[metric], dtype=np.float64)))
            reported = float(summary[model][summary_field])
            displayed = float(snapshot["models"][model][metric])
            if not np.isclose(calculated, reported, rtol=0.0, atol=1e-12):
                raise RuntimeError(f"summary mismatch: {model}/{metric}")
            if not np.isclose(calculated, displayed, rtol=0.0, atol=1e-12):
                raise RuntimeError(f"showcase snapshot mismatch: {model}/{metric}")
    return {
        "summary_sha256": _sha256(summary_path),
        "showcase_snapshot_consistent": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit frozen formal-v1 provenance and values")
    parser.add_argument(
        "--config", type=Path, default=PROJECT_ROOT / "configs/formal_benchmark.yaml"
    )
    parser.add_argument(
        "--provenance", type=Path, default=PROJECT_ROOT / "configs/formal_v1_provenance.yaml"
    )
    parser.add_argument("--results-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = _load_yaml(args.config.resolve())
    provenance = _load_yaml(args.provenance.resolve())
    results_dir = (
        args.results_dir.resolve()
        if args.results_dir
        else (PROJECT_ROOT / config["outputs"]["results_dir"]).resolve()
    )
    manifests = _check_manifests(config)
    environments = _check_environment(provenance)
    counts, details = _check_results(config, results_dir)
    if counts["records"] != int(provenance["records"]):
        raise RuntimeError("formal record total disagrees with provenance")
    summary = _check_summary_and_snapshot(details, results_dir)
    report = {
        "suite_id": provenance["suite_id"],
        "passed": True,
        "historical_run": provenance["historical_run"],
        "manifests": manifests,
        "environments": environments,
        "results": {**counts, **summary, "files": details["files"]},
    }
    destination = args.output or results_dir / "audit_report.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {"passed": True, "records": counts["records"], "output": str(destination)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
