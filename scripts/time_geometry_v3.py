"""Measure native sequential inference after test completion, without cache replay."""

from __future__ import annotations

import json
import time
from dataclasses import asdict

import numpy as np
from PIL import Image

from watermark_lab.innovations.budget_geometry import BudgetGeometryConfig, BudgetGeometryDecoder
from watermark_lab.innovations.geometry_sync import GeometrySyncConfig, GeometrySyncDecoder
from watermark_lab.models.wam_adapter import (
    OFFICIAL_WEIGHT_SHA256,
    WamModel,
    default_wam_checkpoint,
)

if __package__ in {None, ""}:
    from analyze_geometry_v3 import full_decision, load_traces, validate_selected_policy
    from collect_geometry_v3 import (
        POLICY,
        ROOT,
        attack_image,
        load_protocol,
        pixel_sha256,
        sha256,
        write_json,
    )
else:
    from .analyze_geometry_v3 import full_decision, load_traces, validate_selected_policy
    from .collect_geometry_v3 import (
        POLICY,
        ROOT,
        attack_image,
        load_protocol,
        pixel_sha256,
        sha256,
        write_json,
    )


def main() -> int:
    import torch

    selected = json.loads(POLICY.read_text("utf-8"))
    validate_selected_policy(selected)
    samples, _ = load_traces("test")
    config = load_protocol()
    policy = BudgetGeometryConfig(**selected["selection"]["policy"])
    if sha256(default_wam_checkpoint()) != OFFICIAL_WEIGHT_SHA256:
        raise RuntimeError("actual checkpoint SHA-256 mismatch")
    model = WamModel(device="cuda")
    methods = {
        "adaptive_identity": model,
        "legacy_am": GeometrySyncDecoder(model),
        "full_best": GeometrySyncDecoder(
            model, config=GeometrySyncConfig(minimum_border_evidence=0.0, fusion_top_k=1)
        ),
        "budget_wam": BudgetGeometryDecoder(model, budget_config=policy),
    }
    names = list(methods)
    warm = np.full((256, 256, 3), 128, dtype=np.uint8)
    for decoder in methods.values():
        decoder.decode(warm)
    rows = []
    count = 0
    for sample in samples:
        if sample["index"] >= config["timing"]["test_images_per_dataset"]:
            continue
        asset = (
            ROOT / "results/geometry_v3/test/images" / f"{sample['dataset']}_{sample['index']:03d}"
        )
        with Image.open(asset / "adaptive.png") as opened:
            embedded = np.ascontiguousarray(np.asarray(opened.convert("RGB")))
        if pixel_sha256(embedded) != sample["adaptive_sha256"]:
            raise RuntimeError("saved embedded pixels differ from test trace")
        for attack in config["attacks"]:
            if attack["id"] not in config["timing"]["attacks"]:
                continue
            attacked = attack_image(embedded, attack, config["suite"]["seed"])
            trace = next(
                row
                for row in sample["records"]
                if row["positive"] and row["attack"] == attack["id"]
            )
            if pixel_sha256(attacked) != trace["attacked_sha256"]:
                raise RuntimeError("timing attack pixels differ from test trace")
            for repeat in range(config["timing"]["repetitions"]):
                order = names if (count + repeat) % 2 == 0 else names[::-1]
                for name in order:
                    torch.cuda.synchronize()
                    torch.cuda.reset_peak_memory_stats()
                    begin = time.perf_counter()
                    decoded = methods[name].decode(attacked)
                    torch.cuda.synchronize()
                    elapsed = 1000 * (time.perf_counter() - begin)
                    if name == "full_best":
                        expected = full_decision(trace, fused=False)[0]
                    elif name == "legacy_am":
                        expected = full_decision(trace, fused=True, gated=True)[0]
                    elif name == "adaptive_identity":
                        expected = trace["evidence"]["identity"].bits()
                    else:
                        from watermark_lab.innovations.budget_geometry import run_budget_policy

                        replay = run_budget_policy(trace["evidence"].__getitem__, policy)
                        expected = replay.selected.bits()
                        if len(replay.visited) != decoded.metadata["candidate_count"]:
                            raise RuntimeError("live/replayed candidate count differs")
                    if not np.array_equal(decoded.message, expected):
                        raise RuntimeError(
                            f"live/replayed message differs: {sample['image_id']}/{name}"
                        )
                    rows.append(
                        {
                            "dataset": sample["dataset"],
                            "image_id": sample["image_id"],
                            "attack": attack["id"],
                            "repeat": repeat,
                            "method": name,
                            "decode_ms": elapsed,
                            "candidates": decoded.metadata.get("candidate_count", 1),
                            "peak_cuda_allocated_mb": torch.cuda.max_memory_allocated() / 1024**2,
                        }
                    )
            count += 1
            print(f"timing {count}: {sample['dataset']}/{attack['id']}", flush=True)
    summary = []
    for name in names:
        group = [row for row in rows if row["method"] == name]
        times = np.asarray([row["decode_ms"] for row in group])
        summary.append(
            {
                "method": name,
                "runs": len(group),
                "mean_ms": float(times.mean()),
                "p50_ms": float(np.median(times)),
                "p95_ms": float(np.quantile(times, 0.95)),
                "mean_candidates": float(np.mean([row["candidates"] for row in group])),
                "peak_cuda_allocated_mb": max(row["peak_cuda_allocated_mb"] for row in group),
            }
        )
    result = {
        "policy": asdict(policy),
        "policy_sha256": sha256(POLICY),
        "measured_conditions": count,
        "image_units": len({(row["dataset"], row["image_id"]) for row in rows}),
        "repetitions": config["timing"]["repetitions"],
        "device": torch.cuda.get_device_name(),
        "torch_threads": torch.get_num_threads(),
        "methods": summary,
        "rows": rows,
        "live_replay_bitwise_verified": True,
        "note": "Native inference with warm-up, alternating method order and synchronized CUDA.",
    }
    write_json(ROOT / "results/geometry_v3/test/timing.json", result)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
