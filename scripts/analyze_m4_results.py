from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VARIANTS = (
    "A0_fixed_identity",
    "A1_fixed_geometry",
    "A2_adaptive_identity",
    "A3_adaptive_geometry",
)
GEOMETRY_ATTACKS = {
    "rotation_3",
    "rotation_10",
    "perspective_light",
    "perspective_heavy",
    "rotation3_resize75_jpeg80",
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path}")
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _number(row: dict[str, str], field: str) -> float:
    if field == "complete_recovery":
        return float(row[field].lower() == "true")
    return float(row[field])


def _metric_summary(rows: list[dict[str, str]]) -> dict[str, float | int]:
    return {
        "records": len(rows),
        "mean_bit_accuracy": float(np.mean([_number(row, "bit_accuracy") for row in rows])),
        "complete_recovery_rate": float(
            np.mean([_number(row, "complete_recovery") for row in rows])
        ),
        "mean_decode_ms": float(np.mean([_number(row, "decode_ms") for row in rows])),
    }


def _quality_summary(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in rows:
        unique[(row["variant"], row["dataset"], row["image_id"])] = row
    output: list[dict[str, Any]] = []
    for variant in VARIANTS:
        group = [row for key, row in unique.items() if key[0] == variant]
        psnr_values = np.asarray([_number(row, "embed_psnr_db") for row in group])
        output.append(
            {
                "variant": variant,
                "images": len(group),
                "mean_embed_psnr_db": float(np.mean(psnr_values)),
                "std_embed_psnr_db": float(np.std(psnr_values)),
                "minimum_embed_psnr_db": float(np.min(psnr_values)),
                "maximum_embed_psnr_db": float(np.max(psnr_values)),
                "mean_selected_strength": float(
                    np.mean([_number(row, "selected_strength") for row in group])
                ),
                "mean_encode_ms": float(
                    np.mean([_number(row, "encode_ms") for row in group])
                ),
            }
        )
    return output


def _group_summary(
    rows: list[dict[str, str]],
    predicate: Callable[[dict[str, str]], bool],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for variant in VARIANTS:
        group = [row for row in rows if row["variant"] == variant and predicate(row)]
        output.append({"variant": variant, **_metric_summary(group)})
    return output


def _paired_bootstrap(
    rows: list[dict[str, str]],
    *,
    comparison: str,
    metric: str,
    attacks: set[str] | None,
    iterations: int,
    rng: np.random.Generator,
) -> dict[str, Any]:
    baseline = "A0_fixed_identity"
    by_key: dict[tuple[str, str, str], dict[str, float]] = defaultdict(dict)
    for row in rows:
        if attacks is not None and row["attack"] not in attacks:
            continue
        key = (row["dataset"], row["image_id"], row["attack"])
        if row["variant"] in {baseline, comparison}:
            by_key[key][row["variant"]] = _number(row, metric)
    image_differences: dict[tuple[str, str], list[float]] = defaultdict(list)
    for (dataset, image_id, _), values in by_key.items():
        if set(values) != {baseline, comparison}:
            raise RuntimeError("paired M4 record is missing a variant")
        image_differences[(dataset, image_id)].append(
            values[comparison] - values[baseline]
        )
    per_image = np.asarray(
        [float(np.mean(values)) for values in image_differences.values()],
        dtype=np.float64,
    )
    sample_indices = rng.integers(
        0,
        len(per_image),
        size=(iterations, len(per_image)),
    )
    bootstrap_means = np.mean(per_image[sample_indices], axis=1)
    return {
        "comparison": f"{comparison}-A0_fixed_identity",
        "scope": "geometry" if attacks is not None else "all_focus",
        "metric": metric,
        "images": len(per_image),
        "mean_paired_delta": float(np.mean(per_image)),
        "ci95_low": float(np.quantile(bootstrap_means, 0.025)),
        "ci95_high": float(np.quantile(bootstrap_means, 0.975)),
        "bootstrap_iterations": iterations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze M4 paired ablations")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=PROJECT_ROOT / "results/m4_ablation_v2",
    )
    parser.add_argument("--bootstrap-iterations", type=int, default=10_000)
    parser.add_argument(
        "--geometry-attacks",
        nargs="+",
        help="default: the five M4 Debug10 geometry attacks",
    )
    args = parser.parse_args()
    if args.bootstrap_iterations < 1000:
        raise ValueError("bootstrap iterations must be at least 1000")
    results_dir = args.results_dir.resolve()
    rows = _read_csv(results_dir / "all_records.csv")
    images = {(row["dataset"], row["image_id"]) for row in rows}
    attacks_in_results = {row["attack"] for row in rows}
    variants_in_results = {row["variant"] for row in rows}
    if variants_in_results != set(VARIANTS):
        raise RuntimeError(f"unexpected M4 variants: {sorted(variants_in_results)}")
    expected_records = len(VARIANTS) * len(images) * len(attacks_in_results)
    if len(rows) != expected_records:
        raise RuntimeError(f"expected {expected_records} M4 records, got {len(rows)}")

    geometry_attacks = set(args.geometry_attacks or GEOMETRY_ATTACKS)
    missing_attacks = geometry_attacks - attacks_in_results
    if missing_attacks:
        raise RuntimeError(f"geometry attacks missing from results: {sorted(missing_attacks)}")
    quality = _quality_summary(rows)
    geometry = _group_summary(rows, lambda row: row["attack"] in geometry_attacks)
    all_focus = _group_summary(rows, lambda row: True)
    _write_csv(results_dir / "analysis_quality.csv", quality)
    _write_csv(results_dir / "analysis_geometry.csv", geometry)
    _write_csv(results_dir / "analysis_all_focus.csv", all_focus)

    rng = np.random.default_rng(42)
    bootstrap_rows = [
        _paired_bootstrap(
            rows,
            comparison=comparison,
            metric=metric,
            attacks=attacks,
            iterations=args.bootstrap_iterations,
            rng=rng,
        )
        for comparison in VARIANTS[1:]
        for metric in ("bit_accuracy", "complete_recovery")
        for attacks in (None, geometry_attacks)
    ]
    _write_csv(results_dir / "paired_bootstrap.csv", bootstrap_rows)
    print(f"validated records: {len(rows)}")
    print(f"analysis saved: {results_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
