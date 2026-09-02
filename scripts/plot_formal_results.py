from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_ORDER = ("dwt_dct", "trustmark_q", "wam", "am_wam")
MODEL_LABELS = {
    "dwt_dct": "DWT-DCT",
    "trustmark_q": "TrustMark-Q",
    "wam": "WAM",
    "am_wam": "AM-WAM",
}
MODEL_COLORS = {
    "dwt_dct": "#4C78A8",
    "trustmark_q": "#F58518",
    "wam": "#54A24B",
    "am_wam": "#E45756",
}


def _error_bars(frame: pd.DataFrame) -> np.ndarray:
    means = frame["mean"].to_numpy(dtype=float)
    lower = frame["ci95_lower"].to_numpy(dtype=float)
    upper = frame["ci95_upper"].to_numpy(dtype=float)
    return np.vstack((means - lower, upper - means))


def _ordered(frame: pd.DataFrame) -> pd.DataFrame:
    return (
        frame.assign(
            model=pd.Categorical(frame["model"], MODEL_ORDER, ordered=True)
        )
        .sort_values("model")
        .reset_index(drop=True)
    )


def _plot_overall(bootstrap: pd.DataFrame, output_dir: Path) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(10, 4.4), constrained_layout=True)
    for axis, metric, title in (
        (axes[0], "bit_accuracy", "Bit accuracy"),
        (axes[1], "complete_recovery", "Complete recovery rate"),
    ):
        frame = _ordered(
            bootstrap[
                (bootstrap["scope"] == "overall")
                & (bootstrap["metric"] == metric)
            ].copy()
        )
        positions = np.arange(len(frame))
        axis.bar(
            positions,
            frame["mean"],
            yerr=_error_bars(frame),
            capsize=4,
            color=[MODEL_COLORS[str(model)] for model in frame["model"]],
        )
        axis.set_xticks(
            positions,
            [MODEL_LABELS[str(model)] for model in frame["model"]],
            rotation=18,
            ha="right",
        )
        axis.set_ylim(0, 1.02)
        axis.set_title(title)
        axis.set_ylabel("Mean with image-level 95% CI")
        axis.grid(axis="y", alpha=0.25)
    figure.suptitle("formal-v1 overall performance (690 test images, 44 attacks)")
    figure.savefig(output_dir / "formal_overall_performance.png", dpi=200)
    figure.savefig(output_dir / "formal_overall_performance.pdf")
    plt.close(figure)


def _plot_grouped(
    bootstrap: pd.DataFrame,
    *,
    scope: str,
    metric: str,
    title: str,
    filename: str,
    output_dir: Path,
) -> None:
    frame = bootstrap[
        (bootstrap["scope"] == scope) & (bootstrap["metric"] == metric)
    ].copy()
    values = sorted(frame["value"].astype(str).unique())
    positions = np.arange(len(values))
    width = 0.19
    figure, axis = plt.subplots(figsize=(12, 5), constrained_layout=True)
    for model_index, model in enumerate(MODEL_ORDER):
        selected = frame[frame["model"] == model].set_index("value").reindex(values)
        offsets = positions + (model_index - 1.5) * width
        axis.bar(
            offsets,
            selected["mean"],
            width,
            yerr=_error_bars(selected),
            capsize=2,
            label=MODEL_LABELS[model],
            color=MODEL_COLORS[model],
        )
    axis.set_xticks(positions, values, rotation=20, ha="right")
    axis.set_ylim(0, 1.02)
    axis.set_ylabel("Mean with image-level 95% CI")
    axis.set_title(title, pad=44)
    axis.grid(axis="y", alpha=0.25)
    axis.legend(ncols=4, loc="lower center", bbox_to_anchor=(0.5, 1.0))
    figure.savefig(output_dir / f"{filename}.png", dpi=200)
    figure.savefig(output_dir / f"{filename}.pdf")
    plt.close(figure)


def _plot_am_wam_forest(comparisons: pd.DataFrame, output_dir: Path) -> None:
    frame = comparisons[
        (comparisons["comparison"] == "wam")
        & (comparisons["metric"] == "complete_recovery")
        & (comparisons["scope"].isin(["overall", "category"]))
    ].copy()
    frame["label"] = np.where(
        frame["scope"] == "overall", "overall", frame["value"]
    )
    frame = frame.sort_values(
        ["scope", "label"],
        key=lambda column: column.map({"overall": "0"}).fillna("1")
        if column.name == "scope"
        else column,
    ).reset_index(drop=True)
    mean = frame["mean_difference_reference_minus_comparison"].to_numpy(float)
    lower = frame["ci95_lower"].to_numpy(float)
    upper = frame["ci95_upper"].to_numpy(float)
    positions = np.arange(len(frame))
    figure, axis = plt.subplots(
        figsize=(8, max(3.8, 0.55 * len(frame))), constrained_layout=True
    )
    axis.errorbar(
        mean * 100,
        positions,
        xerr=np.vstack(((mean - lower) * 100, (upper - mean) * 100)),
        fmt="o",
        color=MODEL_COLORS["am_wam"],
        capsize=4,
    )
    axis.axvline(0, color="black", linewidth=1, linestyle="--")
    axis.set_yticks(positions, frame["label"])
    axis.invert_yaxis()
    axis.set_xlabel("AM-WAM minus WAM (percentage points, image-level 95% CI)")
    axis.set_title("Paired complete-recovery difference")
    axis.grid(axis="x", alpha=0.25)
    figure.savefig(output_dir / "formal_am_wam_vs_wam_forest.png", dpi=200)
    figure.savefig(output_dir / "formal_am_wam_vs_wam_forest.pdf")
    plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot formal-v1 benchmark summaries")
    parser.add_argument(
        "--results-dir", type=Path, default=PROJECT_ROOT / "results/formal_v1"
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    results_dir = args.results_dir.resolve()
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else (results_dir / "figures").resolve()
    )
    status = json.loads((results_dir / "analysis_status.json").read_text("utf-8"))
    if not status["complete"] and not args.allow_incomplete:
        raise RuntimeError("formal analysis is incomplete; rerun after all result files exist")
    output_dir.mkdir(parents=True, exist_ok=True)
    bootstrap = pd.read_csv(results_dir / "bootstrap_summary.csv")
    comparisons = pd.read_csv(results_dir / "paired_comparisons.csv")
    plt.style.use("seaborn-v0_8-whitegrid")
    _plot_overall(bootstrap, output_dir)
    _plot_grouped(
        bootstrap,
        scope="dataset",
        metric="complete_recovery",
        title="Complete recovery by dataset",
        filename="formal_complete_recovery_by_dataset",
        output_dir=output_dir,
    )
    _plot_grouped(
        bootstrap,
        scope="category",
        metric="bit_accuracy",
        title="Bit accuracy by attack category",
        filename="formal_bit_accuracy_by_category",
        output_dir=output_dir,
    )
    _plot_am_wam_forest(comparisons, output_dir)
    print(f"formal figures saved: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
