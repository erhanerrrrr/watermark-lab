"""Build a portable, audited view of frozen per-image benchmark evidence.

This is descriptive reanalysis, not a new model evaluation or a tuning loop.
No model, attack, calibration or original result file is modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from watermark_lab.attacks.protocol import load_attack_protocol
from watermark_lab.datasets.manifest import read_manifest

ROOT = Path(__file__).resolve().parents[1]
MODELS = ("dwt_dct", "trustmark_q", "wam", "am_wam")
METRICS = ("bit_accuracy", "complete_recovery", "embed_psnr_db", "decode_ms")
KEY = ["dataset", "image_id", "attack"]
LABELS = ("COCO", "DIV2K", "DiffusionDB", "W-Bench")


def fingerprint(path: Path) -> dict[str, str]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest.hexdigest()}


def validate_records(
    frame: pd.DataFrame,
    *,
    expected_images: dict[str, list[str]],
    attacks: list[str],
) -> None:
    """Reject count-preserving duplicates, missing pairs and invalid metrics."""
    if set(frame["model"]) != set(MODELS):
        raise ValueError("the evidence snapshot requires all four benchmark models")
    if frame.duplicated(["model", *KEY]).any():
        raise ValueError("duplicate model/image/attack records")
    expected = {
        (dataset, image, attack)
        for dataset, images in expected_images.items()
        for image, attack in product(images, attacks)
    }
    for model, group in frame.groupby("model"):
        actual = set(group[KEY].itertuples(index=False, name=None))
        if actual != expected:
            raise ValueError(f"manifest/protocol key mismatch for {model}")
    for metric in METRICS:
        values = pd.to_numeric(frame[metric], errors="raise").to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError(f"non-finite {metric}")
        if metric in {"bit_accuracy", "complete_recovery"}:
            if np.any((values < 0) | (values > 1)):
                raise ValueError(f"out-of-range {metric}")
        if metric == "complete_recovery" and not np.isin(values, [0, 1]).all():
            raise ValueError("complete_recovery must be binary")
        if metric == "decode_ms" and np.any(values < 0):
            raise ValueError("negative decode time")


def image_bootstrap(
    differences: pd.DataFrame, *, iterations: int, seed: int
) -> tuple[float, list[float]]:
    """Paired, image-cluster bootstrap stratified by dataset, in percentage points."""
    if iterations < 1 or differences.empty:
        raise ValueError("positive iterations and nonempty paired differences required")
    units = differences.groupby(["dataset", "image_id"], sort=True)["difference"].mean()
    generator = np.random.default_rng(seed)
    estimates = np.zeros(iterations)
    for _, stratum in units.groupby(level="dataset", sort=True):
        values = stratum.to_numpy(dtype=float)
        # Bounded memory even when the final dataset grows beyond the present 690 images.
        for start in range(0, iterations, 128):
            stop = min(start + 128, iterations)
            indices = generator.integers(0, len(values), size=(stop - start, len(values)))
            estimates[start:stop] += values[indices].sum(axis=1) / len(units)
    bounds = np.quantile(estimates * 100, [0.025, 0.975])
    return float(units.mean() * 100), [float(value) for value in bounds]


def comparison(frame: pd.DataFrame, *, iterations: int, seed: int) -> dict[str, Any]:
    base = frame[frame["model"] == "wam"]
    enhanced = frame[frame["model"] == "am_wam"]
    paired = base.merge(enhanced, on=KEY, suffixes=("_base", "_enhanced"),
                        validate="one_to_one")
    if len(paired) != len(base) or len(base) != len(enhanced) or paired.empty:
        raise ValueError("incomplete paired evidence")
    old = paired["complete_recovery_base"].astype(bool)
    new = paired["complete_recovery_enhanced"].astype(bool)
    differences = paired[KEY].copy()
    differences["difference"] = new.astype(float) - old.astype(float)
    gain, bounds = image_bootstrap(differences, iterations=iterations, seed=seed)
    return {
        "bit_accuracy_gain_pp": float((paired["bit_accuracy_enhanced"]
                                       - paired["bit_accuracy_base"]).mean() * 100),
        "recovery_gain_pp": gain,
        "recovery_ci95_pp": bounds,
        "rescued": int((~old & new).sum()),
        "regressed": int((old & ~new).sum()),
        "both_recovered": int((old & new).sum()),
        "both_failed": int((~old & ~new).sum()),
        "decode_overhead_ms": float((paired["decode_ms_enhanced"]
                                     - paired["decode_ms_base"]).mean()),
    }


def build_snapshot(
    frame: pd.DataFrame, *, categories: dict[str, str], iterations: int, seed: int
) -> dict[str, Any]:
    rows = []
    datasets = sorted(frame["dataset"].unique())
    attacks = list(categories)
    for dataset in ["all", *datasets]:
        scope = frame if dataset == "all" else frame[frame["dataset"] == dataset]
        for attack in ["all", *attacks]:
            selected = scope if attack == "all" else scope[scope["attack"] == attack]
            rows.append({
                "dataset": dataset,
                "attack": attack,
                "category": "all" if attack == "all" else categories[attack],
                "images": len(selected[["dataset", "image_id"]].drop_duplicates()),
                "paired_records": int((selected["model"] == "wam").sum()),
                "models": [{"id": model, **{
                    metric: float(selected.loc[selected["model"] == model, metric].mean())
                    for metric in METRICS
                }} for model in MODELS],
                "comparison": comparison(selected, iterations=iterations, seed=seed),
            })
    sensitivity = []
    if len(attacks) > 1:
        for attack in attacks:
            selected = frame[frame["attack"] != attack]
            values = comparison(selected, iterations=iterations, seed=seed)
            sensitivity.append({
                "excluded_attack": attack,
                "images": len(selected[["dataset", "image_id"]].drop_duplicates()),
                "paired_records": int((selected["model"] == "wam").sum()),
                "recovery_gain_pp": values["recovery_gain_pp"],
                "recovery_ci95_pp": values["recovery_ci95_pp"],
            })
    return {"rows": rows, "sensitivity": sensitivity}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    parser.add_argument("--output", type=Path, default=ROOT / "configs/research_evidence.json")
    args = parser.parse_args()
    if args.bootstrap_iterations < 1:
        raise ValueError("bootstrap iterations must be positive")
    config_path = ROOT / "configs/formal_benchmark.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    attack_path = ROOT / config["attacks"]["config"]
    protocol = load_attack_protocol(attack_path)
    categories = {case.case_id: case.category for case in protocol.cases}
    provenance = [fingerprint(path) for path in (Path(__file__).resolve(), config_path,
                                                attack_path)]
    frames = []
    expected_images = {}
    datasets = []
    for dataset, label in zip(config["datasets"], LABELS, strict=True):
        dataset_id = dataset["id"]
        manifest = ROOT / dataset["manifest"]
        entries = read_manifest(manifest)
        if any(entry.split not in {"test", "test_validation"} for entry in entries):
            raise ValueError("evidence must only include test manifests")
        expected_images[dataset_id] = [entry.sample_id for entry in entries]
        datasets.append({"id": dataset_id, "label": label, "images": len(entries)})
        provenance.append(fingerprint(manifest))
        for model in MODELS:
            path = ROOT / config["outputs"]["results_dir"] / model / f"{dataset_id}.csv"
            frame = pd.read_csv(path, usecols=["model", "image_id", "attack", *METRICS])
            if not (frame["model"] == model).all():
                raise ValueError(f"model label mismatch in {path}")
            frame["dataset"] = dataset_id
            frames.append(frame)
            provenance.append(fingerprint(path))
    records = pd.concat(frames, ignore_index=True)
    validate_records(records, expected_images=expected_images, attacks=list(categories))
    snapshot = {
        "version": 1,
        "suite_id": config["suite"]["id"],
        "source": "tracked_evidence_snapshot",
        "records": len(records),
        "images": sum(len(images) for images in expected_images.values()),
        "attacks": len(categories),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bootstrap_iterations": args.bootstrap_iterations,
        "seed": config["suite"]["seed"],
        "notes": [
            "这是冻结 formal-v1 的事后描述性再分析，不是新增独立测试或调参依据。",
            "同图同攻击配对；先在图内平均，再按数据集分层重采样图像，生成 95% CI。",
            "总体按图像数量加权，各攻击等权；四个数据集并非等权。CI 不代表未知攻击分布。",
            "逐项 CI 未作多重比较校正，不能把筛选出的单项结果视为独立确证性检验。",
            "救回/退化计数的单位是图像×攻击，相关记录不当作独立样本计算 CI。",
            "DWT-DCT、TrustMark-Q 使用 CPU；WAM、AM-WAM 使用同一 GPU。耗时仅供同环境比较。",
            "定位坐标与融合边界修复后的代码尚未全量重跑；此处仍展示修复前冻结消息恢复结果。",
            "排除单项攻击为敏感性分析，始终保留全协议结果，不据此删除不利攻击。",
        ],
        "datasets": datasets,
        **build_snapshot(records, categories=categories,
                         iterations=args.bootstrap_iterations, seed=config["suite"]["seed"]),
        "provenance": provenance,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False)
                         + "\n", encoding="utf-8")
    temporary.replace(args.output)
    overall = snapshot["rows"][0]
    print(json.dumps({"output": str(args.output), "rows": len(snapshot["rows"]),
                      "overall": overall["comparison"],
                      "without_rotation_10": next(row for row in snapshot["sensitivity"]
                                                  if row["excluded_attack"] == "rotation_10")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
