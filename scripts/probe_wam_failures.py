from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path

import numpy as np

from watermark_lab.attacks.protocol import apply_attack_case, load_attack_protocol
from watermark_lab.datasets.manifest import iter_manifest_images
from watermark_lab.metrics.image_quality import psnr
from watermark_lab.metrics.message import bit_accuracy, complete_recovery
from watermark_lab.models.wam_adapter import WamModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROBE_ATTACKS = (
    "clean",
    "blur_r8",
    "rotation_10",
    "perspective_heavy",
    "local_splice_50",
    "copy_move_50",
    "local_inpaint_50",
    "rotation3_resize75_jpeg80",
)
PROBE_STRENGTHS = (1.25, 1.82421875, 2.5, 3.5)
BIT_THRESHOLDS = (0.0, 0.25, 0.5, 0.75)


def _fixed_message(sample_id: str) -> np.ndarray:
    digest = hashlib.sha256(f"wam-failure-probe:{sample_id}".encode()).digest()
    return np.unpackbits(np.frombuffer(digest[:4], dtype=np.uint8)).astype(np.uint8)


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe WAM content, strength, and bit threshold")
    parser.add_argument("--device", default="auto")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "results/m3_wam_debug/failure_probe.csv",
    )
    args = parser.parse_args()

    manifest = PROJECT_ROOT / "data/manifests/div2k_valid_hr_debug10.csv"
    dataset_root = PROJECT_ROOT / "data/raw/debug10/div2k_valid_hr"
    selected_ids = {"0801.png", "0802.png", "0803.png"}
    samples = [
        sample
        for sample in iter_manifest_images(manifest, dataset_root, verify_sha256=True)
        if sample.sample_id in selected_ids
    ]
    protocol = load_attack_protocol(PROJECT_ROOT / "configs/attacks.yaml")
    cases = {case.case_id: case for case in protocol.cases if case.case_id in PROBE_ATTACKS}
    model = WamModel(strength=PROBE_STRENGTHS[0], device=args.device)

    rows: list[dict[str, object]] = []
    for sample in samples:
        message = _fixed_message(sample.sample_id)
        for strength in PROBE_STRENGTHS:
            model.strength = strength
            embedded = model.encode(sample.image, message)
            embed_quality = psnr(sample.image, embedded.image)
            for attack_id in PROBE_ATTACKS:
                case = cases[attack_id]
                attacked = apply_attack_case(
                    embedded.image,
                    case,
                    np.random.default_rng(protocol.seed),
                )
                prediction = model.predict_spatial(attacked)
                selected = prediction.detection_probabilities > model.detection_threshold
                if np.any(selected):
                    pooled_logits = np.mean(prediction.bit_logits[:, selected], axis=1)
                else:
                    pooled_logits = np.full(model.message_bits, -np.inf, dtype=np.float32)
                row: dict[str, object] = {
                    "image_id": sample.sample_id,
                    "strength": strength,
                    "embed_psnr_db": embed_quality,
                    "attack": attack_id,
                    "detected_fraction": float(np.mean(selected)),
                    "mean_detection_probability": float(
                        np.mean(prediction.detection_probabilities)
                    ),
                    "minimum_bit_margin_at_05": float(
                        np.min(np.abs(pooled_logits - 0.5))
                    ),
                    "mean_bit_margin_at_05": float(
                        np.mean(np.abs(pooled_logits - 0.5))
                    ),
                }
                for threshold in BIT_THRESHOLDS:
                    suffix = str(threshold).replace(".", "")
                    decoded = (pooled_logits > threshold).astype(np.uint8)
                    row[f"bit_accuracy_t{suffix}"] = bit_accuracy(message, decoded)
                    row[f"complete_recovery_t{suffix}"] = complete_recovery(
                        message,
                        decoded,
                    )
                rows.append(row)
            print(
                f"probe: {sample.sample_id} strength={strength:.6f} "
                f"PSNR={embed_quality:.3f}",
                flush=True,
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"failure probe saved: {args.output.resolve()} ({len(rows)} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
