"""Export the compact, reviewable border-stress evidence and a publication figure."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

if __package__ in {None, ""}:
    from run_border_stress import BOUNDARIES, ROOT, sha256
else:
    from .run_border_stress import BOUNDARIES, ROOT, sha256


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=ROOT / "results/border_stress_v1")
    parser.add_argument(
        "--evidence-output", type=Path, default=ROOT / "docs/evidence/border_stress_v1.json"
    )
    args = parser.parse_args()
    results = args.results_dir.resolve()
    analysis = json.loads((results / "analysis.json").read_text(encoding="utf-8"))
    source = results / "all_records.csv"
    if not analysis["complete"] or sha256(source) != analysis["results_sha256"]:
        raise RuntimeError("analysis does not match complete source records")
    with source.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != analysis["expected_records"]:
        raise RuntimeError("source record count mismatch")
    if {row["run_fingerprint"] for row in rows} != {analysis["run_fingerprint"]}:
        raise RuntimeError("source fingerprint mismatch")
    provenance = json.loads(
        (results / "provenance/protocol_snapshot.json").read_text(encoding="utf-8")
    )
    by_boundary = []
    for boundary in BOUNDARIES:
        group = [r for r in rows if r["boundary"] == boundary]
        wam = [r for r in group if r["model"] == "wam"]
        am = [r for r in group if r["model"] == "am_wam"]
        pairs = [
            r
            for r in analysis["paired_image_bootstrap"]
            if r["boundary"] == boundary and r["metric"] == "complete_recovery"
        ]
        by_boundary.append(
            {
                "boundary": boundary,
                "image_units": analysis["image_units"],
                "records_per_model": len(am),
                "wam_complete_recovery": float(
                    np.mean([float(r["complete_recovery"]) for r in wam])
                ),
                "am_wam_complete_recovery": float(
                    np.mean([float(r["complete_recovery"]) for r in am])
                ),
                "am_same_embedding_identity_recovery": float(
                    np.mean([float(r["identity_complete_recovery"]) for r in am])
                ),
                "am_search_skipped_fraction": float(
                    np.mean([float(r["geometry_search_skipped"]) for r in am])
                ),
                "am_sync_accepted_fraction": float(
                    np.mean([float(r["geometry_candidate_accepted"]) for r in am])
                ),
                "paired_complete_recovery": {
                    r["comparison"]: {key: r[key] for key in ("mean", "ci95_low", "ci95_high")}
                    for r in pairs
                },
            }
        )
    evidence = {
        "suite_id": "border-stress-v1-exploratory",
        "interpretation": analysis["interpretation"],
        "complete": True,
        "image_units": analysis["image_units"],
        "records": len(rows),
        "bootstrap_iterations": provenance["config"]["suite"]["bootstrap_iterations"],
        "angles": provenance["config"]["attacks"]["angles"],
        "run_fingerprint": analysis["run_fingerprint"],
        "source_records_sha256": analysis["results_sha256"],
        "frozen_geometry_sha256": provenance["config"]["inputs"]["frozen_geometry_sha256"],
        "by_boundary": by_boundary,
    }
    args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_output.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    figure, (recovery, effects) = plt.subplots(
        1, 2, figsize=(12.4, 4.6), gridspec_kw={"width_ratios": [1.3, 1]}
    )
    positions = np.arange(len(by_boundary))
    labels = ["Median", "Black", "Reflect", "Crop + resize"]
    bars = [
        ("WAM", "wam_complete_recovery", "#7797bd"),
        ("Adaptive embedding + identity", "am_same_embedding_identity_recovery", "#a7b8a0"),
        ("AM-WAM (frozen)", "am_wam_complete_recovery", "#28776d"),
    ]
    for index, (label, metric, color) in enumerate(bars):
        recovery.bar(
            positions + (index - 1) * 0.25,
            [100 * item[metric] for item in by_boundary],
            0.24,
            color=color,
            label=label,
        )
    recovery.set_xticks(positions, labels)
    recovery.set_ylim(0, 104)
    recovery.set_ylabel("Complete message recovery (%)")
    recovery.set_title("Recovery under changed rotation boundaries", loc="left", fontsize=11)
    recovery.legend(loc="upper left", bbox_to_anchor=(0, -0.14), frameon=False, fontsize=9)
    recovery.yaxis.grid(True, alpha=0.18)
    recovery.set_axisbelow(True)
    for index, item in enumerate(by_boundary):
        delta = item["paired_complete_recovery"]["sync_same_embedding"]
        mean, low, high = [100 * delta[key] for key in ("mean", "ci95_low", "ci95_high")]
        effects.errorbar(
            mean, index, xerr=[[mean - low], [high - mean]], fmt="o", color="#28776d", capsize=4
        )
    effects.set_yticks(
        positions,
        [
            f"{label}\nsearch skipped {100 * item['am_search_skipped_fraction']:.1f}%"
            for label, item in zip(labels, by_boundary, strict=True)
        ],
    )
    effects.invert_yaxis()
    effects.axvline(0, color="#84909d", linewidth=1)
    effects.set_xlabel("Synchronization gain (percentage points; 95% CI)")
    effects.set_title("Same embedding, paired image bootstrap", loc="left", fontsize=11)
    effects.xaxis.grid(True, alpha=0.18)
    figure.suptitle(
        "Exploratory diagnosis: 40 previously seen images, 3 rotation angles",
        fontsize=12,
        x=0.5,
        y=0.99,
    )
    figure.tight_layout(rect=(0, 0.06, 1, 0.94))
    directory = results / "figures"
    directory.mkdir(exist_ok=True)
    for suffix in ("png", "pdf"):
        figure.savefig(directory / f"border_stress_recovery.{suffix}", dpi=180, bbox_inches="tight")
    plt.close(figure)
    print(json.dumps(evidence, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
