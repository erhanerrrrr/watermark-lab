from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from watermark_lab.attacks.protocol import load_attack_protocol
from watermark_lab.datasets.manifest import read_manifest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
METRICS = (
    "detected",
    "bit_accuracy",
    "ber",
    "complete_recovery",
    "embed_psnr_db",
    "post_attack_psnr_db",
    "encode_ms",
    "decode_ms",
)


def _load_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"expected mapping in {path}")
    return value


def _summary(frame: pd.DataFrame, groups: list[str]) -> pd.DataFrame:
    aggregations: dict[str, tuple[str, str]] = {"records": ("image_id", "size")}
    for metric in METRICS:
        aggregations[f"mean_{metric}"] = (metric, "mean")
        aggregations[f"std_{metric}"] = (metric, "std")
    return frame.groupby(groups, dropna=False).agg(**aggregations).reset_index()


def _paired_bootstrap(
    differences: np.ndarray,
    *,
    iterations: int,
    seed: int,
) -> tuple[float, float, float]:
    values = np.asarray(differences, dtype=np.float64)
    if not len(values):
        return float("nan"), float("nan"), float("nan")
    generator = np.random.default_rng(seed)
    estimates = np.empty(iterations, dtype=np.float64)
    for index in range(iterations):
        sample = generator.integers(0, len(values), size=len(values))
        estimates[index] = float(np.mean(values[sample]))
    lower, upper = np.quantile(estimates, (0.025, 0.975))
    return float(np.mean(values)), float(lower), float(upper)


def _paired_comparisons(
    frame: pd.DataFrame,
    *,
    reference: str,
    iterations: int,
    seed: int,
) -> pd.DataFrame:
    key = ["dataset", "image_id", "attack"]
    reference_frame = frame[frame["model"] == reference]
    rows: list[dict[str, Any]] = []
    for model_name in sorted(set(frame["model"]) - {reference}):
        comparison = frame[frame["model"] == model_name]
        paired = reference_frame.merge(
            comparison,
            on=key,
            suffixes=("_reference", "_comparison"),
            validate="one_to_one",
        )
        if not np.array_equal(
            paired["category_reference"].to_numpy(),
            paired["category_comparison"].to_numpy(),
        ):
            raise RuntimeError("paired model records disagree on attack category")
        paired["category"] = paired["category_reference"]
        scopes: list[tuple[str, str, pd.DataFrame]] = [("overall", "all", paired)]
        scopes.extend(
            ("dataset", str(value), group)
            for value, group in paired.groupby("dataset", sort=True)
        )
        scopes.extend(
            ("category", str(value), group)
            for value, group in paired.groupby("category", sort=True)
        )
        scopes.extend(
            ("attack", str(value), group)
            for value, group in paired.groupby("attack", sort=True)
        )
        for scope, value, scoped in scopes:
            for metric in METRICS:
                paired_differences = (
                    scoped[f"{metric}_reference"].astype(float)
                    - scoped[f"{metric}_comparison"].astype(float)
                )
                # The 44 attacks on one image are correlated. Bootstrap image units,
                # rather than pretending every attack row is an independent sample.
                unit_differences = (
                    scoped.assign(_difference=paired_differences)
                    .groupby(["dataset", "image_id"], dropna=False)["_difference"]
                    .mean()
                    .to_numpy()
                )
                mean, lower, upper = _paired_bootstrap(
                    unit_differences,
                    iterations=iterations,
                    seed=seed,
                )
                rows.append(
                    {
                        "reference": reference,
                        "comparison": model_name,
                        "scope": scope,
                        "value": value,
                        "metric": metric,
                        "paired_records": len(paired_differences),
                        "bootstrap_image_units": len(unit_differences),
                        "mean_difference_reference_minus_comparison": mean,
                        "ci95_lower": lower,
                        "ci95_upper": upper,
                    }
                )
    return pd.DataFrame(rows)


def _bootstrap_model_summaries(
    frame: pd.DataFrame,
    *,
    iterations: int,
    seed: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model_name, model_frame in frame.groupby("model", sort=True):
        scopes: list[tuple[str, str, pd.DataFrame]] = [
            ("overall", "all", model_frame)
        ]
        scopes.extend(
            ("dataset", str(value), group)
            for value, group in model_frame.groupby("dataset", sort=True)
        )
        scopes.extend(
            ("category", str(value), group)
            for value, group in model_frame.groupby("category", sort=True)
        )
        scopes.extend(
            ("attack", str(value), group)
            for value, group in model_frame.groupby("attack", sort=True)
        )
        for scope, value, scoped in scopes:
            for metric in METRICS:
                # Attack rows from the same image are correlated. First average
                # within each image, then bootstrap independent image units.
                unit_values = (
                    scoped.groupby(["dataset", "image_id"], dropna=False)[metric]
                    .mean()
                    .to_numpy(dtype=np.float64)
                )
                mean, lower, upper = _paired_bootstrap(
                    unit_values,
                    iterations=iterations,
                    seed=seed,
                )
                rows.append(
                    {
                        "model": model_name,
                        "scope": scope,
                        "value": value,
                        "metric": metric,
                        "records": len(scoped),
                        "bootstrap_image_units": len(unit_values),
                        "mean": mean,
                        "ci95_lower": lower,
                        "ci95_upper": upper,
                    }
                )
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze formal-v1 benchmark results")
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs/formal_benchmark.yaml",
    )
    parser.add_argument("--results-dir", type=Path)
    parser.add_argument("--bootstrap-iterations", type=int, default=1000)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    if args.bootstrap_iterations < 1:
        raise ValueError("bootstrap iterations must be positive")

    config = _load_mapping(args.config.resolve())
    results_dir = (
        args.results_dir.resolve()
        if args.results_dir
        else (PROJECT_ROOT / config["outputs"]["results_dir"]).resolve()
    )
    protocol = load_attack_protocol(
        (PROJECT_ROOT / config["attacks"]["config"]).resolve()
    )
    categories = {case.case_id: case.category for case in protocol.cases}
    frames: list[pd.DataFrame] = []
    expected_records = 0
    missing: list[str] = []
    for model_name in config["models"]:
        for dataset in config["datasets"]:
            dataset_id = str(dataset["id"])
            path = results_dir / str(model_name) / f"{dataset_id}.csv"
            manifest_records = len(
                read_manifest((PROJECT_ROOT / dataset["manifest"]).resolve())
            )
            configured_limit = dataset.get("limit")
            if configured_limit is not None:
                manifest_records = min(manifest_records, int(configured_limit))
            dataset_records = manifest_records * len(protocol.cases)
            expected_records += dataset_records
            if not path.is_file():
                missing.append(str(path))
                continue
            frame = pd.read_csv(path)
            if len(frame) != dataset_records and not args.allow_incomplete:
                raise RuntimeError(
                    f"record count mismatch in {path}: {len(frame)} != {dataset_records}"
                )
            frame["dataset"] = dataset_id
            frames.append(frame)
    if missing and not args.allow_incomplete:
        raise RuntimeError("missing formal result files:\n" + "\n".join(missing))
    if not frames:
        raise RuntimeError("no formal result files found")

    records = pd.concat(frames, ignore_index=True)
    records["category"] = records["attack"].map(categories)
    if records["category"].isna().any():
        raise RuntimeError("formal records contain attacks outside the fixed protocol")
    summaries = {
        "summary_overall.csv": _summary(records, ["model"]),
        "summary_by_dataset.csv": _summary(records, ["model", "dataset"]),
        "summary_by_category.csv": _summary(records, ["model", "category"]),
        "summary_by_attack.csv": _summary(records, ["model", "attack"]),
    }
    for filename, summary in summaries.items():
        summary.to_csv(results_dir / filename, index=False, encoding="utf-8-sig")
    bootstrap_summaries = _bootstrap_model_summaries(
        records,
        iterations=args.bootstrap_iterations,
        seed=int(config["suite"]["seed"]),
    )
    bootstrap_summaries.to_csv(
        results_dir / "bootstrap_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    comparisons = _paired_comparisons(
        records,
        reference="am_wam",
        iterations=args.bootstrap_iterations,
        seed=int(config["suite"]["seed"]),
    )
    comparisons.to_csv(
        results_dir / "paired_comparisons.csv",
        index=False,
        encoding="utf-8-sig",
    )
    status = {
        "suite_id": config["suite"]["id"],
        "complete": len(records) == expected_records and not missing,
        "records": len(records),
        "expected_records": expected_records,
        "models_present": sorted(records["model"].unique().tolist()),
        "missing_files": missing,
        "bootstrap_iterations": args.bootstrap_iterations,
    }
    (results_dir / "analysis_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
