"""Create a portable test-evidence snapshot and figures from frozen v3 results."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

if __package__ in {None, ""}:
    from analyze_formal_detection import wilson_interval
    from analyze_geometry_v3 import validate_selected_policy
    from collect_geometry_v3 import POLICY, PROTOCOL, ROOT, load_protocol, sha256, write_json
else:
    from .analyze_formal_detection import wilson_interval
    from .analyze_geometry_v3 import validate_selected_policy
    from .collect_geometry_v3 import POLICY, PROTOCOL, ROOT, load_protocol, sha256, write_json

LABELS = {
    "wam_fixed": "WAM (fixed embedding)",
    "adaptive_identity": "Adaptive + identity",
    "legacy_am": "AM-WAM (border gate)",
    "full_best": "Ungated full / best",
    "full_soft": "Ungated full / fusion",
    "budget_wam": "Budget-WAM",
}


def enrich_pairs(frame: pd.DataFrame, pairs: list[dict], category: str | None = None) -> list[dict]:
    positive = frame[frame["positive"]]
    result = []
    for pair in pairs:
        group = positive if category is None else positive[positive[category] == pair[category]]
        means = group.groupby("method")["complete_recovery"].mean()
        result.append(
            {
                **pair,
                "budget_recovery": float(means["budget_wam"]),
                "baseline_recovery": float(means[pair["baseline"]]),
            }
        )
    return result


def decision_audit(frame: pd.DataFrame) -> list[dict]:
    positive = frame[frame["positive"]]
    keys = ["dataset", "image_id", "attack"]
    joined = positive[positive["method"] == "budget_wam"].merge(
        positive[positive["method"] == "full_best"],
        on=keys, suffixes=("_budget", "_full"), validate="one_to_one",
    )
    result = []
    for reason, group in joined.groupby("stop_reason_budget"):
        difference = group["complete_recovery_budget"] - group["complete_recovery_full"]
        result.append(
            {
                "stop_reason": reason,
                "records": len(group),
                "mean_candidates": float(group["candidates_budget"].mean()),
                "complete_recovery": float(group["complete_recovery_budget"].mean()),
                "rescued_vs_full_best": int((difference > 0).sum()),
                "regressed_vs_full_best": int((difference < 0).sum()),
            }
        )
    return result


def main() -> int:
    config = load_protocol()
    selected = json.loads(POLICY.read_text("utf-8"))
    validate_selected_policy(selected)
    directory = ROOT / "results/geometry_v3/test"
    analysis_path = directory / "analysis.json"
    analysis = json.loads(analysis_path.read_text("utf-8"))
    timing_path = directory / "timing.json"
    timing = json.loads(timing_path.read_text("utf-8"))
    if timing["policy_sha256"] != sha256(POLICY) or not timing["live_replay_bitwise_verified"]:
        raise RuntimeError("timing must verify live inference against the same frozen policy")
    records_path = directory / "records.csv"
    frame = pd.read_csv(records_path)
    expected_images = 4 * config["suite"]["test_per_dataset"]
    if analysis["images"] != expected_images or len(frame) != analysis["records"]:
        raise RuntimeError("test evidence is incomplete")
    methods = []
    for name in LABELS:
        method = next(row for row in analysis["methods"] if row["method"] == name)
        item = {**method, "label": LABELS[method["method"]]}
        item["false_positive_image_ci95"] = wilson_interval(
            item["false_positive_images"], item["negative_images"]
        )
        methods.append(item)
    primary = next(row for row in analysis["paired"] if row["baseline"] == "full_best")
    budget = next(row for row in methods if row["method"] == "budget_wam")
    tolerance = config["selection_targets"]["recovery_tolerance_vs_full_best_pp"]
    sources = [
        PROTOCOL,
        POLICY,
        analysis_path,
        timing_path,
        records_path,
        ROOT / "results/geometry_v3/test/provenance.json",
        ROOT / "results/geometry_v3/calibration/analysis.json",
        ROOT / "scripts/export_geometry_v3.py",
        ROOT / "scripts/time_geometry_v3.py",
    ]
    evidence = {
        "suite_id": "geometry-v3",
        "complete": True,
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "calibration_images": selected["calibration_images"],
        "test_images": analysis["images"],
        "attack_cases": len(config["attacks"]),
        "negative_attack_cases": len(config["negative_attacks"]),
        "max_input_side": config["suite"]["max_input_side"],
        "positive_records_per_method": budget["positive_records"],
        "negative_records_per_method": budget["negative_records"],
        "policy": selected["selection"]["policy"],
        "calibration_targets_met": selected["selection"]["meets_targets"],
        "test_criteria": {
            "recovery_tolerance_pp": tolerance,
            "recovery_point_target_met": primary["recovery_gain_pp"] >= -tolerance,
            "noninferiority_ci_supported": primary["ci95_pp"][0] >= -tolerance,
            "candidate_target_met": budget["mean_candidates"] / 10
            <= config["selection_targets"]["max_mean_candidate_fraction_vs_full"],
        },
        "methods": methods,
        "paired": enrich_pairs(frame, analysis["paired"]),
        "by_family": enrich_pairs(frame, analysis["by_family"], "family"),
        "by_dataset": enrich_pairs(frame, analysis["by_dataset"], "dataset"),
        "decision_audit": decision_audit(frame),
        "timing": {key: value for key, value in timing.items() if key not in {"rows", "policy"}},
        "notes": [
            "48 calibration 与 80 test 新图按 SHA-256 与项目历史清单及彼此隔离；"
            "没有重用旧40图作测试。",
            "DIV2K 旧 validation 已用尽，新图来自未使用的 train 源文件；"
            "不声称与 WAM 预训练数据隔离。",
            "所有方法在嵌入前将最长边限制为1024，保留宽高比；正式v1原分辨率结果不与本轮混排。",
            "B1至B4及旧AM门控对照共享逐像素相同的嵌入图和攻击图，策略不知道消息真值、角度或填充类型。",
            "策略和检测阈值仅在校准集选择，测试开始后禁止重选。各基线分别使用自己的校准负样本阈值。",
            "恢复率不要求检测阈值判正；TPR与误报同时报告，避免把消息正确与低误报混为一谈。",
            "误报图像计数表示4个负样本条件中任一条件误报，每图只计一次，Wilson区间按80图计算。",
            "候选预算限制推理调用次数，不保证墙钟毫秒上限；trace成本是重放估计，速度结论以独立在线计时为准。",
            "在线计时使用预定12图×4攻击×2次，交替顺序并同步GPU；其耗时分布不是全部80图16攻击的耗时分布。",
            "差值CI使用按数据集分层的图像级配对Bootstrap；达到恢复点估计目标不等于已证明统计非劣。",
            "80个负样本图像不足以验证0.1%误报指标；0次观察误报也有非零置信区间上界。",
            "图像按排除历史后的文件顺序选取，样本量较小；数据集和攻击家族切片没有多重比较校正。",
        ],
        "provenance": [
            {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)} for path in sources
        ],
    }
    write_json(ROOT / "docs/evidence/geometry_v3.json", evidence)

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "font.size": 10})
    figure, axes = plt.subplots(1, 2, figsize=(13, 4.5))
    chosen = ["legacy_am", "full_best", "budget_wam"]
    families = [
        "control",
        "non_geometry",
        "median",
        "black",
        "reflect",
        "crop_resize",
        "compound",
        "perspective",
    ]
    colors = ["#8095b5", "#b0b5bc", "#087f70"]
    for index, (method, color) in enumerate(zip(chosen, colors, strict=True)):
        group = frame[(frame["positive"]) & (frame["method"] == method)]
        values = [
            100 * group[group["family"] == family]["complete_recovery"].mean()
            for family in families
        ]
        axes[0].bar(
            np.arange(len(families)) + (index - 1) * 0.25,
            values,
            0.24,
            color=color,
            label=LABELS[method],
        )
    axes[0].set_xticks(
        np.arange(len(families)),
        [value.replace("_", " ") for value in families],
        rotation=35,
        ha="right",
    )
    axes[0].set_ylabel("Complete recovery (%)")
    axes[0].set_ylim(0, 105)
    axes[0].set_title("80 held-out images / fixed attack families", loc="left")
    axes[0].legend(fontsize=8, loc="lower left")
    # Pair accuracy and timing over exactly the same measured image/attack conditions.
    keys = {(row["dataset"], row["image_id"], row["attack"]) for row in timing["rows"]}
    for measured in timing["methods"]:
        group = frame[(frame["positive"]) & (frame["method"] == measured["method"])]
        group = group[
            [tuple(row) in keys for row in group[["dataset", "image_id", "attack"]].values]
        ]
        if len(group) != timing["measured_conditions"]:
            raise RuntimeError("timing/accuracy condition keys disagree")
        x, y = measured["mean_ms"], 100 * group["complete_recovery"].mean()
        color = dict(zip(chosen, colors, strict=True)).get(measured["method"], "#c89141")
        axes[1].scatter(x, y, s=60, color=color)
        rightmost = measured["method"] == "full_best"
        axes[1].annotate(
            LABELS[measured["method"]],
            (x, y),
            xytext=(-6 if rightmost else 6, 5),
            textcoords="offset points",
            ha="right" if rightmost else "left",
            fontsize=8,
        )
    axes[1].set_xlabel("Measured sequential decode time (ms)")
    axes[1].set_ylabel("Complete recovery on timed conditions (%)")
    axes[1].set_title("Same 12 images / 4 attacks / 2 repetitions", loc="left")
    axes[1].margins(x=0.3, y=0.3)
    axes[1].set_xlim(left=0)
    axes[1].set_ylim(0, 105)
    for axis in axes:
        axis.yaxis.grid(True, alpha=0.15)
        axis.set_axisbelow(True)
    figure.tight_layout()
    figure_dir = directory / "figures"
    figure_dir.mkdir(exist_ok=True)
    for extension in ("png", "pdf"):
        figure.savefig(
            figure_dir / f"geometry_v3_results.{extension}", dpi=180, bbox_inches="tight"
        )
    plt.close(figure)
    grid = json.loads(
        (ROOT / "results/geometry_v3/calibration/policy_grid.json").read_text("utf-8")
    )
    figure, axis = plt.subplots(figsize=(7.8, 4.5))
    required_recovery = 100 * selected["full_best_recovery"] - tolerance
    axis.fill_between([0.8, 7], required_recovery, 101, color="#e6f5ef", zorder=0)
    for maximum, color in ((5, "#c89141"), (7, "#087f70"), (10, "#7995b9")):
        group = [row for row in grid if row["policy"]["max_candidates"] == maximum]
        axis.scatter(
            [row["mean_candidates"] for row in group],
            [100 * row["recovery"] for row in group],
            s=18, alpha=0.5, color=color, label=f"Candidate cap {maximum}",
        )
    axis.scatter(
        selected["selection"]["mean_candidates"], 100 * selected["selection"]["recovery"],
        s=190, marker="*", color="#8d236b", edgecolors="white", label="Frozen selection", zorder=5,
    )
    axis.scatter(
        10, 100 * selected["full_best_recovery"], marker="D", color="#33485f", s=45,
        label="Full search / best",
    )
    axis.axhline(required_recovery, color="#839b8f", linestyle="--", linewidth=1)
    axis.axvline(7, color="#839b8f", linestyle="--", linewidth=1)
    axis.set(
        xlabel="Mean candidate calls (calibration positives)",
        ylabel="Complete recovery on calibration (%)", xlim=(0.8, 10.5),
        ylim=(68, 100),
        title="432 predefined policies / 48 calibration images",
    )
    axis.legend(fontsize=8, loc="lower right")
    axis.grid(alpha=0.15)
    figure.tight_layout()
    for extension in ("png", "pdf"):
        figure.savefig(figure_dir / f"calibration_selection.{extension}", dpi=180)
    plt.close(figure)
    print(
        json.dumps(
            {
                "test_criteria": evidence["test_criteria"],
                "primary": primary,
                "budget": budget,
                "timing": timing["methods"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
