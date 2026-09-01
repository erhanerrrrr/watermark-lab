from __future__ import annotations

import numpy as np

from watermark_lab.core.types import DecodeResult, EmbedResult
from watermark_lab.innovations.content_adaptive import (
    AdaptiveStrengthConfig,
    ContentAdaptiveStrengthController,
)
from watermark_lab.innovations.geometry_sync import GeometrySyncConfig, GeometrySyncDecoder
from watermark_lab.models.wam_adapter import WamSpatialPrediction


class FakeStrengthModel:
    message_bits = 32

    def __init__(self) -> None:
        self.strength = 1.0
        self.message = np.zeros(32, dtype=np.uint8)

    def encode(self, image: np.ndarray, message: np.ndarray) -> EmbedResult:
        self.message = message.copy()
        # Float output makes the analytical PSNR/strength relation exact in this unit test.
        output = image.astype(np.float64) + self.strength
        return EmbedResult(output, {"strength": self.strength})

    def decode(self, image: np.ndarray) -> DecodeResult:
        robust = self.strength >= 3.0
        message = self.message.copy()
        if not robust:
            message[0] ^= 1
        return DecodeResult(
            message=message,
            detected=True,
            confidence=0.9,
            metadata={"minimum_absolute_bit_margin": 0.3 if robust else 0.05},
        )


def test_adaptive_strength_spends_bounded_quality_budget_for_hard_content() -> None:
    model = FakeStrengthModel()
    controller = ContentAdaptiveStrengthController(
        model,
        base_strength=1.0,
        config=AdaptiveStrengthConfig(
            target_psnr_db=40.0,
            minimum_psnr_db=38.0,
            robustness_steps=5,
        ),
    )
    image = np.full((32, 32, 3), 100, dtype=np.uint8)
    message = np.asarray([0, 1] * 16, dtype=np.uint8)

    result = controller.encode(image, message)

    assert result.metadata["selected_strength"] >= 3.0
    assert result.metadata["selected_psnr_db"] >= 37.85
    assert result.metadata["quality_budget_spent_db"] <= 2.15
    assert len(result.metadata["strength_search"]) >= 2
    assert "laplacian_variance" in result.metadata["content_features"]


class FakeGeometryModel:
    message_bits = 32
    detection_threshold = 0.5
    minimum_detected_fraction = 0.01
    bit_logit_threshold = 0.5

    def validate_image(self, image: np.ndarray) -> np.ndarray:
        return np.asarray(image, dtype=np.uint8)

    def predict_spatial(self, image: np.ndarray) -> WamSpatialPrediction:
        recovered = bool(image[0, 0, 0])
        detection = np.full((4, 4), 0.95 if recovered else 0.60, dtype=np.float32)
        expected = np.asarray([0, 1] * 16, dtype=np.uint8)
        if not recovered:
            expected = 1 - expected
        logits = np.empty((32, 4, 4), dtype=np.float32)
        for index, bit in enumerate(expected):
            logits[index] = 3.0 if bit else -2.0
        return WamSpatialPrediction(detection, logits)


class FixtureGeometryDecoder(GeometrySyncDecoder):
    def candidate_images(self, image: np.ndarray) -> list[tuple[str, np.ndarray]]:
        identity = np.zeros_like(image)
        recovered = np.zeros_like(image)
        recovered[0, 0, 0] = 255
        return [("identity", identity), ("rotation_-10", recovered)]


def test_geometry_sync_selects_the_confident_inverse_branch() -> None:
    decoder = FixtureGeometryDecoder(
        FakeGeometryModel(),  # type: ignore[arg-type]
        config=GeometrySyncConfig(
            rotation_corrections=(),
            perspective_corrections=(),
            fusion_top_k=1,
            minimum_border_evidence=0.0,
            minimum_score_improvement=0.0,
        ),
    )

    result = decoder.decode(np.zeros((16, 16, 3), dtype=np.uint8))

    assert result.metadata["selected_transform"] == "rotation_-10"
    assert np.array_equal(result.message, np.asarray([0, 1] * 16, dtype=np.uint8))
    assert result.metadata["score_improvement"] > 0


def test_geometry_sync_skips_search_without_border_evidence() -> None:
    decoder = FixtureGeometryDecoder(
        FakeGeometryModel(),  # type: ignore[arg-type]
        config=GeometrySyncConfig(
            rotation_corrections=(),
            perspective_corrections=(),
            fusion_top_k=1,
            minimum_border_evidence=0.5,
        ),
    )

    result = decoder.decode(np.zeros((16, 16, 3), dtype=np.uint8))

    assert result.metadata["selected_transform"] == "identity"
    assert result.metadata["geometry_search_skipped"]
    assert result.metadata["candidate_count"] == 1


def test_coarse_to_fine_search_evaluates_six_instead_of_ten_branches() -> None:
    decoder = GeometrySyncDecoder(
        FakeGeometryModel(),  # type: ignore[arg-type]
        config=GeometrySyncConfig(
            minimum_border_evidence=0.0,
            search_strategy="coarse_to_fine",
        ),
    )

    result = decoder.decode(np.zeros((32, 32, 3), dtype=np.uint8))

    assert result.metadata["configured_candidate_count"] == 10
    assert result.metadata["candidate_count"] == 6
    assert result.metadata["search_strategy"] == "coarse_to_fine"
