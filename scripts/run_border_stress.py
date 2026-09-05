"""Exploratory padding stress test, independent of the frozen attack registry.

The old geometry module is recovered from its pinned Git revision and SHA-256,
so later localization/fusion bug fixes cannot silently change this diagnostic.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import platform
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image

from watermark_lab.datasets.manifest import iter_manifest_images, read_manifest
from watermark_lab.metrics.image_quality import psnr

ROOT = Path(__file__).resolve().parents[1]
BOUNDARIES = ("median", "black", "reflect", "crop_resize")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pixel_sha256(array: np.ndarray) -> str:
    digest = hashlib.sha256(str(array.shape).encode("ascii"))
    digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()


def rotate_boundary(image: np.ndarray, angle: float, boundary: str) -> np.ndarray:
    """Rotate around the same center; reflection changes only out-of-frame samples."""
    if boundary not in BOUNDARIES:
        raise ValueError(f"unknown boundary: {boundary}")
    if not math.isfinite(angle) or abs(angle) >= 45:
        raise ValueError("angle must be finite and within (-45, 45)")
    source = np.asarray(image, dtype=np.uint8)
    height, width = source.shape[:2]
    if height < 8 or width < 8:
        raise ValueError("border stress requires image dimensions of at least eight")
    fill = tuple(int(value) for value in np.median(source, axis=(0, 1)))
    if boundary == "reflect":
        padding = max(height, width)
        padded = np.pad(source, ((padding, padding), (padding, padding), (0, 0)), mode="reflect")
        rotated = Image.fromarray(padded).rotate(angle, Image.Resampling.BICUBIC)
        rotated = rotated.crop((padding, padding, padding + width, padding + height))
    else:
        rotated = Image.fromarray(source).rotate(
            angle,
            Image.Resampling.BICUBIC,
            expand=False,
            fillcolor=(0, 0, 0) if boundary == "black" else fill,
        )
    if boundary == "crop_resize" and angle != 0:
        radians = math.radians(abs(angle))
        cosine, sine = math.cos(radians), math.sin(radians)
        scale = min(
            width / (width * cosine + height * sine), height / (width * sine + height * cosine)
        )
        crop_width = max(1, math.floor(width * scale) - 4)
        crop_height = max(1, math.floor(height * scale) - 4)
        left, top = (width - crop_width) // 2, (height - crop_height) // 2
        rotated = rotated.crop((left, top, left + crop_width, top + crop_height))
        rotated = rotated.resize((width, height), Image.Resampling.BICUBIC)
    return np.ascontiguousarray(np.asarray(rotated, dtype=np.uint8))


def paired_bootstrap(values: np.ndarray, iterations: int, seed: int) -> dict[str, float]:
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or not values.size or not np.all(np.isfinite(values)):
        raise ValueError("bootstrap requires nonempty finite image-unit values")
    rng = np.random.default_rng(seed)
    estimates = values[rng.integers(len(values), size=(iterations, len(values)))].mean(axis=1)
    return {
        "mean": float(values.mean()),
        "ci95_low": float(np.quantile(estimates, 0.025)),
        "ci95_high": float(np.quantile(estimates, 0.975)),
    }


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected mapping: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    temporary.replace(path)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _frozen_geometry(config: dict[str, Any], provenance: Path):
    path = provenance / "geometry_sync_frozen.py"
    expected = config["inputs"]["frozen_geometry_sha256"]
    if not path.exists():
        commit = config["inputs"]["frozen_geometry_commit"]
        result = subprocess.run(
            ["git", "show", f"{commit}:src/watermark_lab/innovations/geometry_sync.py"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
        # Source checkouts may use CRLF; the pinned hash describes the LF source.
        source = result.stdout.replace(b"\r\n", b"\n")
        if hashlib.sha256(source).hexdigest() != expected:
            raise RuntimeError("pinned geometry source SHA-256 mismatch")
        path.write_bytes(source)
    if sha256(path) != expected:
        raise RuntimeError("frozen geometry snapshot SHA-256 mismatch")
    name = "_border_stress_frozen_geometry"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def summarize(rows: list[dict[str, Any]], *, iterations: int, seed: int) -> dict[str, Any]:
    summary: list[dict[str, Any]] = []
    paired: list[dict[str, Any]] = []
    for boundary in BOUNDARIES:
        for model in ("wam", "am_wam"):
            group = [r for r in rows if r["boundary"] == boundary and r["model"] == model]
            summary.append(
                {
                    "boundary": boundary,
                    "model": model,
                    "records": len(group),
                    **{
                        key: float(np.mean([r[key] for r in group]))
                        for key in (
                            "bit_accuracy",
                            "complete_recovery",
                            "decode_ms",
                            "border_evidence",
                            "geometry_search_skipped",
                            "geometry_candidate_accepted",
                        )
                    },
                }
            )
        wam = {
            (r["dataset"], r["image_id"], r["angle"]): r
            for r in rows
            if r["boundary"] == boundary and r["model"] == "wam"
        }
        am = [r for r in rows if r["boundary"] == boundary and r["model"] == "am_wam"]
        for metric in ("bit_accuracy", "complete_recovery"):
            for comparison in ("am_minus_wam", "sync_same_embedding"):
                units: dict[tuple[str, str], list[float]] = {}
                for row in am:
                    key = (row["dataset"], row["image_id"])
                    baseline = (
                        wam[(*key, row["angle"])][metric]
                        if comparison == "am_minus_wam"
                        else row[f"identity_{metric}"]
                    )
                    units.setdefault(key, []).append(float(row[metric]) - float(baseline))
                values = np.asarray([np.mean(value) for value in units.values()])
                paired.append(
                    {
                        "boundary": boundary,
                        "metric": metric,
                        "comparison": comparison,
                        "image_units": len(values),
                        **paired_bootstrap(values, iterations, seed),
                    }
                )
    return {"by_boundary": summary, "paired_image_bootstrap": paired}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/border_stress_v1.yaml")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--limit-per-dataset", type=int, default=10)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--analyze-only", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit_per_dataset <= 10:
        raise ValueError("limit-per-dataset must be within [1, 10]")
    config_path = args.config.resolve()
    config = _load(config_path)
    output = (args.output_dir or ROOT / config["outputs"]["results_dir"]).resolve()
    provenance = output / "provenance"
    provenance.mkdir(parents=True, exist_ok=True)
    protocol = _load(ROOT / config["inputs"]["dataset_config"])
    seed = int(config["suite"]["seed"])
    angles = list(config["attacks"]["angles"])
    boundaries = list(config["attacks"]["boundaries"])
    expected = (
        len(protocol["datasets"]) * args.limit_per_dataset * len(angles) * len(boundaries) * 2
    )
    if args.limit_per_dataset == 10 and expected != config["suite"]["expected_records"]:
        raise RuntimeError("protocol expected record count mismatch")

    partial_paths = [
        output / ".partials" / f"{dataset['id']}_{index:03d}.json"
        for dataset in protocol["datasets"]
        for index in range(args.limit_per_dataset)
    ]
    if not args.analyze_only:
        frozen = _frozen_geometry(config, provenance)
        dependencies = [
            config_path,
            ROOT / config["inputs"]["dataset_config"],
            ROOT / config["inputs"]["calibration"],
            ROOT / config["inputs"]["m4_config"],
            Path(__file__).resolve(),
            ROOT / "src/watermark_lab/innovations/content_adaptive.py",
            provenance / "geometry_sync_frozen.py",
        ]
        dependencies.extend(ROOT / d["manifest"] for d in protocol["datasets"])
        hashes = {
            str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path): sha256(path)
            for path in dependencies
        }
        fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
        snapshot = provenance / "protocol_snapshot.json"
        frozen_protocol = {
            "config": config,
            "limit_per_dataset": args.limit_per_dataset,
            "dependency_sha256": hashes,
            "run_fingerprint": fingerprint,
        }
        if (
            snapshot.exists()
            and json.loads(snapshot.read_text(encoding="utf-8")) != frozen_protocol
        ):
            raise RuntimeError(
                "output directory belongs to a different frozen protocol/code; "
                "use a new --output-dir"
            )
        _write_json(snapshot, frozen_protocol)
        from watermark_lab.innovations.content_adaptive import AdaptiveStrengthConfig
        from watermark_lab.models.am_wam import AmWamModel
        from watermark_lab.models.wam_adapter import (
            OFFICIAL_WEIGHT_SHA256,
            WamModel,
            default_wam_checkpoint,
        )

        weight_hash = sha256(default_wam_checkpoint())
        if weight_hash != OFFICIAL_WEIGHT_SHA256:
            raise RuntimeError("actual WAM weight hash differs from pinned official weight")
        m4 = _load(ROOT / config["inputs"]["m4_config"])
        calibration = _load(ROOT / config["inputs"]["calibration"])
        wam = WamModel(device=args.device)
        am = AmWamModel(
            device=args.device,
            backend=wam._backend,
            adaptive_config=AdaptiveStrengthConfig(**m4["adaptive_strength"]),
        )
        am._geometry_decoder = frozen.GeometrySyncDecoder(
            am.base_model, config=frozen.GeometrySyncConfig(**m4["geometry_sync"])
        )
        import torch

        environment = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "python": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "torch": torch.__version__,
            "device": wam._backend.device_name,
            "gpu": torch.cuda.get_device_name() if torch.cuda.is_available() else None,
            "actual_checkpoint_sha256": weight_hash,
            "run_fingerprint": fingerprint,
        }
        _write_json(provenance / "environment.json", environment)
        started = time.perf_counter()
        for dataset in protocol["datasets"]:
            dataset_id = dataset["id"]
            manifest = ROOT / dataset["manifest"]
            entries = read_manifest(manifest)[: args.limit_per_dataset]
            samples = islice(
                iter_manifest_images(manifest, ROOT / dataset["root"], verify_sha256=True),
                args.limit_per_dataset,
            )
            strength = calibration["models"]["wam"]["datasets"][dataset["calibration_id"]][
                "selected"
            ]["strength"]
            wam.strength = am.strength = float(strength)
            for index, (entry, sample) in enumerate(zip(entries, samples, strict=True)):
                partial = output / ".partials" / f"{dataset_id}_{index:03d}.json"
                if partial.exists():
                    saved = json.loads(partial.read_text(encoding="utf-8"))
                    if saved["run_fingerprint"] != fingerprint:
                        raise RuntimeError("partial fingerprint mismatch")
                    print(f"reuse {dataset_id} {index + 1}", flush=True)
                    continue
                sample_seed = int.from_bytes(
                    hashlib.sha256(f"{seed}:{dataset_id}:{sample.sample_id}".encode()).digest()[:8],
                    "big",
                )
                message = np.random.default_rng(sample_seed).integers(0, 2, 32, dtype=np.uint8)
                rows = []
                for model in (wam, am):
                    encode_started = time.perf_counter()
                    embedded = model.encode(sample.image, message)
                    encode_ms = 1000 * (time.perf_counter() - encode_started)
                    embed_hash = pixel_sha256(embedded.image)
                    embed_quality = psnr(sample.image, embedded.image)
                    for angle in angles:
                        for boundary in boundaries:
                            attacked = rotate_boundary(embedded.image, angle, boundary)
                            decode_started = time.perf_counter()
                            decoded = model.decode(attacked)
                            decode_ms = 1000 * (time.perf_counter() - decode_started)
                            identity = am.base_model.decode(attacked) if model is am else decoded
                            meta = decoded.metadata
                            rows.append(
                                {
                                    "dataset": dataset_id,
                                    "image_id": sample.sample_id,
                                    "model": model.name,
                                    "angle": angle,
                                    "boundary": boundary,
                                    "sample_seed": sample_seed,
                                    "source_file_sha256": entry.sha256,
                                    "message": "".join(str(int(bit)) for bit in message),
                                    "embedded_pixel_sha256": embed_hash,
                                    "attacked_pixel_sha256": pixel_sha256(attacked),
                                    "embed_psnr_db": embed_quality,
                                    "encode_ms": encode_ms,
                                    "bit_accuracy": float(np.mean(decoded.message == message)),
                                    "complete_recovery": int(
                                        np.array_equal(decoded.message, message)
                                    ),
                                    "identity_bit_accuracy": float(
                                        np.mean(identity.message == message)
                                    ),
                                    "identity_complete_recovery": int(
                                        np.array_equal(identity.message, message)
                                    ),
                                    "decode_ms": decode_ms,
                                    "detected": bool(decoded.detected),
                                    "selected_transform": meta.get(
                                        "selected_transform", "identity"
                                    ),
                                    "border_evidence": frozen.geometry_border_evidence(attacked),
                                    "geometry_search_skipped": int(
                                        meta.get("geometry_search_skipped", True)
                                    ),
                                    "geometry_candidate_accepted": int(
                                        meta.get("geometry_candidate_accepted", False)
                                    ),
                                    "candidate_count": meta.get("candidate_count", 1),
                                    "run_fingerprint": fingerprint,
                                }
                            )
                _write_json(
                    partial,
                    {"run_fingerprint": fingerprint, "manifest_entry": asdict(entry), "rows": rows},
                )
                print(
                    f"{dataset_id} {index + 1}/{args.limit_per_dataset}: "
                    f"{len(rows)} rows, elapsed {time.perf_counter() - started:.1f}s",
                    flush=True,
                )

    records = []
    fingerprints: set[str] = set()
    for path in partial_paths:
        saved = json.loads(path.read_text(encoding="utf-8"))
        fingerprints.add(saved["run_fingerprint"])
        records.extend(saved["rows"])
    keys = {(r["dataset"], r["image_id"], r["model"], r["angle"], r["boundary"]) for r in records}
    if len(fingerprints) != 1 or len(records) != expected or len(keys) != expected:
        raise RuntimeError("result fingerprint/unique-key completeness check failed")
    _write_csv(output / "all_records.csv", records)
    analysis = summarize(
        records, iterations=int(config["suite"]["bootstrap_iterations"]), seed=seed
    )
    analysis.update(
        {
            "complete": True,
            "records": len(records),
            "expected_records": expected,
            "image_units": len(protocol["datasets"]) * args.limit_per_dataset,
            "run_fingerprint": fingerprints.pop(),
            "interpretation": config["suite"]["interpretation"],
            "results_sha256": sha256(output / "all_records.csv"),
        }
    )
    _write_json(output / "analysis.json", analysis)
    print(json.dumps(analysis, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
