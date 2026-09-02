from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUALITY_METRICS = (
    "count_correct",
    "message_precision",
    "message_recall",
    "mean_matched_bit_accuracy",
    "all_messages_recovered",
    "mean_matched_iou",
)


def _load_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"expected mapping in {path}")
    return value


def _bootstrap(
    values: np.ndarray,
    *,
    iterations: int,
    seed: int,
) -> tuple[float, float, float]:
    observed = np.asarray(values, dtype=np.float64)
    if not len(observed):
        return float("nan"), float("nan"), float("nan")
    generator = np.random.default_rng(seed)
    estimates = np.empty(iterations, dtype=np.float64)
    for index in range(iterations):
        sample = generator.integers(0, len(observed), size=len(observed))
        estimates[index] = float(np.mean(observed[sample]))
    lower, upper = np.quantile(estimates, (0.025, 0.975))
    return float(np.mean(observed)), float(lower), float(upper)


def _paired_rows(
    frame: pd.DataFrame,
    *,
    iterations: int,
    seed: int,
) -> pd.DataFrame:
    key = ["dataset", "image_id", "scenario", "attack"]
    official = frame[frame["decoder"] == "official_hard_dbscan"]
    adaptive = frame[frame["decoder"] == "adaptive_soft"]
    paired = adaptive.merge(
        official,
        on=key,
        suffixes=("_adaptive", "_official"),
        validate="one_to_one",
    )
    output: list[dict[str, Any]] = []
    scopes: list[tuple[str, str, pd.DataFrame]] = [("overall", "all", paired)]
    scopes.extend(
        ("scenario", str(scenario), group)
        for scenario, group in paired.groupby("scenario", sort=True)
    )
    for scope, value, group in scopes:
        for metric in (*QUALITY_METRICS, "cluster_ms"):
            differences = (
                group[f"{metric}_adaptive"].astype(float)
                - group[f"{metric}_official"].astype(float)
            )
            unit_differences = (
                group.assign(_difference=differences)
                .groupby(["dataset", "image_id"], dropna=False)["_difference"]
                .mean()
                .to_numpy()
            )
            mean, lower, upper = _bootstrap(
                unit_differences,
                iterations=iterations,
                seed=seed,
            )
            output.append(
                {
                    "scope": scope,
                    "value": value,
                    "metric": metric,
                    "paired_records": len(group),
                    "bootstrap_image_units": len(unit_differences),
                    "mean_difference_adaptive_minus_official": mean,
                    "ci95_lower": lower,
                    "ci95_upper": upper,
                    "higher_is_better": metric != "cluster_ms",
                }
            )
    return pd.DataFrame(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze completed M4.2 results")
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs/m4_multi_message.yaml",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=PROJECT_ROOT / "results/m4_multi_message",
    )
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    args = parser.parse_args()
    if args.bootstrap_iterations < 1:
        raise ValueError("bootstrap iterations must be positive")

    config = _load_mapping(args.config.resolve())
    results_dir = args.results_dir.resolve()
    metadata = json.loads(
        (results_dir / "run_metadata.json").read_text(encoding="utf-8")
    )
    if not metadata.get("complete", False):
        raise RuntimeError("M4.2 shards must be complete before final analysis")
    frame = pd.read_csv(results_dir / "all_records.csv")
    if len(frame) != int(metadata["record_count"]):
        raise RuntimeError("M4.2 merged record count does not match metadata")
    for column in ("count_correct", "all_messages_recovered"):
        frame[column] = frame[column].astype(str).str.lower().map(
            {"true": 1.0, "false": 0.0, "1": 1.0, "0": 0.0}
        )
        if frame[column].isna().any():
            raise ValueError(f"invalid boolean values in {column}")

    aggregations: dict[str, tuple[str, str]] = {"records": ("image_id", "size")}
    for metric in (*QUALITY_METRICS, "cluster_ms"):
        aggregations[f"mean_{metric}"] = (metric, "mean")
        aggregations[f"std_{metric}"] = (metric, "std")
    overall = frame.groupby(["decoder"], dropna=False).agg(**aggregations).reset_index()
    by_scenario = (
        frame.groupby(["decoder", "scenario"], dropna=False)
        .agg(**aggregations)
        .reset_index()
    )
    overall.to_csv(results_dir / "analysis_overall.csv", index=False, encoding="utf-8-sig")
    by_scenario.to_csv(
        results_dir / "analysis_by_scenario.csv",
        index=False,
        encoding="utf-8-sig",
    )
    comparisons = _paired_rows(
        frame,
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
        "complete": True,
        "records": len(frame),
        "images": int(frame[["dataset", "image_id"]].drop_duplicates().shape[0]),
        "bootstrap_iterations": args.bootstrap_iterations,
    }
    (results_dir / "analysis_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(status, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
