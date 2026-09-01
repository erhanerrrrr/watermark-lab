from __future__ import annotations

import numpy as np

from watermark_lab.models.wam_adapter import WamModel, WamSpatialPrediction


class FakeWamBackend:
    device_name = "cpu-test"
    checkpoint_sha256 = "fixture"

    def __init__(self, *, detected: bool = True) -> None:
        self.detected = detected
        self.message = np.zeros(32, dtype=np.uint8)
        self.strength = 0.0

    def encode(
        self,
        image: np.ndarray,
        message: np.ndarray,
        *,
        strength: float,
    ) -> np.ndarray:
        self.message = message.copy()
        self.strength = strength
        return image.copy()

    def predict(self, image: np.ndarray) -> WamSpatialPrediction:
        detection_value = 0.9 if self.detected else 0.1
        detection = np.full((8, 8), detection_value, dtype=np.float32)
        bit_logits = np.empty((32, 8, 8), dtype=np.float32)
        for index, bit in enumerate(self.message):
            bit_logits[index] = 1.0 if bit else -1.0
        return WamSpatialPrediction(detection, bit_logits)


def test_wam_adapter_round_trip_and_localization() -> None:
    backend = FakeWamBackend()
    model = WamModel(strength=1.25, backend=backend)
    image = np.full((96, 128, 3), 127, dtype=np.uint8)
    message = np.asarray([0, 1] * 16, dtype=np.uint8)

    embedded = model.encode(image, message)
    decoded = model.decode(embedded.image)

    assert backend.strength == 1.25
    assert decoded.detected
    assert np.array_equal(decoded.message, message)
    assert decoded.localization is not None
    assert decoded.localization.shape == (8, 8)
    assert decoded.metadata["detected_fraction"] == 1.0
    assert embedded.metadata["variant"] == "wam_mit"


def test_wam_adapter_returns_zero_message_without_detected_pixels() -> None:
    backend = FakeWamBackend(detected=False)
    model = WamModel(backend=backend)
    image = np.zeros((64, 64, 3), dtype=np.uint8)

    decoded = model.decode(image)

    assert not decoded.detected
    assert not decoded.message.any()
    assert decoded.metadata["detected_fraction"] == 0.0


def test_wam_adapter_rejects_invalid_spatial_shapes() -> None:
    class InvalidBackend(FakeWamBackend):
        def predict(self, image: np.ndarray) -> WamSpatialPrediction:
            return WamSpatialPrediction(
                np.zeros((8, 8, 1), dtype=np.float32),
                np.zeros((32, 8, 8), dtype=np.float32),
            )

    model = WamModel(backend=InvalidBackend())

    try:
        model.decode(np.zeros((64, 64, 3), dtype=np.uint8))
    except ValueError as error:
        assert "HxW" in str(error)
    else:
        raise AssertionError("invalid WAM prediction shape was accepted")
