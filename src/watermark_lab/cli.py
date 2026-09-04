from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

from watermark_lab.attacks.basic import AttackSpec
from watermark_lab.attacks.protocol import load_attack_protocol
from watermark_lab.core.registry import create_model, list_model_specs
from watermark_lab.datasets.manifest import (
    build_manifest,
    iter_manifest_images,
    write_manifest,
)
from watermark_lab.experiments.runner import run_experiment, write_results_csv
from watermark_lab.models.trustmark_adapter import trustmark_package_available
from watermark_lab.models.wam_adapter import wam_assets_available, wam_runtime_available


def _configure_windows_stdio() -> None:
    """Keep Chinese CLI output readable in legacy Windows terminals and pipes."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def _synthetic_image(size: int = 256) -> np.ndarray:
    axis = np.linspace(0, 255, size, dtype=np.uint8)
    x_grid, y_grid = np.meshgrid(axis, axis)
    blue = ((x_grid.astype(np.uint16) + y_grid.astype(np.uint16)) // 2).astype(np.uint8)
    return np.stack((x_grid, y_grid, blue), axis=2)


def _status() -> int:
    print("Model status")
    for spec in list_model_specs():
        state = "ready" if spec.ready else "planned"
        if spec.name == "trustmark_q" and not trustmark_package_available():
            state = "adapter"
        if spec.name in {"wam", "am_wam"} and not (
            wam_runtime_available() and wam_assets_available()
        ):
            state = "adapter"
        print(f"- {spec.name:16} {state:7} milestone={spec.stage:4} role={spec.role}")
    if not trustmark_package_available():
        print('TrustMark runtime: missing (install with pip install -e ".[trustmark]")')
    if not wam_runtime_available():
        print("WAM runtime: missing (run scripts\\setup_wam_windows.ps1)")
    elif not wam_assets_available():
        print("WAM source/checkpoint: missing (run scripts\\setup_wam_windows.ps1)")
    return 0


def _self_check(model_name: str, output_dir: str | None) -> int:
    model = create_model(model_name)
    attacks = (
        AttackSpec("identity"),
        AttackSpec("jpeg", {"quality": 80}),
        AttackSpec("gaussian_noise", {"sigma": 0.01}),
    )
    records = run_experiment(model, [("synthetic-gradient", _synthetic_image())], attacks)
    print(json.dumps([asdict(record) for record in records], ensure_ascii=False, indent=2))

    identity = next(record for record in records if record.attack == "identity")
    if not identity.detected or not identity.complete_recovery:
        raise RuntimeError("self-check failed: identity round-trip did not recover the message")

    if output_dir:
        destination = Path(output_dir) / "self_check.csv"
        write_results_csv(records, destination)
        print(f"saved: {destination.resolve()}")
    print("self-check: PASS")
    return 0


def _build_manifest(args: argparse.Namespace) -> int:
    entries = build_manifest(
        args.root,
        dataset=args.dataset,
        split=args.split,
        limit=args.limit,
    )
    destination = write_manifest(entries, args.output)
    print(f"manifest: {destination.resolve()}")
    print(f"samples: {len(entries)}")
    return 0


def _protocol_status(config_path: str) -> int:
    protocol = load_attack_protocol(config_path)
    counts: dict[str, int] = {}
    for case in protocol.cases:
        counts[case.category] = counts.get(case.category, 0) + 1
    print(f"protocol: {protocol.protocol_id} v{protocol.version}")
    print(f"seed: {protocol.seed}")
    print(f"cases: {len(protocol.cases)}")
    for category, count in sorted(counts.items()):
        print(f"- {category}: {count}")
    return 0


def _run_manifest(args: argparse.Namespace) -> int:
    model_kwargs = {"strength": args.strength} if args.strength is not None else {}
    model = create_model(args.model, **model_kwargs)
    protocol = load_attack_protocol(args.attacks_config)
    cases = protocol.select(args.categories)
    if not cases:
        raise ValueError("no attack cases match the selected categories")
    samples = (
        (sample.sample_id, sample.image)
        for sample in iter_manifest_images(
            args.manifest,
            args.dataset_root,
            verify_sha256=args.verify_sha256,
        )
    )
    records = run_experiment(model, samples, cases, seed=protocol.seed)
    destination = write_results_csv(records, args.output)
    print(f"model: {model.name}")
    print(f"protocol: {protocol.protocol_id} v{protocol.version}")
    print(f"records: {len(records)}")
    print(f"results: {destination.resolve()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Watermark Lab command line")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="show implementation status for all planned models")
    check = subparsers.add_parser("self-check", help="run a small end-to-end pipeline check")
    check.add_argument(
        "--model",
        choices=("lsb_reference", "dwt_dct", "trustmark_q", "wam", "am_wam"),
        default="lsb_reference",
        help="lightweight model to validate",
    )
    check.add_argument("--output-dir", help="optional directory for the CSV result")

    manifest = subparsers.add_parser(
        "build-manifest", help="create a deterministic dataset manifest"
    )
    manifest.add_argument("--dataset", required=True, help="dataset name")
    manifest.add_argument("--split", required=True, help="dataset split")
    manifest.add_argument("--root", required=True, help="image folder")
    manifest.add_argument("--output", required=True, help="output CSV path")
    manifest.add_argument("--limit", type=int, help="optional deterministic sample limit")

    protocol = subparsers.add_parser(
        "protocol-status", help="validate and summarize an attack protocol"
    )
    protocol.add_argument("--config", default="configs/attacks.yaml")

    experiment = subparsers.add_parser(
        "run-manifest", help="run one model on a fixed manifest and attack protocol"
    )
    experiment.add_argument(
        "--model", required=True, choices=("dwt_dct", "trustmark_q", "wam", "am_wam")
    )
    experiment.add_argument("--strength", type=float, help="fixed embedding strength")
    experiment.add_argument("--manifest", required=True)
    experiment.add_argument("--dataset-root", required=True)
    experiment.add_argument("--attacks-config", default="configs/attacks.yaml")
    experiment.add_argument(
        "--categories",
        nargs="+",
        choices=("control", "single", "compound"),
        help="default: all categories",
    )
    experiment.add_argument("--verify-sha256", action="store_true")
    experiment.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_windows_stdio()
    args = build_parser().parse_args(argv)
    if args.command == "status":
        return _status()
    if args.command == "self-check":
        return _self_check(args.model, args.output_dir)
    if args.command == "build-manifest":
        return _build_manifest(args)
    if args.command == "protocol-status":
        return _protocol_status(args.config)
    if args.command == "run-manifest":
        return _run_manifest(args)
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
