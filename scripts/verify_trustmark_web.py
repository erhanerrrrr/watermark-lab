"""Exercise the isolated TrustMark runtime and all six models through one live API."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import time
from pathlib import Path

import httpx
from PIL import Image


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--output", type=Path, default=Path("artifacts/trustmark-web"))
    args = parser.parse_args()
    with Image.open(args.image) as source:
        image = source.convert("RGB")
        image.thumbnail((512, 512), Image.Resampling.LANCZOS)
        if min(image.size) < 128:
            raise ValueError("QA image must remain at least 128 x 128")
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        payload = stream.getvalue()
    message = "00110101011000110101001110100101"
    args.output.mkdir(parents=True, exist_ok=True)
    report: dict = {"input_sha256": hashlib.sha256(payload).hexdigest(), "experiments": []}

    with httpx.Client(base_url=args.base_url, timeout=240) as client:
        models_response = client.get("/api/models")
        models_response.raise_for_status()
        models = models_response.json()
        assert len(models) == 6 and all(model["available"] for model in models), models
        trustmark = next(model for model in models if model["id"] == "trustmark_q")
        assert trustmark["execution_backend"] == "isolated", trustmark
        report["models"] = [
            {key: model[key] for key in ("id", "available", "execution_backend", "runtime_label")}
            for model in models
        ]

        def post(path: str, image_bytes: bytes, data: dict) -> dict:
            response = client.post(
                path, files={"image": ("QA-isolated-runtime.png", image_bytes, "image/png")},
                data=data,
            )
            response.raise_for_status()
            return response.json()

        embedded = post("/api/watermarks/embed", payload, {
            "model": "trustmark_q", "message": message, "strength": 1, "device": "auto",
        })
        encoded_response = client.get(embedded["embedded_image_url"])
        encoded_response.raise_for_status()
        encoded_png = encoded_response.content
        (args.output / "trustmark-embedded.png").write_bytes(encoded_png)
        decoded = post("/api/watermarks/decode", encoded_png, {
            "model": "trustmark_q", "strength": 1, "device": "auto",
        })
        assert decoded["decoded_message"] == embedded["expected_message"] == message
        assert decoded["detected"] is True
        assert decoded["bit_accuracy"] is decoded["ber"] is decoded["complete_recovery"] is None
        worker_pid = embedded["metadata"]["worker_pid"]
        assert decoded["metadata"]["worker_pid"] == worker_pid
        report["blind_round_trip"] = {
            "embed_operation": embedded["id"], "decoded_message": decoded["decoded_message"],
            "evaluation_fields_null": True, "runtime": decoded["metadata"],
        }
        print("TrustMark blind embed/decode passed; worker PID", worker_pid, flush=True)

        for model in models:
            started = time.perf_counter()
            result = post("/api/experiments/single", payload, {
                "model": model["id"], "message": message,
                "strength": model["default_strength"], "attack": "none", "device": "auto",
            })
            assert result["complete_recovery"] and result["decoded_message"] == message, result
            detail = client.get(f"/api/experiments/{result['id']}")
            detail.raise_for_status()
            assert detail.json()["decoded_message"] == message
            for url in result["artifacts"].values():
                artifact = client.get(url)
                artifact.raise_for_status()
                assert artifact.content.startswith(b"\x89PNG")
            if model["id"] == "trustmark_q":
                assert result["metadata"]["worker_pid"] == worker_pid
            report["experiments"].append({
                "id": result["id"], "model": result["model"],
                "complete_recovery": result["complete_recovery"],
                "bit_accuracy": result["bit_accuracy"], "embed_psnr_db": result["embed_psnr_db"],
                "execution_backend": result["metadata"]["execution_backend"],
                "wall_seconds": time.perf_counter() - started,
            })
            print(model["display_name"], result["id"], "clean recovery passed", flush=True)

        exported = client.get("/api/experiments/export.csv")
        exported.raise_for_status()
        assert all(row["id"] in exported.text for row in report["experiments"])
        report["csv_export_verified"] = True
        report["passed"] = True
        report["note"] = "Live engineering QA on one image; not a new research benchmark."
        (args.output / "qa.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    print(args.output / "qa.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
