"""Calibrate/replay blind policies; inspect held-out test only after freezing a selection."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from watermark_lab.innovations.budget_geometry import (
    BudgetGeometryConfig,
    CandidateEvidence,
    run_budget_policy,
)

if __package__ in {None, ""}:
    from collect_geometry_v3 import POLICY, PROTOCOL, ROOT, load_protocol, sha256, write_json
else:
    from .collect_geometry_v3 import POLICY, PROTOCOL, ROOT, load_protocol, sha256, write_json

METHODS = ("wam_fixed", "adaptive_identity", "legacy_am", "full_best", "full_soft", "budget_wam")
ORIGINAL_ORDER = (
    "identity",
    "rotation_-10",
    "rotation_-6",
    "rotation_-3",
    "rotation_+3",
    "rotation_+6",
    "rotation_+10",
    "perspective_0.03",
    "perspective_0.06",
    "perspective_0.1",
)


def validate_selected_policy(artifact: dict) -> None:
    if artifact["selection_split"] != "calibration":
        raise RuntimeError("policy must be selected exclusively on calibration")
    if artifact["protocol_sha256"] != sha256(PROTOCOL):
        raise RuntimeError("evaluation protocol changed after policy selection")
    if artifact["analysis_code_sha256"] != sha256(Path(__file__).resolve()):
        raise RuntimeError("analysis code changed after policy selection")
    source = ROOT / "src/watermark_lab/innovations/budget_geometry.py"
    if artifact["policy_code_sha256"] != sha256(source):
        raise RuntimeError("inference policy code changed after calibration was frozen")
    if artifact["selection"]["policy"]["detection_fraction_threshold"] != artifact[
        "detection_thresholds"
    ]["budget_wam"]:
        raise RuntimeError("live policy and evaluation detection thresholds disagree")


def load_traces(split: str) -> tuple[list[dict], list[Path]]:
    directory = ROOT / "results/geometry_v3" / split
    status = json.loads((directory / "collection_status.json").read_text("utf-8"))
    paths = sorted((directory / "traces").glob("*.json"))
    if not status["complete"] or len(paths) != status["images"]:
        raise RuntimeError("incomplete trace collection")
    samples = [json.loads(path.read_text("utf-8")) for path in paths]
    if {sample["fingerprint"] for sample in samples} != {status["fingerprint"]}:
        raise RuntimeError("mixed trace provenance")
    config = load_protocol()
    expected = {
        (positive, attack["id"])
        for positive in (True, False)
        for attack in config["attacks"]
        if positive or attack["id"] in config["negative_attacks"]
    }
    image_keys = {(sample["dataset"], sample["image_id"]) for sample in samples}
    if len(image_keys) != len(samples):
        raise RuntimeError("duplicate image traces")
    for sample in samples:
        keys = {(row["positive"], row["attack"]) for row in sample["records"]}
        if keys != expected or len(keys) != len(sample["records"]):
            raise RuntimeError("trace attack keys differ from frozen protocol")
        for row in sample["records"]:
            row["evidence"] = {
                candidate["name"]: CandidateEvidence(
                    **{key: value for key, value in candidate.items() if key != "elapsed_ms"}
                )
                for candidate in row["candidates"]
            }
            if set(row["evidence"]) != set(ORIGINAL_ORDER):
                raise RuntimeError("missing candidate evidence")
    return samples, paths


def full_decision(
    row: dict, *, fused: bool, gated: bool = False
) -> tuple[np.ndarray, float, list[str]]:
    branches = [row["evidence"][name] for name in ORIGINAL_ORDER]
    identity = branches[0]
    if gated and row["border_evidence"] < 0.02:
        return identity.bits(), identity.selected_fraction, ["identity"]
    ranked = sorted(branches, key=lambda branch: branch.score, reverse=True)
    best = ranked[0]
    if best.selected_fraction <= 0 or best.score - identity.score < 0.006:
        top = [identity]
    else:
        top = [branch for branch in ranked if branch.selected_fraction > 0][: 3 if fused else 1]
    weights = np.exp((np.asarray([branch.score for branch in top]) - top[0].score) / 0.15)
    weights /= weights.sum()
    bits = (
        np.sum(np.asarray([branch.pooled_logits for branch in top]) * weights[:, None], axis=0)
        > 0.5
    ).astype(np.uint8)
    return bits, top[0].selected_fraction, list(ORIGINAL_ORDER)


def records_for_policy(
    samples: list[dict], policy: BudgetGeometryConfig, *, all_methods: bool = True
) -> pd.DataFrame:
    rows = []
    for sample in samples:
        expected = np.asarray(sample["expected_message"])
        for record in sample["records"]:
            trace = record["evidence"]
            identity = trace["identity"]
            decision = run_budget_policy(trace.__getitem__, policy)
            decisions = {
                "budget_wam": (
                    decision.selected.bits(),
                    decision.selected.selected_fraction,
                    [branch.name for branch in decision.visited],
                )
            }
            if all_methods:
                decisions.update(
                    {
                        "wam_fixed": (
                            np.asarray(record["fixed_message"])
                            if record["positive"]
                            else identity.bits(),
                            record["fixed_detection_fraction"],
                            ["identity"],
                        ),
                        "adaptive_identity": (
                            identity.bits(),
                            identity.selected_fraction,
                            ["identity"],
                        ),
                        "legacy_am": full_decision(record, fused=True, gated=True),
                        "full_best": full_decision(record, fused=False),
                        "full_soft": full_decision(record, fused=True),
                    }
                )
            costs = {
                candidate["name"]: candidate["elapsed_ms"] for candidate in record["candidates"]
            }
            for method, (bits, fraction, visited) in decisions.items():
                rows.append(
                    {
                        "dataset": sample["dataset"],
                        "image_id": sample["image_id"],
                        "positive": record["positive"],
                        "attack": record["attack"],
                        "family": record["family"],
                        "method": method,
                        "bit_accuracy": float(np.mean(bits == expected))
                        if record["positive"]
                        else None,
                        "complete_recovery": int(np.array_equal(bits, expected))
                        if record["positive"]
                        else None,
                        "detection_score": fraction,
                        "candidates": len(visited),
                        "trace_cost_ms": sum(costs[name] for name in visited)
                        if method != "wam_fixed"
                        else None,
                        "embed_psnr_db": sample["fixed_psnr_db"]
                        if method == "wam_fixed"
                        else sample["adaptive_psnr_db"],
                        "stop_reason": decision.stop_reason
                        if method == "budget_wam"
                        else "baseline",
                    }
                )
    return pd.DataFrame(rows)


def thresholds(frame: pd.DataFrame) -> dict[str, float]:
    return {
        method: float(np.nextafter(group["detection_score"].max(), np.inf))
        for method, group in frame[~frame["positive"]].groupby("method")
    }


def summarize(frame: pd.DataFrame, cutoffs: dict[str, float]) -> list[dict]:
    rows = []
    positive = frame[frame["positive"]]
    for method, group in positive.groupby("method", sort=True):
        negatives = frame[(frame["method"] == method) & ~frame["positive"]]
        false = negatives["detection_score"] >= cutoffs[method]
        by_image = negatives.assign(false=false).groupby(["dataset", "image_id"])["false"].any()
        rows.append(
            {
                "method": method,
                "positive_records": len(group),
                "negative_records": len(negatives),
                "bit_accuracy": float(group["bit_accuracy"].mean()),
                "complete_recovery": float(group["complete_recovery"].mean()),
                "mean_candidates": float(group["candidates"].mean()),
                "mean_trace_cost_ms": None
                if group["trace_cost_ms"].isna().all()
                else float(group["trace_cost_ms"].mean()),
                "threshold": cutoffs[method],
                "tpr": float((group["detection_score"] >= cutoffs[method]).mean()),
                "fpr": float(false.mean()),
                "false_positive_images": int(by_image.sum()),
                "negative_images": len(by_image),
                "mean_psnr_db": float(group["embed_psnr_db"].mean()),
            }
        )
    return rows


def paired_ci(frame: pd.DataFrame, baseline: str, iterations: int, seed: int) -> dict:
    positive = frame[frame["positive"]]
    key = ["dataset", "image_id", "attack"]
    joined = positive[positive["method"] == "budget_wam"].merge(
        positive[positive["method"] == baseline],
        on=key,
        suffixes=("_new", "_base"),
        validate="one_to_one",
    )
    if len(joined) != len(positive[positive["method"] == baseline]):
        raise RuntimeError("incomplete paired comparison")
    differences = joined["complete_recovery_new"] - joined["complete_recovery_base"]
    units = joined.assign(delta=differences).groupby(["dataset", "image_id"])["delta"].mean()
    rng = np.random.default_rng(seed)
    estimates = np.zeros(iterations)
    for _, group in units.groupby(level=0):
        values = group.to_numpy()
        estimates += values[rng.integers(len(values), size=(iterations, len(values)))].sum(axis=1)
    return {
        "baseline": baseline,
        "image_units": len(units),
        "paired_records": len(joined),
        "recovery_gain_pp": float(100 * units.mean()),
        "ci95_pp": (100 * np.quantile(estimates / len(units), [0.025, 0.975])).tolist(),
        "rescued": int((differences > 0).sum()),
        "regressed": int((differences < 0).sum()),
    }


def select_policy(samples: list[dict], paths: list[Path]) -> dict:
    if (ROOT / "results/geometry_v3/test/provenance.json").exists():
        raise RuntimeError("test has started; policy selection is permanently closed for v3")
    grid_path = ROOT / "configs/geometry_v3_policy_search.yaml"
    grid = yaml.safe_load(grid_path.read_text("utf-8"))
    config = load_protocol()
    default = records_for_policy(samples, BudgetGeometryConfig())
    best_full = default[(default["positive"]) & (default["method"] == "full_best")][
        "complete_recovery"
    ].mean()
    targets = config["selection_targets"]
    candidates = []
    keys = [
        "max_candidates",
        "minimum_search_fraction",
        "identity_minimum_margin",
        "stop_minimum_margin",
        "reliable_agreement",
    ]
    for index, values in enumerate(product(*(grid[key] for key in keys))):
        policy = BudgetGeometryConfig(**dict(zip(keys, values, strict=True)))
        frame = records_for_policy(samples, policy, all_methods=False)
        threshold = thresholds(frame)["budget_wam"]
        if threshold > 1:
            continue
        positives = frame[frame["positive"]]
        recovery = float(positives["complete_recovery"].mean())
        mean_candidates = float(positives["candidates"].mean())
        recovered_detected = float(
            (
                positives["complete_recovery"].astype(bool)
                & (positives["detection_score"] >= threshold)
            ).mean()
        )
        meets_cost = mean_candidates / 10 <= targets["max_mean_candidate_fraction_vs_full"]
        meets_recovery = bool(
            100 * (best_full - recovery) <= targets["recovery_tolerance_vs_full_best_pp"]
        )
        candidates.append(
            {
                "policy": asdict(replace(policy, detection_fraction_threshold=threshold)),
                "recovery": recovery,
                "detected_recovery": recovered_detected,
                "mean_candidates": mean_candidates,
                "meets_cost": meets_cost,
                "meets_recovery": meets_recovery,
                "meets_targets": meets_cost and meets_recovery,
            }
        )
        if index % 144 == 0:
            print(
                f"calibration grid {index}: recovery {recovery:.3f}, "
                f"candidates {mean_candidates:.2f}",
                flush=True,
            )
    eligible = [item for item in candidates if item["meets_targets"]]
    if eligible:
        selected = min(eligible, key=lambda item: (item["mean_candidates"], -item["recovery"]))
    else:
        eligible = [item for item in candidates if item["meets_cost"]]
        selected = max(eligible, key=lambda item: (item["recovery"], -item["mean_candidates"]))
    final_frame = records_for_policy(samples, BudgetGeometryConfig(**selected["policy"]))
    artifact = {
        "version": 1,
        "suite_id": "geometry-v3",
        "selection_split": "calibration",
        "calibration_images": len(samples),
        "policies_evaluated": len(candidates),
        "full_best_recovery": float(best_full),
        "selection": selected,
        "detection_thresholds": thresholds(final_frame),
        "protocol_sha256": sha256(PROTOCOL),
        "grid_sha256": sha256(grid_path),
        "analysis_code_sha256": sha256(Path(__file__).resolve()),
        "policy_code_sha256": sha256(ROOT / "src/watermark_lab/innovations/budget_geometry.py"),
        "calibration_trace_sha256": {
            path.relative_to(ROOT).as_posix(): sha256(path) for path in paths
        },
    }
    if POLICY.exists() and json.loads(POLICY.read_text("utf-8")) != artifact:
        raise RuntimeError("refusing to silently overwrite previously frozen policy")
    write_json(POLICY, artifact)
    write_json(ROOT / "results/geometry_v3/calibration/policy_grid.json", candidates)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("development", "calibration", "test"), required=True)
    parser.add_argument("--select", action="store_true")
    args = parser.parse_args()
    if args.select and args.split != "calibration":
        raise ValueError("selection is allowed only on calibration")
    samples, paths = load_traces(args.split)
    if args.select:
        selected = select_policy(samples, paths)
    elif POLICY.exists():
        selected = json.loads(POLICY.read_text("utf-8"))
    else:
        selected = None
    if args.split == "test" and selected is None:
        raise RuntimeError("test requires a frozen policy")
    if selected:
        validate_selected_policy(selected)
    if args.split == "test":
        trace_provenance = json.loads(
            (ROOT / "results/geometry_v3/test/provenance.json").read_text("utf-8")
        )
        if trace_provenance["source_sha256"][POLICY.relative_to(ROOT).as_posix()] != sha256(POLICY):
            raise RuntimeError("policy artifact changed after test collection started")
    policy = (
        BudgetGeometryConfig(**selected["selection"]["policy"])
        if selected
        else BudgetGeometryConfig()
    )
    frame = records_for_policy(samples, policy)
    cutoffs = selected["detection_thresholds"] if selected else thresholds(frame)
    config = load_protocol()
    output = ROOT / "results/geometry_v3" / args.split
    frame.to_csv(output / "records.csv", index=False, encoding="utf-8-sig")
    summary = {
        "split": args.split,
        "images": len(samples),
        "records": len(frame),
        "methods": summarize(frame, cutoffs),
        "paired": [
            paired_ci(
                frame, method, config["suite"]["bootstrap_iterations"], config["suite"]["seed"]
            )
            for method in METHODS[:-1]
        ],
        "by_family": [],
        "by_dataset": [],
    }
    for category in ("family", "dataset"):
        for value, group in frame.groupby(category):
            # Compare recovery on positives, including attacks without negative controls.
            summary[f"by_{category}"] += [
                {
                    category: value,
                    **paired_ci(
                        group,
                        method,
                        config["suite"]["bootstrap_iterations"],
                        config["suite"]["seed"],
                    ),
                }
                for method in ("legacy_am", "full_best", "full_soft")
            ]
    write_json(output / "analysis.json", summary)
    print(
        json.dumps(
            {
                "split": args.split,
                "policy": asdict(policy),
                "methods": summary["methods"],
                "paired": summary["paired"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
