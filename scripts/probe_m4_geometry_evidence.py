from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from pathlib import Path

import numpy as np
import yaml

from watermark_lab.attacks.protocol import apply_attack_case, load_attack_protocol
from watermark_lab.datasets.manifest import iter_manifest_images
from watermark_lab.innovations.geometry_sync import geometry_border_evidence

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    config_path = PROJECT_ROOT / "configs/m4_ablation.yaml"
    with config_path.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    with (PROJECT_ROOT / config["inputs"]["debug_suite"]).open(
        "r",
        encoding="utf-8",
    ) as stream:
        debug = yaml.safe_load(stream)
    protocol = load_attack_protocol(PROJECT_ROOT / config["inputs"]["attack_protocol"])
    cases = {case.case_id: case for case in protocol.cases}
    rows: list[dict[str, object]] = []
    for dataset in debug["datasets"]:
        dataset_id = str(dataset["id"])
        samples = iter_manifest_images(
            PROJECT_ROOT / dataset["manifest"],
            PROJECT_ROOT / dataset["root"],
            verify_sha256=True,
        )
        for sample in samples:
            for attack_id in config["focus_attacks"]:
                digest = hashlib.sha256(
                    f"evidence:{dataset_id}:{sample.sample_id}:{attack_id}".encode()
                ).digest()
                rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
                attacked = apply_attack_case(sample.image, cases[attack_id], rng)
                rows.append(
                    {
                        "dataset": dataset_id,
                        "image_id": sample.sample_id,
                        "attack": attack_id,
                        "border_geometry_evidence": geometry_border_evidence(attacked),
                    }
                )

    output = PROJECT_ROOT / "results/m4_ablation/geometry_evidence_probe.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    groups: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        groups[str(row["attack"])].append(float(row["border_geometry_evidence"]))
    for attack, values in sorted(groups.items()):
        print(
            f"{attack:32} min={min(values):.4f} mean={np.mean(values):.4f} "
            f"max={max(values):.4f} pass@.02={np.mean(np.asarray(values) >= 0.02):.3f}"
        )
    print(f"saved: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
