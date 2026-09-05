"""Generate the human-readable result report exclusively from exported test evidence."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from watermark_lab.api.geometry_research import load_geometry_evidence

ROOT = Path(__file__).resolve().parents[1]
NAMES = {
    "wam_fixed": "B0 WAM 固定嵌入",
    "adaptive_identity": "B1 自适应嵌入 + identity",
    "legacy_am": "旧 AM 门控",
    "full_best": "B2 无门控完整搜索 / 最佳分支",
    "full_soft": "B3 无门控完整搜索 / 软融合",
    "budget_wam": "B4 Budget-WAM",
}
FAMILIES = {
    "control": "无攻击", "non_geometry": "非几何攻击", "median": "中值填充旋转",
    "black": "黑色填充旋转", "reflect": "反射填充旋转", "crop_resize": "裁边缩放旋转",
    "compound": "旋转 + JPEG", "perspective": "透视",
}
STOPS = {
    "insufficient_watermark_evidence": "水印证据不足", "reliable_identity": "原图证据可靠",
    "reliable_correction": "校正证据可靠", "candidate_budget_exhausted": "达到预算上限",
    "all_candidates_evaluated": "全部候选已评估",
}


def fixed(value: float) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def signed(value: float) -> str:
    return f"{'+' if value > 0 else ''}{fixed(value)}"


def percent(value: float) -> str:
    return f"{fixed(100 * value)}%"


def ci(values: tuple[float, float] | list[float]) -> str:
    return f"[{signed(values[0])}, {signed(values[1])}]"


def main() -> int:
    evidence = load_geometry_evidence().model_dump(mode="json")
    methods = {row["method"]: row for row in evidence["methods"]}
    paired = {row["baseline"]: row for row in evidence["paired"]}
    timing = {row["method"]: row for row in evidence["timing"]["methods"]}
    budget = methods["budget_wam"]
    primary = paired["full_best"]
    old = paired["legacy_am"]
    criteria = evidence["test_criteria"]
    noninferiority = (
        "支持预设统计非劣界限" if criteria["noninferiority_ci_supported"] else "尚不支持统计非劣"
    )
    speed_reduction = 100 * (1 - timing["budget_wam"]["mean_ms"] / timing["full_best"]["mean_ms"])
    lines = [
        "# geometry-v3 独立测试结果",
        "",
        "本报告由 `scripts/report_geometry_v3.py` 从版本化证据生成。实现、数据来源、"
        "校准与复现命令见 [GEOMETRY_V3_IMPLEMENTATION.md](GEOMETRY_V3_IMPLEMENTATION.md)。",
        "",
        "## 1. 结论与预设目标",
        "",
        f"Budget-WAM 在 {evidence['test_images']} 张新 test 图、"
        f"{evidence['attack_cases']} 项固定攻击下，完整恢复率为 "
        f"**{percent(budget['complete_recovery'])}**。相对旧 AM 门控差值为 "
        f"**{signed(old['recovery_gain_pp'])} pp**，95% 图像级配对区间 "
        f"{ci(old['ci95_pp'])} pp；相对无门控完整搜索最佳分支差值为 "
        f"{signed(primary['recovery_gain_pp'])} pp，区间 {ci(primary['ci95_pp'])} pp。",
        "",
        f"平均候选调用 **{budget['mean_candidates']:.2f}/10**，单次上限 "
        f"{evidence['policy']['max_candidates']}。预定在线计时子集相对完整搜索的平均耗时"
        f"减少 {speed_reduction:.2f}%；该计时子集不代表所有测试条件。",
        "",
        "| 预设检查 | test 判定 |",
        "|---|---|",
        f"| 相对 B2 恢复下降 ≤ {criteria['recovery_tolerance_pp']:g} pp | "
        f"{'点估计达标' if criteria['recovery_point_target_met'] else '点估计未达标'} |",
        "| 平均候选调用 ≤ 7 | "
        f"{'达标' if criteria['candidate_target_met'] else '未达标'} |",
        "| 差值 95% CI 下界 ≥ −3 pp | "
        f"{noninferiority} |",
        "",
        "点估计达标不等于已证明统计非劣。创新位于基于解码证据的顺序搜索和预算控制，"
        "底层网络仍是官方 WAM；本轮没有训练新网络，也没有证明对任意攻击鲁棒。",
        "",
        "下图仅展示 calibration 上 432 个预设策略与冻结选择。绿色区域为校准目标，"
        "紫色星形为最终策略；test 开始后没有重新选点。",
        "",
        "![校准策略选择](../results/geometry_v3/test/figures/calibration_selection.png)",
        "",
        "## 2. 六种对照与检测",
        "",
        "| 方法 | 完整恢复 | BA | 嵌入 PSNR | 平均候选 | 检测 TPR | 条件级 FPR | 误报图像 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in NAMES:
        row = methods[name]
        lines.append(
            f"| {NAMES[name]} | {percent(row['complete_recovery'])} | "
            f"{percent(row['bit_accuracy'])} | {row['mean_psnr_db']:.3f} dB | "
            f"{row['mean_candidates']:.2f} | {percent(row['tpr'])} | "
            f"{percent(row['fpr'])} | {row['false_positive_images']}/{row['negative_images']} |"
        )
    fp_ci = budget["false_positive_image_ci95"]
    lines += [
        "",
        f"Budget-WAM 的检测区域阈值为 {budget['threshold']:.17g}，只在 48 张 calibration "
        "负图上选择。完整恢复不以检测判正为前提；检测 TPR 单独计算。每张负图在 "
        f"4 项条件中任一误报只计一次，图像级误报率 95% Wilson 区间为 "
        f"[{percent(fp_ci[0])}, {percent(fp_ci[1])}]。80 张负图不足以验证 0.1% 误报指标。",
        "",
        "## 3. 配对差值",
        "",
        "救回与退化以同图、同消息、同攻击记录配对。差值方向均为 Budget-WAM − 基线。",
        "",
        "| 基线 | 恢复率差值 | 95% CI（pp） | 救回 | 退化 |",
        "|---|---:|---|---:|---:|",
    ]
    for name in list(NAMES)[:-1]:
        row = paired[name]
        lines.append(
            f"| {NAMES[name]} | {signed(row['recovery_gain_pp'])} pp | {ci(row['ci95_pp'])} | "
            f"{row['rescued']} | {row['regressed']} |"
        )
    for category, heading in (("family", "攻击家族"), ("dataset", "数据集")):
        lines += [
            "",
            f"### 按{heading}查看",
            "",
            f"| {heading} | Budget-WAM 恢复 | 旧 AM 恢复 | 对旧 AM 差值 / 95% CI | "
            "对完整搜索差值 / 95% CI |",
            "|---|---:|---:|---|---|",
        ]
        rows = evidence[f"by_{category}"]
        for old_row in (row for row in rows if row["baseline"] == "legacy_am"):
            full_row = next(
                row for row in rows
                if row[category] == old_row[category] and row["baseline"] == "full_best"
            )
            label = FAMILIES.get(old_row[category], old_row[category])
            lines.append(
                f"| {label} | {percent(old_row['budget_recovery'])} | "
                f"{percent(old_row['baseline_recovery'])} | "
                f"{signed(old_row['recovery_gain_pp'])} / {ci(old_row['ci95_pp'])} | "
                f"{signed(full_row['recovery_gain_pp'])} / {ci(full_row['ci95_pp'])} |"
            )
    lines += [
        "",
        "### 停止原因与代价",
        "",
        "以下为正样本的停止原因分组。救回/退化对比 B2；不同组包含不同难度的图像，"
        "组内恢复率不能直接解释为停止原因的因果作用。",
        "",
        "| 原因 | 记录数 | 平均候选 | 组内完整恢复 | 对 B2 救回 / 退化 |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in evidence["decision_audit"]:
        lines.append(
            f"| {STOPS.get(row['stop_reason'], row['stop_reason'])} | {row['records']} | "
            f"{row['mean_candidates']:.2f} | {percent(row['complete_recovery'])} | "
            f"{row['rescued_vs_full_best']} / {row['regressed_vs_full_best']} |"
        )
    weak = next(
        row for row in evidence["decision_audit"]
        if row["stop_reason"] == "insufficient_watermark_evidence"
    )
    lines += [
        "",
        f"相对完整搜索的 {primary['regressed']} 条退化记录中，"
        f"{weak['regressed_vs_full_best']} 条在原图水印证据不足时结束。弱证据输入上的"
        "搜索取舍是明确的剩余瓶颈。这是对冻结测试结果的路径诊断，未据此重新选择阈值。",
    ]
    lines += [
        "",
        "分家族结果合并四数据集，分数据集结果合并全部攻击。Bootstrap 按数据集分层，"
        "以图像为重采样单位，重复 2,000 次；这些切片没有多重比较校正。",
        "",
        "## 4. 实际在线时间",
        "",
        f"设备：{evidence['timing']['device']}。固定 12 张 test 图 × 4 攻击 × 2 轮，"
        "暖机、交替方法顺序并同步 GPU。在线消息与轨迹重放逐位一致，Budget-WAM "
        "候选数也一致；实际嵌入与攻击像素哈希已核验。",
        "",
        "| 方法 | 均值 | p50 | p95 | 平均候选 | 进程显存峰值 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, row in timing.items():
        lines.append(
            f"| {NAMES[name]} | {row['mean_ms']:.1f} ms | {row['p50_ms']:.1f} ms | "
            f"{row['p95_ms']:.1f} ms | {row['mean_candidates']:.2f} | "
            f"{row['peak_cuda_allocated_mb']:.0f} MB |"
        )
    lines += [
        "",
        "图中右侧只配对同一计时子集的恢复率与耗时，左侧为全部 80 张图的结果。",
        "",
        "![独立恢复与在线代价](../results/geometry_v3/test/figures/geometry_v3_results.png)",
        "",
        "## 5. 可复核资产与适用范围",
        "",
        "便携证据：[geometry_v3.json](evidence/geometry_v3.json)。完整轨迹、CSV、环境、"
        "来源快照、在线逐次计时和 PNG/PDF 图位于 `results/geometry_v3/`（本地生成，Git 忽略）。"
        "Web 在结果页提供六方法、家族/数据集筛选及 JSON 下载；交互实验支持 "
        "Budget-WAM 和不同旋转填充方式，并展示实际推理决策。",
        "",
        *[f"- {note}" for note in evidence["notes"]],
        "",
        "原 formal-v1、robustness-v2 和边界压力诊断各自保留原协议与结论，不能混成同一排名。"
        "答辩应引用本轮独立 test 数字，校准与开发数字只用于解释设计过程。",
        "",
    ]
    destination = ROOT / "docs/GEOMETRY_V3_RESULTS.md"
    destination.write_text("\n".join(lines), encoding="utf-8")
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
