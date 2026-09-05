"""Collect reusable blind-candidate traces with project-disjoint calibration/test splits."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from watermark_lab.attacks.basic import AttackSpec, apply_attack
from watermark_lab.datasets.manifest import read_manifest
from watermark_lab.innovations.budget_geometry import (
    CANDIDATES,
    CandidateEvidence,
    transform_candidate,
)
from watermark_lab.innovations.content_adaptive import AdaptiveStrengthConfig
from watermark_lab.innovations.geometry_sync import GeometrySyncDecoder, geometry_border_evidence
from watermark_lab.metrics.image_quality import psnr
from watermark_lab.models.am_wam import AmWamModel
from watermark_lab.models.wam_adapter import (
    OFFICIAL_WEIGHT_SHA256,
    WamModel,
    default_wam_checkpoint,
)

if __package__ in {None, ""}:
    from run_border_stress import pixel_sha256, rotate_boundary, sha256
else:
    from .run_border_stress import pixel_sha256, rotate_boundary, sha256

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "configs/geometry_v3_protocol.yaml"
POLICY = ROOT / "configs/geometry_v3_selected_policy.json"
STRENGTHS = ROOT / "configs/geometry_v3_strengths.json"
SOURCES = ("coco", "div2k", "diffusiondb", "w_bench")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), "utf-8")
    temporary.replace(path)


def load_protocol() -> dict:
    return yaml.safe_load(PROTOCOL.read_text("utf-8"))


def dataset_assets(split: str, config: dict):
    if split == "development":
        debug = yaml.safe_load((ROOT / "configs/debug_suite.yaml").read_text("utf-8"))
        for source, dataset in zip(SOURCES, debug["datasets"], strict=True):
            manifest = ROOT / dataset["manifest"]
            yield (
                source,
                manifest,
                ROOT / dataset["root"],
                read_manifest(manifest)[: config["suite"]["development_per_dataset"]],
            )
    else:
        for source in SOURCES:
            manifest = ROOT / f"data/manifests/geometry_v3_{source}_{split}.csv"
            entries = read_manifest(manifest)
            if len(entries) != config["suite"][f"{split}_per_dataset"]:
                raise RuntimeError(f"incomplete {split} manifest: {source}")
            yield source, manifest, ROOT / "data/raw/geometry_v3" / source, entries


def verify_splits() -> None:
    prior = {
        entry.sha256
        for path in (ROOT / "data/manifests").glob("*.csv")
        if not path.name.startswith("geometry_v3_")
        for entry in read_manifest(path)
    }
    seen = set(prior)
    for split in ("calibration", "test"):
        for source, _, _, entries in dataset_assets(split, load_protocol()):
            hashes = {entry.sha256 for entry in entries}
            if len(hashes) != len(entries) or hashes & seen:
                raise RuntimeError(f"historical/cross-split duplicate images: {source}/{split}")
            seen.update(hashes)


def image_array(path: Path, maximum_side: int, expected_hash: str) -> np.ndarray:
    if sha256(path) != expected_hash:
        raise RuntimeError(f"source image hash changed: {path}")
    with Image.open(path) as opened:
        image = opened.convert("RGB")
        if max(image.size) > maximum_side:
            ratio = maximum_side / max(image.size)
            image = image.resize(
                tuple(max(1, round(side * ratio)) for side in image.size), Image.Resampling.LANCZOS
            )
        return np.ascontiguousarray(np.asarray(image))


def sample_message(source: str, image_id: str, seed: int) -> np.ndarray:
    derived = int.from_bytes(
        hashlib.sha256(f"{seed}:{source}:{image_id}".encode()).digest()[:8], "big"
    )
    return np.random.default_rng(derived).integers(0, 2, 32, dtype=np.uint8)


def attack_image(image: np.ndarray, spec: dict, seed: int) -> np.ndarray:
    if "boundary" in spec:
        result = rotate_boundary(image, spec["angle"], spec["boundary"])
        if "jpeg" in spec:
            result = apply_attack(result, AttackSpec("jpeg", {"quality": spec["jpeg"]}))
        return result
    parameters = {key: value for key, value in spec.items() if key not in {"id", "family", "name"}}
    return apply_attack(image, AttackSpec(spec["name"], parameters), np.random.default_rng(seed))


def _runtime_sources() -> list[Path]:
    return [
        Path(__file__).resolve(),
        PROTOCOL,
        ROOT / "src/watermark_lab/innovations/geometry_sync.py",
        ROOT / "src/watermark_lab/innovations/budget_geometry.py",
        ROOT / "src/watermark_lab/innovations/content_adaptive.py",
        ROOT / "src/watermark_lab/models/wam_adapter.py",
        ROOT / "src/watermark_lab/models/am_wam.py",
        ROOT / "src/watermark_lab/attacks/basic.py",
        ROOT / "configs/m4_ablation.yaml",
        ROOT / "scripts/run_border_stress.py",
    ]


def calibrate_strengths(model: WamModel, config: dict) -> None:
    if STRENGTHS.exists():
        saved = json.loads(STRENGTHS.read_text("utf-8"))
        if saved["protocol_sha256"] != sha256(PROTOCOL):
            raise RuntimeError("strength calibration protocol changed")
        return
    result = {"protocol_sha256": sha256(PROTOCOL), "source_split": "calibration", "datasets": {}}
    for source, manifest, root, entries in dataset_assets("calibration", config):
        samples = [
            (
                image_array(
                    root / entry.relative_path, config["suite"]["max_input_side"], entry.sha256
                ),
                sample_message(source, entry.sample_id, config["suite"]["seed"]),
            )
            for entry in entries
        ]
        strength = config["embedding"]["fixed_strength"]
        history = []
        for step in range(3):
            model.strength = strength
            qualities = [
                psnr(image, model.encode(image, message).image) for image, message in samples
            ]
            history.append({"strength": strength, "mean_psnr_db": float(np.mean(qualities))})
            if step < 2:
                strength *= 10 ** ((np.mean(qualities) - 40.0) / 20)
        result["datasets"][source] = {
            "strength": strength,
            "history": history,
            "manifest_sha256": sha256(manifest),
        }
        print(f"strength {source}: {strength:.4f}, mean PSNR {np.mean(qualities):.3f}", flush=True)
    write_json(STRENGTHS, result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("development", "calibration", "test"), required=True)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    config = load_protocol()
    verify_splits()
    if args.split == "test" and not POLICY.exists():
        raise RuntimeError("freeze a calibration-selected policy before inspecting test results")
    if sha256(default_wam_checkpoint()) != OFFICIAL_WEIGHT_SHA256:
        raise RuntimeError("actual checkpoint hash mismatch")
    model = WamModel(device=args.device)
    calibrate_strengths(model, config)
    strengths = json.loads(STRENGTHS.read_text("utf-8"))["datasets"]
    m4 = yaml.safe_load((ROOT / config["embedding"]["adaptive_config"]).read_text("utf-8"))
    adaptive = AmWamModel(
        device=args.device,
        backend=model._backend,
        adaptive_config=AdaptiveStrengthConfig(**m4["adaptive_strength"]),
    )
    scorer = GeometrySyncDecoder(model)
    output = ROOT / "results/geometry_v3" / args.split
    sources = _runtime_sources() + [STRENGTHS]
    sources += [manifest for _, manifest, _, _ in dataset_assets(args.split, config)]
    if args.split == "test":
        sources.append(POLICY)
    hashes = {path.relative_to(ROOT).as_posix(): sha256(path) for path in sources}
    fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    snapshot = output / "provenance.json"
    if snapshot.exists() and json.loads(snapshot.read_text("utf-8"))["fingerprint"] != fingerprint:
        raise RuntimeError("trace source/config changed; use a new version, never mix checkpoints")
    import torch

    write_json(
        snapshot,
        {
            "fingerprint": fingerprint,
            "source_sha256": hashes,
            "split": args.split,
            "python": sys.version,
            "torch": torch.__version__,
            "device": args.device,
            "gpu": torch.cuda.get_device_name() if torch.cuda.is_available() else None,
            "checkpoint_sha256": OFFICIAL_WEIGHT_SHA256,
        },
    )
    source_dir = output / "source_snapshot"
    source_dir.mkdir(parents=True, exist_ok=True)
    for path in _runtime_sources():
        (source_dir / path.name).write_bytes(path.read_bytes())
    # Warm up before branch timings; final claims use the independent online timing runner.
    model.decode(np.full((256, 256, 3), 128, dtype=np.uint8))
    started = time.perf_counter()
    expected_files = []
    for source, _, root, entries in dataset_assets(args.split, config):
        model.strength = adaptive.strength = strengths[source]["strength"]
        for index, entry in enumerate(entries):
            path = output / "traces" / f"{source}_{index:03d}.json"
            expected_files.append(path)
            if path.exists():
                if json.loads(path.read_text("utf-8"))["fingerprint"] != fingerprint:
                    raise RuntimeError("trace fingerprint mismatch")
                print(f"reuse {args.split}/{source}/{index}", flush=True)
                continue
            image = image_array(
                root / entry.relative_path, config["suite"]["max_input_side"], entry.sha256
            )
            message = sample_message(source, entry.sample_id, config["suite"]["seed"])
            fixed = model.encode(image, message).image
            encoded = adaptive.encode(image, message).image
            assets = output / "images" / f"{source}_{index:03d}"
            assets.mkdir(parents=True, exist_ok=True)
            for label, array in (("original", image), ("fixed", fixed), ("adaptive", encoded)):
                Image.fromarray(array).save(assets / f"{label}.png")
            records = []
            for positive in (True, False):
                for attack in config["attacks"]:
                    if not positive and attack["id"] not in config["negative_attacks"]:
                        continue
                    attacked = attack_image(
                        encoded if positive else image, attack, config["suite"]["seed"]
                    )
                    candidates = []
                    for name in CANDIDATES:
                        begin = time.perf_counter()
                        branch = scorer._score(name, transform_candidate(attacked, name))
                        elapsed = 1000 * (time.perf_counter() - begin)
                        candidates.append(
                            {**asdict(CandidateEvidence.from_branch(branch)), "elapsed_ms": elapsed}
                        )
                    fixed_decoded = (
                        model.decode(attack_image(fixed, attack, config["suite"]["seed"]))
                        if positive
                        else None
                    )
                    records.append(
                        {
                            "positive": positive,
                            "attack": attack["id"],
                            "family": attack["family"],
                            "attacked_sha256": pixel_sha256(attacked),
                            "border_evidence": geometry_border_evidence(attacked),
                            "candidates": candidates,
                            "fixed_message": fixed_decoded.message.tolist() if positive else None,
                            "fixed_detection_fraction": fixed_decoded.metadata["detected_fraction"]
                            if positive
                            else candidates[0]["selected_fraction"],
                        }
                    )
            write_json(
                path,
                {
                    "fingerprint": fingerprint,
                    "dataset": source,
                    "index": index,
                    "image_id": entry.sample_id,
                    "source_sha256": entry.sha256,
                    "input_shape": image.shape,
                    "input_sha256": pixel_sha256(image),
                    "adaptive_sha256": pixel_sha256(encoded),
                    "expected_message": message.tolist(),
                    "fixed_psnr_db": psnr(image, fixed),
                    "adaptive_psnr_db": psnr(image, encoded),
                    "records": records,
                },
            )
            print(
                f"{args.split} {source} {index + 1}/{len(entries)}: "
                f"{len(records)} traces; elapsed {time.perf_counter() - started:.1f}s",
                flush=True,
            )
    expected_records = sum(
        len(json.loads(path.read_text("utf-8"))["records"]) for path in expected_files
    )
    write_json(
        output / "collection_status.json",
        {
            "complete": True,
            "images": len(expected_files),
            "records": expected_records,
            "candidates_per_record": len(CANDIDATES),
            "fingerprint": fingerprint,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
