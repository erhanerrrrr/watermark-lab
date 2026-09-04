from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from watermark_lab.datasets.manifest import read_manifest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"expected mapping in {path}")
    return value


def select_tie_safe_threshold(negative_scores: np.ndarray, target_fpr: float) -> float:
    scores = np.asarray(negative_scores, dtype=np.float64)
    if not len(scores) or not np.all(np.isfinite(scores)):
        raise ValueError("negative calibration scores must be finite and non-empty")
    if not 0.0 <= target_fpr < 1.0:
        raise ValueError("target_fpr must be in [0, 1)")
    candidates = np.append(np.unique(scores), np.nextafter(np.max(scores), math.inf))
    eligible = [value for value in candidates if float(np.mean(scores >= value)) <= target_fpr]
    if not eligible:
        return float("inf")
    return float(min(eligible))


def roc_auc(labels: np.ndarray, scores: np.ndarray) -> float:
    labels = np.asarray(labels, dtype=np.uint8)
    scores = np.asarray(scores, dtype=np.float64)
    positive = scores[labels == 1]
    negative = scores[labels == 0]
    if not len(positive) or not len(negative):
        raise ValueError("ROC-AUC requires positive and negative samples")
    comparisons = positive[:, None] - negative[None, :]
    return float(np.mean(comparisons > 0) + 0.5 * np.mean(comparisons == 0))


def wilson_interval(successes: int, total: int) -> tuple[float, float]:
    if total < 1 or not 0 <= successes <= total:
        raise ValueError("invalid binomial counts")
    z = 1.959963984540054
    rate = successes / total
    denominator = 1.0 + z * z / total
    center = (rate + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(rate * (1.0 - rate) / total + z * z / (4 * total * total))
    margin /= denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def _summary_row(
    frame: pd.DataFrame,
    *,
    model: str,
    scope: str,
    value: str,
    threshold: float,
    target_fpr: float,
) -> dict[str, Any]:
    labels = frame["label"].to_numpy(dtype=np.uint8)
    scores = frame["detection_score"].to_numpy(dtype=np.float64)
    predicted = scores >= threshold
    intrinsic = frame["intrinsic_detected"].astype(str).str.lower().eq("true").to_numpy()
    positive = labels == 1
    negative = labels == 0
    true_positive = int(np.sum(predicted & positive))
    false_positive = int(np.sum(predicted & negative))
    positives = int(np.sum(positive))
    negatives = int(np.sum(negative))
    tpr_low, tpr_high = wilson_interval(true_positive, positives)
    fpr_low, fpr_high = wilson_interval(false_positive, negatives)
    score_name = str(frame["score_name"].iloc[0])
    return {
        "model": model,
        "scope": scope,
        "value": value,
        "score_name": score_name,
        "score_resolution": "binary" if score_name == "official_detection_flag" else "continuous",
        "threshold": threshold,
        "target_calibration_fpr": target_fpr,
        "positive_samples": positives,
        "negative_samples": negatives,
        "tpr": true_positive / positives,
        "tpr_ci95_lower": tpr_low,
        "tpr_ci95_upper": tpr_high,
        "fpr": false_positive / negatives,
        "fpr_ci95_lower": fpr_low,
        "fpr_ci95_upper": fpr_high,
        "roc_auc": roc_auc(labels, scores),
        "intrinsic_tpr": float(np.mean(intrinsic[positive])),
        "intrinsic_fpr": float(np.mean(intrinsic[negative])),
        "positive_complete_recovery": float(
            pd.to_numeric(frame.loc[positive, "complete_recovery"]).mean()
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze formal clean detection benchmark")
    parser.add_argument(
        "--config", type=Path, default=PROJECT_ROOT / "configs/formal_detection.yaml"
    )
    parser.add_argument("--results-dir", type=Path)
    args = parser.parse_args()
    config = _load_mapping(args.config.resolve())
    results_dir = (
        args.results_dir.resolve()
        if args.results_dir
        else (PROJECT_ROOT / config["outputs"]["results_dir"]).resolve()
    )
    target_fpr = float(config["suite"]["target_calibration_fpr"])
    frames: list[pd.DataFrame] = []
    expected_records = 0
    missing: list[str] = []
    for model in config["models"]:
        for split in ("calibration", "test"):
            for dataset in config[f"{split}_datasets"]:
                path = results_dir / str(model) / split / f"{dataset['id']}.csv"
                expected = len(read_manifest(PROJECT_ROOT / dataset["manifest"])) * 2
                expected_records += expected
                if not path.is_file():
                    missing.append(str(path))
                    continue
                frame = pd.read_csv(path)
                if len(frame) != expected:
                    raise RuntimeError(
                        f"record count mismatch in {path}: {len(frame)} != {expected}"
                    )
                frames.append(frame)
    if missing:
        raise RuntimeError("missing detection result files:\n" + "\n".join(missing))
    records = pd.concat(frames, ignore_index=True)
    thresholds: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for model, model_frame in records.groupby("model", sort=True):
        calibration_negative = model_frame[
            (model_frame["split"] == "calibration") & (model_frame["label"] == 0)
        ]
        threshold = select_tie_safe_threshold(
            calibration_negative["detection_score"].to_numpy(), target_fpr
        )
        calibration_fpr = float(
            np.mean(calibration_negative["detection_score"].to_numpy() >= threshold)
        )
        thresholds[str(model)] = {
            "score_name": str(calibration_negative["score_name"].iloc[0]),
            "threshold": threshold,
            "target_fpr": target_fpr,
            "calibration_negative_samples": len(calibration_negative),
            "empirical_calibration_fpr": calibration_fpr,
        }
        test = model_frame[model_frame["split"] == "test"]
        rows.append(
            _summary_row(
                test,
                model=str(model),
                scope="overall",
                value="all",
                threshold=threshold,
                target_fpr=target_fpr,
            )
        )
        for dataset, group in test.groupby("dataset", sort=True):
            rows.append(
                _summary_row(
                    group,
                    model=str(model),
                    scope="dataset",
                    value=str(dataset),
                    threshold=threshold,
                    target_fpr=target_fpr,
                )
            )
    pd.DataFrame(rows).to_csv(
        results_dir / "detection_summary.csv", index=False, encoding="utf-8-sig"
    )
    (results_dir / "thresholds.json").write_text(
        json.dumps(thresholds, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    status = {
        "suite_id": config["suite"]["id"],
        "complete": len(records) == expected_records,
        "records": len(records),
        "expected_records": expected_records,
        "models_present": sorted(records["model"].unique().tolist()),
        "calibration_negative_samples_per_model": sum(
            len(read_manifest(PROJECT_ROOT / item["manifest"]))
            for item in config["calibration_datasets"]
        ),
        "test_positive_and_negative_samples_per_model": 2
        * sum(
            len(read_manifest(PROJECT_ROOT / item["manifest"]))
            for item in config["test_datasets"]
        ),
    }
    (results_dir / "analysis_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
