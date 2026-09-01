import numpy as np
import pytest

from watermark_lab.attacks.basic import AttackSpec, apply_attack
from watermark_lab.metrics.image_quality import psnr
from watermark_lab.metrics.message import bit_accuracy
from watermark_lab.models.dwt_dct import DwtDctWatermarkModel


def _textured_image(size: int = 256) -> np.ndarray:
    generator = np.random.default_rng(73)
    axis = np.linspace(0, 255, size, dtype=np.float64)
    x_grid, y_grid = np.meshgrid(axis, axis)
    noise = generator.normal(0.0, 12.0, size=(size, size))
    red = np.clip(x_grid + noise, 0, 255)
    green = np.clip(y_grid + noise, 0, 255)
    blue = np.clip((x_grid + y_grid) / 2.0 + noise, 0, 255)
    return np.rint(np.stack((red, green, blue), axis=2)).astype(np.uint8)


def test_dwt_dct_identity_round_trip_and_quality() -> None:
    generator = np.random.default_rng(11)
    image = _textured_image()
    original = image.copy()
    message = generator.integers(0, 2, size=32, dtype=np.uint8)
    model = DwtDctWatermarkModel()

    embedded = model.encode(image, message)
    decoded = model.decode(embedded.image)

    assert np.array_equal(image, original)
    assert decoded.detected
    assert np.array_equal(decoded.message, message)
    assert psnr(image, embedded.image) >= 38.0
    assert embedded.metadata["repetition"] == 5


def test_dwt_dct_has_useful_jpeg_robustness() -> None:
    generator = np.random.default_rng(19)
    image = _textured_image()
    message = generator.integers(0, 2, size=32, dtype=np.uint8)
    model = DwtDctWatermarkModel()
    embedded = model.encode(image, message).image
    attacked = apply_attack(embedded, AttackSpec("jpeg", {"quality": 80}))
    decoded = model.decode(attacked)

    assert decoded.detected
    assert bit_accuracy(message, decoded.message) >= 0.9


def test_dwt_dct_rejects_images_without_capacity() -> None:
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    message = np.zeros(32, dtype=np.uint8)

    with pytest.raises(ValueError, match="requires at least 48 LL blocks"):
        DwtDctWatermarkModel().encode(image, message)
