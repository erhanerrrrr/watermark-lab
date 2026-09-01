from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from watermark_lab.core.registry import create_model
from watermark_lab.datasets.manifest import iter_manifest_images
from watermark_lab.models.wam_adapter import WamModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        result = yaml.safe_load(stream)
    if not isinstance(result, dict):
        raise ValueError(f"expected mapping in {path}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run WAM on unwatermarked Debug10 images")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs/debug_suite.yaml")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "results/m3_wam_debug",
    )
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    config = _load_yaml(args.config.resolve())
    model = create_model("wam", device=args.device)
    if not isinstance(model, WamModel):
        raise TypeError("registry returned a non-WAM model")

    rows: list[dict[str, Any]] = []
    for dataset in config["datasets"]:
        dataset_id = str(dataset["id"])
        manifest = (PROJECT_ROOT / dataset["manifest"]).resolve()
        root = (PROJECT_ROOT / dataset["root"]).resolve()
        for sample in iter_manifest_images(manifest, root, verify_sha256=True):
            decoded = model.decode(sample.image)
            rows.append(
                {
                    "dataset": dataset_id,
                    "image_id": sample.sample_id,
                    "detected": decoded.detected,
                    "decode_confidence": decoded.confidence,
                    "detected_fraction": decoded.metadata["detected_fraction"],
                    "mean_detection_probability": decoded.metadata[
                        "mean_detection_probability"
                    ],
                    "maximum_detection_probability": decoded.metadata[
                        "maximum_detection_probability"
                    ],
                }
            )
            print(f"negative control: {dataset_id}/{sample.sample_id}", flush=True)

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "negative_controls.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    fractions = np.asarray([float(row["detected_fraction"]) for row in rows])
    summary = {
        "created_at": datetime.now().astimezone().isoformat(),
        "records": len(rows),
        "false_positive_rate": float(np.mean([bool(row["detected"]) for row in rows])),
        "mean_detected_fraction": float(np.mean(fractions)),
        "maximum_detected_fraction": float(np.max(fractions)),
        "p95_detected_fraction": float(np.quantile(fractions, 0.95)),
        "pixel_detection_threshold": model.detection_threshold,
        "minimum_detected_fraction": model.minimum_detected_fraction,
    }
    (output_dir / "negative_control_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
