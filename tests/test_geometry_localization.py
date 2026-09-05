from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from watermark_lab.attacks.basic import AttackSpec, apply_attack
from watermark_lab.innovations.geometry_sync import (
    GeometrySyncConfig,
    GeometrySyncDecoder,
    correct_perspective,
    localization_in_input_coordinates,
)
from watermark_lab.models.wam_adapter import WamSpatialPrediction


def _centroid_in_image(probabilities: np.ndarray, height: int, width: int) -> np.ndarray:
    y, x = np.indices(probabilities.shape, dtype=float)
    x = (x + 0.5) * width / probabilities.shape[1]
    y = (y + 0.5) * height / probabilities.shape[0]
    mass = probabilities.sum()
    return np.array(((x * probabilities).sum() / mass, (y * probabilities).sum() / mass))


def test_identity_localization_preserves_detector_grid_and_values() -> None:
    probabilities = np.random.default_rng(1).random((24, 32)).astype(np.float32)

    result = localization_in_input_coordinates(probabilities, "identity", (180, 320, 3))

    np.testing.assert_array_equal(result, probabilities)
    assert result.dtype == np.float32
    assert result.flags.c_contiguous


@pytest.mark.parametrize("angle", [-30.0, 30.0])
@pytest.mark.parametrize("grid_shape", [(120, 240), (40, 40), (30, 60)])
def test_rotation_localization_recovers_input_landmark_on_rectangular_images(
    angle: float, grid_shape: tuple[int, int]
) -> None:
    height, width = 120, 240
    grid_height, grid_width = grid_shape
    y, x = np.indices(grid_shape, dtype=float)
    x = (x + 0.5) * width / grid_width
    y = (y + 0.5) * height / grid_height
    branch_center = np.array((170.0, 45.0))
    probabilities = np.exp(-((x - branch_center[0]) ** 2 + (y - branch_center[1]) ** 2) / 80)

    result = localization_in_input_coordinates(
        probabilities, f"rotation_{angle:+g}", (height, width, 3)
    )

    # A positive correction rotates input points counterclockwise on screen;
    # returning the marker to the input must move it clockwise around the center.
    radians = np.deg2rad(angle)
    cosine, sine = np.cos(radians), np.sin(radians)
    inverse_rotation = np.array(((cosine, -sine), (sine, cosine)))
    center = np.array((width / 2, height / 2))
    expected = center + inverse_rotation @ (branch_center - center)
    np.testing.assert_allclose(_centroid_in_image(result, height, width), expected, atol=0.8)
    assert result.shape == grid_shape
    assert 0.0 <= result.min() <= result.max() <= 1.0


@pytest.mark.parametrize("image_shape", [(120, 240), (240, 120)])
def test_perspective_localization_returns_to_attacked_input_coordinates(
    image_shape: tuple[int, int],
) -> None:
    height, width = image_shape
    y, x = np.indices(image_shape)
    marker = ((x - 0.25 * width) / (0.1 * width)) ** 2 + (
        (y - 0.25 * height) / (0.1 * height)
    ) ** 2 <= 1.0
    image = np.repeat((marker.astype(np.uint8) * 255)[:, :, None], 3, axis=2)
    attacked = apply_attack(image, AttackSpec("perspective", {"magnitude": 0.15}))
    corrected = correct_perspective(attacked, 0.15)
    detector_map = np.asarray(
        Image.fromarray(corrected[:, :, 0]).resize((48, 48), Image.Resampling.BILINEAR),
        dtype=np.float32,
    ) / 255.0

    result = localization_in_input_coordinates(detector_map, "perspective_0.15", image.shape)

    projected = np.asarray(
        Image.fromarray(result).resize((width, height), Image.Resampling.BILINEAR)
    ) >= 0.5
    expected = attacked[:, :, 0] >= 128
    iou = np.sum(projected & expected) / np.sum(projected | expected)
    assert iou > 0.90
    assert result.shape == detector_map.shape
    assert 0.0 <= result.min() <= result.max() <= 1.0


def test_rotation_localization_does_not_invent_evidence_outside_branch_canvas() -> None:
    result = localization_in_input_coordinates(np.ones((40, 40)), "rotation_30", (120, 240, 3))

    assert result[0, 0] == 0.0
    assert result[-1, -1] == 0.0
    assert result[20, 20] == 1.0
    assert np.isfinite(result).all()


class _SparseBranchModel:
    message_bits = 32
    detection_threshold = 0.5
    minimum_detected_fraction = 0.01
    bit_logit_threshold = 0.5

    def __init__(self, *, empty: bool = False) -> None:
        self.empty = empty

    def validate_image(self, image: np.ndarray) -> np.ndarray:
        return image

    def predict_spatial(self, image: np.ndarray) -> WamSpatialPrediction:
        valid = bool(image[0, 0, 0]) and not self.empty
        detection = np.full((8, 8), 0.95 if valid else 0.1, dtype=np.float32)
        logits = np.full((32, 8, 8), 3.0, dtype=np.float32)
        return WamSpatialPrediction(detection, logits)


class _TwoBranchDecoder(GeometrySyncDecoder):
    def candidate_images(self, image: np.ndarray) -> list[tuple[str, np.ndarray]]:
        return [("identity", np.zeros_like(image)), ("rotation_30", np.ones_like(image))]


def test_geometry_fusion_ignores_empty_detection_branches() -> None:
    decoder = _TwoBranchDecoder(
        _SparseBranchModel(),  # type: ignore[arg-type]
        config=GeometrySyncConfig(minimum_border_evidence=0.0, fusion_top_k=3),
    )

    result = decoder.decode(np.zeros((24, 48, 3), dtype=np.uint8))

    assert result.detected
    assert np.all(result.message == 1)
    assert result.metadata["fused_transforms"] == ["rotation_30"]
    assert result.metadata["fusion_weights"] == [1.0]
    assert result.metadata["localization_coordinate_system"] == "input_image"
    assert result.metadata["localization_grid"] == "detector"
    assert result.localization.shape == (8, 8)
    # The candidate prediction was uniformly positive; its inverse-warped
    # input corners must be empty, proving decode returns the remapped map.
    assert result.localization[0, -1] == 0.0


@pytest.mark.parametrize("minimum_detected_fraction", [0.0, 0.01])
def test_all_empty_geometry_branches_return_undetected_without_fusion(
    minimum_detected_fraction: float,
) -> None:
    model = _SparseBranchModel(empty=True)
    model.minimum_detected_fraction = minimum_detected_fraction
    decoder = _TwoBranchDecoder(
        model,  # type: ignore[arg-type]
        config=GeometrySyncConfig(minimum_border_evidence=0.0),
    )

    result = decoder.decode(np.zeros((24, 48, 3), dtype=np.uint8))

    assert not result.detected
    assert np.all(result.message == 0)
    assert result.metadata["selected_transform"] == "identity"
    assert result.metadata["fused_transforms"] == ["identity"]
    assert np.isfinite(result.localization).all()
