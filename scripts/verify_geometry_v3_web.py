"""Exercise live HTTP evidence, paired demos and truly blind Budget-WAM extraction."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def pixels(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as image:
        return np.asarray(image.convert("RGB"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    args = parser.parse_args()
    client = httpx.Client(base_url=args.base_url, timeout=300, trust_env=False)
    evidence = client.get("/api/research/geometry-v3")
    evidence.raise_for_status()
    exported = client.get("/api/research/geometry-v3/export.json")
    exported.raise_for_status()
    assert evidence.json() == exported.json()
    assert "attachment" in exported.headers["content-disposition"]
    catalog = client.get("/api/catalog")
    catalog.raise_for_status()
    assert any(row["id"] == "budget_wam" and row["available"] for row in catalog.json()["models"])
    # Predetermined first calibration image; illustrative demos are not new test measurements.
    sample = json.loads(
        (ROOT / "results/geometry_v3/calibration/traces/coco_000.json").read_text("utf-8")
    )
    image = (ROOT / "results/geometry_v3/calibration/images/coco_000/original.png").read_bytes()
    strengths = json.loads((ROOT / "configs/geometry_v3_strengths.json").read_text("utf-8"))
    message = "".join(str(bit) for bit in sample["expected_message"])
    demos = []
    for model in ("am_wam", "budget_wam"):
        response = client.post(
            "/api/experiments/single",
            files={"image": ("geometry-v3-calibration-demo.png", image, "image/png")},
            data={
                "model": model, "message": message,
                "strength": str(strengths["datasets"]["coco"]["strength"]),
                "attack": "rotate_black", "attack_parameter": "8.3", "device": "cuda",
            },
        )
        response.raise_for_status()
        result = response.json()
        restored = client.get(f"/api/experiments/{result['id']}")
        restored.raise_for_status()
        assert restored.json()["decoded_message"] == result["decoded_message"]
        demos.append(result)
    for name in ("original", "embedded", "attacked"):
        left = client.get(demos[0]["artifacts"][name])
        right = client.get(demos[1]["artifacts"][name])
        left.raise_for_status()
        right.raise_for_status()
        assert np.array_equal(pixels(left.content), pixels(right.content)), name
    attacked = client.get(demos[1]["artifacts"]["attacked"])
    attacked.raise_for_status()
    blind = client.post(
        "/api/watermarks/decode",
        files={"image": ("unknown-to-decoder.png", attacked.content, "image/png")},
        data={"model": "budget_wam", "device": "cuda"},
    )
    blind.raise_for_status()
    decoded = blind.json()
    assert decoded["decoded_message"] == demos[1]["decoded_message"]
    assert decoded["bit_accuracy"] is None and decoded["complete_recovery"] is None
    policy = ROOT / "configs/geometry_v3_selected_policy.json"
    metadata = decoded["metadata"]["decode"]
    assert metadata["policy_sha256"] == hashlib.sha256(policy.read_bytes()).hexdigest()
    assert metadata["candidate_count"] <= metadata["candidate_budget"] == 7
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "evidence_export_matches": True,
        "demo_image": "predetermined calibration/coco_000; not held-out evaluation",
        "demo_images_pixel_identical": True,
        "demos": demos,
        "blind_extraction_without_expected_message": decoded,
    }
    path = ROOT / "artifacts/geometry-v3-web/qa.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), "utf-8")
    print(json.dumps({
        "demos": [
            {key: row[key] for key in ("id", "model", "complete_recovery", "bit_accuracy")}
            for row in demos
        ],
        "blind_candidate_count": metadata["candidate_count"],
        "evidence_export_matches": True,
        "paired_pixels_match": True,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
