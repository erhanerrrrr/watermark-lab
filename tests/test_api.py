from __future__ import annotations

import io

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient
from PIL import Image

from watermark_lab.api.app import app


def _image_bytes() -> bytes:
    image = Image.new("RGB", (256, 256), color=(90, 130, 170))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def test_health_and_models() -> None:
    client = TestClient(app)
    assert client.get("/api/health").json()["status"] == "ok"
    models = client.get("/api/models").json()
    assert any(item["id"] == "dwt_dct" for item in models)


def test_single_lsb_experiment_returns_real_metrics() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/experiments/single",
        files={"image": ("test.png", _image_bytes(), "image/png")},
        data={
            "model": "lsb_reference",
            "message": "watermark-lab",
            "strength": "2.0",
            "attack": "none",
            "attack_parameter": "0",
            "device": "cpu",
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["model"] == "lsb_reference"
    assert result["detected"] is True
    assert result["bit_accuracy"] == 1.0
    assert result["ber"] == 0.0
    assert 0.0 <= result["embed_ssim"] <= 1.0
    assert result["embedded_image_data_url"].startswith("data:image/png;base64,")
