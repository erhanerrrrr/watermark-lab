from __future__ import annotations

import base64
import io
import json
from typing import Any

import numpy as np
import pytest
from PIL import Image

from watermark_lab.api.trustmark_worker import (
    TrustMarkWorker,
    image_from_png,
    image_to_png,
    serve,
)
from watermark_lab.models.trustmark_adapter import TrustMarkQModel


class FakeBackend:
    def __init__(self) -> None:
        self.payload = ""
        self.strengths: list[float] = []

    def schemaCapacity(self) -> int:
        return 61

    def encode(self, image: Image.Image, payload: str, **options: Any) -> Image.Image:
        print("backend encode diagnostic")
        self.payload = payload
        self.strengths.append(options["WM_STRENGTH"])
        assert options["MODE"] == "binary"
        return image.copy()

    def decode(self, image: Image.Image, **options: Any) -> tuple[str, bool, int]:
        print("backend decode diagnostic")
        assert image.mode == "RGB"
        assert options == {"MODE": "binary", "DETECTFIRST": False, "ROTATION": False}
        return self.payload + "0" * (61 - len(self.payload)), True, 1


def _worker() -> tuple[TrustMarkWorker, FakeBackend, list[float]]:
    backend = FakeBackend()
    loads: list[float] = []

    def factory(*, strength: float) -> TrustMarkQModel:
        print("model loading diagnostic")
        loads.append(strength)
        return TrustMarkQModel(strength=strength, backend=backend)

    def health() -> dict[str, Any]:
        print("health diagnostic")
        return {"ready": True, "protocol_version": 1, "model": "trustmark_q"}

    return TrustMarkWorker(model_factory=factory, health_probe=health), backend, loads


def _run(
    worker: TrustMarkWorker, requests: list[Any], **options: Any
) -> tuple[list[dict[str, Any]], str]:
    incoming = io.StringIO("".join(json.dumps(request) + "\n" for request in requests))
    outgoing = io.StringIO()
    diagnostics = io.StringIO()
    serve(incoming, outgoing, worker=worker, diagnostics=diagnostics, **options)
    return [json.loads(line) for line in outgoing.getvalue().splitlines()], diagnostics.getvalue()


def _image() -> np.ndarray:
    return np.random.default_rng(38).integers(0, 256, (128, 160, 3), dtype=np.uint8)


def test_worker_roundtrip_retains_pixels_bits_and_single_model_across_strengths() -> None:
    worker, backend, loads = _worker()
    image = _image()
    payload = image_to_png(image)
    bits = [0, 1] * 16
    responses, diagnostics = _run(
        worker,
        [
            {"id": 1, "op": "health"},
            {"id": "encode-1", "op": "encode", "image_png": payload, "bits": bits},
            {"id": 3, "op": "decode", "image_png": payload},
            {"id": 4, "op": "encode", "image_png": payload, "bits": bits, "strength": 0.8},
            {"id": 5, "op": "health"},
        ],
    )
    assert all(response["ok"] for response in responses)
    assert [response["id"] for response in responses] == [1, "encode-1", 3, 4, 5]
    assert not responses[0]["result"]["model_loaded"]
    assert responses[-1]["result"]["model_loaded"]
    assert loads == [1.0]
    assert backend.strengths == [1.0, 0.8]
    assert responses[3]["result"]["metadata"]["strength"] == 0.8
    assert np.array_equal(image_from_png(responses[1]["result"]["image_png"]), image)
    decoded = responses[2]["result"]
    assert decoded["message"] == bits
    assert decoded["detected"] is True
    assert decoded["confidence"] == 1.0
    assert "not a probability" in decoded["metadata"]["confidence_note"]
    assert "model loading diagnostic" in diagnostics
    assert "backend encode diagnostic" in diagnostics
    assert "backend decode diagnostic" in diagnostics
    assert "health diagnostic" in diagnostics


@pytest.mark.parametrize(
    "bad_request",
    [
        [],
        {"op": "health"},
        {"id": True, "op": "health"},
        {"id": "", "op": "health"},
        {"id": "x" * 129, "op": "health"},
        {"id": 1, "op": "unknown"},
        {"id": 1, "op": []},
        {"id": 1, "op": {}},
        {"id": 1, "op": "decode", "image_png": "invalid base64"},
        {"id": 1, "op": "decode", "image_png": base64.b64encode(b"not PNG").decode()},
        {"id": 1, "op": "decode", "strength": 0},
        {"id": 1, "op": "decode", "strength": 1001},
        {"id": 1, "op": "decode", "strength": 10**400},
        {"id": 1, "op": "decode", "strength": "1"},
        {"id": 1, "op": "decode", "strength": True},
        {"id": 1, "op": "decode", "strength": float("nan")},
        {"id": 1, "op": "decode", "strength": float("inf")},
        {"id": 1, "op": "encode", "bits": [0, 1]},
        {"id": 1, "op": "encode", "bits": "01" * 16},
        {"id": 1, "op": "encode", "bits": [0, 256] * 16},
        {"id": 1, "op": "encode", "bits": [0.0, 1.0] * 16},
        {"id": 1, "op": "encode", "bits": [False, True] * 16},
    ],
)
def test_bad_request_does_not_load_model_or_poison_next_request(bad_request: Any) -> None:
    worker, _, loads = _worker()
    responses, _ = _run(worker, [bad_request, {"id": "next", "op": "health"}])
    assert responses[0]["ok"] is False
    assert responses[0]["error"]["code"] == "invalid_request"
    assert responses[1]["ok"] is True
    assert responses[1]["id"] == "next"
    assert loads == []


def test_worker_rejects_jpeg_and_small_png_before_loading_model() -> None:
    worker, _, loads = _worker()
    jpeg = io.BytesIO()
    Image.fromarray(_image()).save(jpeg, format="JPEG")
    responses, _ = _run(
        worker,
        [
            {"id": 1, "op": "decode", "image_png": base64.b64encode(jpeg.getvalue()).decode()},
            {"id": 2, "op": "decode", "image_png": image_to_png(_image()[:127])},
        ],
    )
    assert all(response["error"]["code"] == "invalid_request" for response in responses)
    assert "requires PNG" in responses[0]["error"]["message"]
    assert "128 x 128" in responses[1]["error"]["message"]
    assert loads == []


def test_worker_rejects_large_pixel_count_before_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("watermark_lab.api.trustmark_worker.MAX_IMAGE_PIXELS", 128 * 128)
    worker, _, loads = _worker()
    responses, _ = _run(worker, [{"id": 1, "op": "decode", "image_png": image_to_png(_image())}])
    assert responses[0]["error"]["code"] == "invalid_request"
    assert loads == []


def test_worker_malformed_and_oversize_lines_keep_request_boundaries() -> None:
    worker, _, loads = _worker()
    incoming = io.StringIO(
        "{broken\n" + "x" * 1000 + '\n{"id": "after", "op": "health"}\n'
    )
    outgoing = io.StringIO()
    serve(incoming, outgoing, worker=worker, diagnostics=io.StringIO(), max_request_chars=64)
    responses = [json.loads(line) for line in outgoing.getvalue().splitlines()]
    assert len(responses) == 3
    assert responses[0]["error"]["code"] == "invalid_request"
    assert responses[1]["error"]["code"] == "invalid_request"
    assert responses[2]["id"] == "after"
    assert responses[2]["ok"] is True
    assert loads == []


def test_worker_recovers_after_failed_model_load() -> None:
    attempts = []

    def factory(*, strength: float) -> TrustMarkQModel:
        attempts.append(strength)
        if len(attempts) == 1:
            raise RuntimeError("temporary model failure")
        return TrustMarkQModel(strength=strength, backend=FakeBackend())

    worker = TrustMarkWorker(model_factory=factory)
    responses, _ = _run(
        worker,
        [{"id": number, "op": "decode", "image_png": image_to_png(_image())} for number in (1, 2)],
    )
    assert responses[0]["error"]["code"] == "inference_error"
    assert "temporary model failure" in responses[0]["error"]["message"]
    assert responses[1]["ok"] is True
    assert attempts == [1.0, 1.0]


def test_health_import_failure_is_structured_and_shutdown_stops_reading() -> None:
    def health() -> dict[str, Any]:
        raise ImportError("TrustMark unavailable")

    worker = TrustMarkWorker(health_probe=health)
    responses, _ = _run(
        worker,
        [{"id": 1, "op": "health"}, {"id": 2, "op": "shutdown"}, {"id": 3, "op": "health"}],
    )
    assert len(responses) == 2
    assert responses[0]["error"]["code"] == "runtime_unavailable"
    assert responses[1] == {"id": 2, "ok": True, "result": {"shutdown": True}}
