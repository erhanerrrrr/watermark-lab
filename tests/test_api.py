from __future__ import annotations

import io
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient
from PIL import Image

from watermark_lab.api.app import create_app


def _image_bytes(size: int = 256) -> bytes:
    image = Image.new("RGB", (size, size), color=(90, 130, 170))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    application = create_app(
        storage_dir=tmp_path / "storage", frontend_dir=tmp_path / "frontend"
    )
    return TestClient(application)


def _post_experiment(client: TestClient) -> dict[str, object]:
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
    assert response.status_code == 200, response.text
    return response.json()


def test_health_catalog_and_models_are_real(client: TestClient) -> None:
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["persisted_experiments"] == 0
    assert health["frontend_available"] is False

    models = client.get("/api/models").json()
    assert any(item["id"] == "dwt_dct" for item in models)
    assert all(item["display_name"] for item in models)

    catalog = client.get("/api/catalog").json()
    assert catalog["formal"]["records"] == 121_440
    assert catalog["formal"]["complete"] is True
    assert len(catalog["datasets"]) == 4
    assert len(catalog["protocol"]["cases"]) == 44
    assert len(catalog["interactive_attacks"]) == 8


def test_single_experiment_persists_artifacts_and_exports(
    client: TestClient, tmp_path: Path
) -> None:
    result = _post_experiment(client)
    assert result["model"] == "lsb_reference"
    assert result["detected"] is True
    assert result["bit_accuracy"] == 1.0
    assert result["ber"] == 0.0
    assert 0.0 <= result["embed_ssim"] <= 1.0

    experiment_id = str(result["id"])
    history = client.get("/api/experiments").json()
    assert [item["id"] for item in history] == [experiment_id]
    assert "artifacts" not in history[0]

    detail = client.get(f"/api/experiments/{experiment_id}").json()
    assert detail["expected_message"] == detail["decoded_message"]
    for url in detail["artifacts"].values():
        artifact = client.get(url)
        assert artifact.status_code == 200
        assert artifact.headers["content-type"] == "image/png"
        assert artifact.content.startswith(b"\x89PNG")

    exported = client.get("/api/experiments/export.csv")
    assert exported.status_code == 200
    assert experiment_id in exported.content.decode("utf-8-sig")

    restarted = TestClient(
        create_app(storage_dir=tmp_path / "storage", frontend_dir=tmp_path / "frontend")
    )
    assert restarted.get("/api/health").json()["persisted_experiments"] == 1
    assert restarted.get(f"/api/experiments/{experiment_id}").status_code == 200


def test_embed_then_decode_round_trip(client: TestClient) -> None:
    embedded = client.post(
        "/api/watermarks/embed",
        files={"image": ("source.png", _image_bytes(), "image/png")},
        data={"model": "lsb_reference", "message": "round-trip", "device": "cpu"},
    )
    assert embedded.status_code == 200, embedded.text
    embedded_result = embedded.json()
    image_response = client.get(embedded_result["embedded_image_url"])
    assert image_response.status_code == 200

    decoded = client.post(
        "/api/watermarks/decode",
        files={"image": ("embedded.png", image_response.content, "image/png")},
        data={
            "model": "lsb_reference",
            "expected_message": "round-trip",
            "device": "cpu",
        },
    )
    assert decoded.status_code == 200, decoded.text
    decoded_result = decoded.json()
    assert decoded_result["detected"] is True
    assert decoded_result["bit_accuracy"] == 1.0
    assert decoded_result["complete_recovery"] is True


def test_input_validation_and_manifest_download(client: TestClient) -> None:
    wrong_type = client.post(
        "/api/experiments/single",
        files={"image": ("not-image.txt", b"hello", "text/plain")},
    )
    assert wrong_type.status_code == 415

    too_small = client.post(
        "/api/experiments/single",
        files={"image": ("small.png", _image_bytes(64), "image/png")},
    )
    assert too_small.status_code == 422

    empty_message = client.post(
        "/api/experiments/single",
        files={"image": ("test.png", _image_bytes(), "image/png")},
        data={"message": "   "},
    )
    assert empty_message.status_code == 422

    manifest = client.get("/api/datasets/coco2017_val/manifest/test")
    assert manifest.status_code == 200
    assert manifest.content.decode("utf-8-sig").startswith("dataset,split")
    assert client.get("/api/datasets/unknown/manifest/test").status_code == 404


def test_built_frontend_is_served_as_a_single_page_app(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    assets = frontend / "assets"
    assets.mkdir(parents=True)
    (frontend / "index.html").write_text(
        "<html><title>Watermark Lab</title></html>", encoding="utf-8"
    )
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")
    client = TestClient(create_app(storage_dir=tmp_path / "storage", frontend_dir=frontend))

    assert client.get("/").status_code == 200
    assert client.get("/results").text.startswith("<html>")
    assert client.get("/assets/app.js").text == "console.log('ok')"
    assert client.get("/api").status_code == 404
    assert client.get("/api/not-a-route").status_code == 404
