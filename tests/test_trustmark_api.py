from __future__ import annotations

import io
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient
from PIL import Image

from watermark_lab.api import service
from watermark_lab.api.app import create_app


class FakeWorker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.message = [0] * 32
        self.closed = False
        self.failed = False
        self.runtime_info = {
            "execution_backend": "isolated", "device": "cpu", "worker_pid": 1234,
        }

    def ensure_ready(self) -> dict:
        return {"ready": True, "device": "cpu"}

    def availability(self) -> tuple[bool, str | None]:
        return True, None

    def request(self, operation: str, **values) -> dict:
        self.calls.append((operation, values))
        if self.failed:
            raise RuntimeError("TrustMark test worker unavailable")
        if operation == "encode":
            self.message = values["bits"]
            return {"image_png": values["image_png"], "metadata": {"strength": values["strength"]}}
        return {
            "message": self.message, "detected": True, "confidence": 1.0, "metadata": {},
        }

    def close(self) -> None:
        self.closed = True


def _png() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (128, 160), color=(90, 120, 150)).save(stream, format="PNG")
    return stream.getvalue()


def test_api_dispatches_all_trustmark_operations_without_local_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_factory = service.create_model

    def local_factory(name, **kwargs):
        assert name != "trustmark_q", "TrustMark must never load in the main process"
        return original_factory(name, **kwargs)

    monkeypatch.setattr(service, "create_model", local_factory)
    monkeypatch.setenv("WATERMARK_LAB_TRUSTMARK_MODE", "isolated")
    worker = FakeWorker()
    application = create_app(storage_dir=tmp_path / "store", trustmark_worker=worker)
    with TestClient(application) as client:
        catalog = client.get("/api/catalog").json()
        model = next(row for row in catalog["models"] if row["id"] == "trustmark_q")
        assert model["available"] is True
        assert model["execution_backend"] == "isolated"
        assert model["runtime_label"] == "TrustMark 独立进程 · CPU"
        incompatible = client.post(
            "/api/watermarks/embed", files={"image": ("input.png", _png(), "image/png")},
            data={"model": "trustmark_q", "device": "cuda", "message": "wrong device"},
        )
        assert incompatible.status_code == 422
        assert worker.calls == []

        embedded = client.post(
            "/api/watermarks/embed", files={"image": ("input.png", _png(), "image/png")},
            data={"model": "trustmark_q", "strength": "1", "message": "isolated payload"},
        )
        assert embedded.status_code == 200, embedded.text
        embedded_payload = embedded.json()
        encoded_png = client.get(embedded_payload["embedded_image_url"]).content
        decoded = client.post(
            "/api/watermarks/decode",
            files={"image": ("watermarked.png", encoded_png, "image/png")},
            data={"model": "trustmark_q", "strength": "1"},
        )
        assert decoded.status_code == 200, decoded.text
        assert decoded.json()["decoded_message"] == embedded_payload["expected_message"]
        assert decoded.json()["bit_accuracy"] is None
        assert decoded.json()["metadata"]["device"] == "cpu"
        assert decoded.json()["metadata"]["requested_device"] == "auto"
        assert decoded.json()["metadata"]["decode"]["runtime"]["execution_backend"] == "isolated"
        assert set(worker.calls[1][1]) == {"image_png", "strength"}

        experiment = client.post(
            "/api/experiments/single",
            files={"image": ("input.png", _png(), "image/png")},
            data={"model": "trustmark_q", "strength": "1", "message": "saved experiment"},
        )
        assert experiment.status_code == 200, experiment.text
        record = experiment.json()
        assert record["complete_recovery"] is True
        assert record["metadata"]["embed"]["runtime"]["worker_pid"] == 1234
        assert client.get(f"/api/experiments/{record['id']}").status_code == 200
        assert record["id"] in client.get("/api/experiments/export.csv").text

        worker.failed = True
        failed = client.post(
            "/api/experiments/single",
            files={"image": ("input.png", _png(), "image/png")},
            data={"model": "trustmark_q", "message": "fails"},
        )
        assert failed.status_code == 503
        assert client.get("/api/health").json()["persisted_experiments"] == 1
        local = client.post(
            "/api/experiments/single",
            files={"image": ("input.png", _png(), "image/png")},
            data={"model": "lsb_reference", "message": "local still works"},
        )
        assert local.status_code == 200
    assert worker.closed
