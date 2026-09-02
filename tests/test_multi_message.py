from __future__ import annotations

import numpy as np

from watermark_lab.core.types import EmbedResult
from watermark_lab.innovations.multi_message import (
    AdaptiveSoftMessageClusterer,
    MultiMessageConfig,
    embed_multiple_regions,
    rectangular_region_masks,
    small_patch_region_masks,
)
from watermark_lab.metrics.multi_message import evaluate_multi_message_result
from watermark_lab.models.wam_adapter import WamSpatialPrediction


def _prediction_fixture() -> tuple[WamSpatialPrediction, np.ndarray, np.ndarray]:
    height, width = 20, 24
    messages = np.asarray(
        [
            [0] * 32,
            [0, 1] * 16,
        ],
        dtype=np.uint8,
    )
    masks = rectangular_region_masks(
        height,
        width,
        2,
        margin_fraction=0.05,
        gap_fraction=0.05,
    )
    detection = np.full((height, width), 0.1, dtype=np.float32)
    logits = np.zeros((32, height, width), dtype=np.float32)
    rng = np.random.default_rng(42)
    for message, mask in zip(messages, masks, strict=True):
        detection[mask] = 0.95
        values = np.where(message == 1, 3.0, -2.0).astype(np.float32)
        logits[:, mask] = values[:, None] + rng.normal(
            0.0,
            0.08,
            size=(32, int(np.sum(mask))),
        )
    return WamSpatialPrediction(detection, logits), messages, masks


def test_adaptive_soft_clusterer_recovers_messages_and_regions() -> None:
    prediction, messages, masks = _prediction_fixture()
    clusterer = AdaptiveSoftMessageClusterer(
        config=MultiMessageConfig(
            minimum_cluster_pixels=12,
            minimum_cluster_fraction=0.03,
            localization_threshold=0.2,
        )
    )

    result = clusterer.decode_prediction(prediction)
    metrics = evaluate_multi_message_result(
        messages,
        result.messages,
        expected_masks=masks,
        predicted_localizations=result.localizations,
        localization_threshold=0.2,
    )

    assert result.count == 2
    assert metrics.count_correct
    assert metrics.all_messages_recovered
    assert metrics.mean_matched_iou > 0.95
    assert result.metadata["adaptive_minimum_support"]
    assert result.metadata["soft_assignment"]
    assert result.metadata["adaptive_weighted_dbscan_seeding"]


def test_adaptive_soft_clusterer_returns_empty_without_detection() -> None:
    prediction = WamSpatialPrediction(
        np.full((8, 8), 0.1, dtype=np.float32),
        np.zeros((32, 8, 8), dtype=np.float32),
    )

    result = AdaptiveSoftMessageClusterer().decode_prediction(prediction)

    assert result.count == 0
    assert result.localizations.shape == (0, 8, 8)
    assert np.all(result.label_map == -1)


def test_multi_message_metrics_match_permuted_predictions() -> None:
    expected = np.asarray([[0] * 32, [1] * 32], dtype=np.uint8)
    predicted = expected[::-1].copy()
    masks = rectangular_region_masks(16, 16, 2)
    localizations = masks[::-1].astype(np.float32)

    metrics = evaluate_multi_message_result(
        expected,
        predicted,
        expected_masks=masks,
        predicted_localizations=localizations,
    )

    assert metrics.assignments == ((0, 1), (1, 0))
    assert metrics.message_precision == 1.0
    assert metrics.message_recall == 1.0
    assert metrics.mean_matched_iou == 1.0
    assert metrics.all_messages_recovered


class _RegionalFixtureModel:
    message_bits = 32

    @staticmethod
    def validate_image(image: np.ndarray) -> np.ndarray:
        return np.ascontiguousarray(np.asarray(image, dtype=np.uint8))

    @staticmethod
    def validate_message(message: np.ndarray) -> np.ndarray:
        bits = np.asarray(message, dtype=np.uint8)
        if bits.shape != (32,):
            raise ValueError("fixture expects 32 bits")
        return bits

    def encode(self, image: np.ndarray, message: np.ndarray) -> EmbedResult:
        value = 220 if message[0] else 30
        return EmbedResult(np.full_like(image, value), {"fixture_value": value})


def test_multi_region_embedding_only_changes_requested_masks() -> None:
    image = np.full((20, 24, 3), 100, dtype=np.uint8)
    messages = np.asarray([[0] * 32, [1] * 32], dtype=np.uint8)
    masks = rectangular_region_masks(20, 24, 2)

    result = embed_multiple_regions(_RegionalFixtureModel(), image, messages, masks)

    assert np.all(result.image[masks[0]] == 30)
    assert np.all(result.image[masks[1]] == 220)
    assert np.all(result.image[~np.any(masks, axis=0)] == 100)
    assert result.metadata["message_count"] == 2


def test_small_patch_layout_is_disjoint_and_below_official_fixed_support() -> None:
    masks = small_patch_region_masks(256, 256)

    assert masks.shape == (2, 256, 256)
    assert not np.any(masks[0] & masks[1])
    assert 1000 < np.sum(masks[1]) < 3000
