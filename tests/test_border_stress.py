from __future__ import annotations

import numpy as np
import pytest

from scripts.run_border_stress import paired_bootstrap, rotate_boundary
from watermark_lab.attacks.basic import AttackSpec, apply_attack


def test_padding_variants_preserve_shared_rotated_interior() -> None:
    source = np.random.default_rng(4).integers(0, 256, (80, 120, 3), dtype=np.uint8)
    median = rotate_boundary(source, 12.7, "median")
    black = rotate_boundary(source, 12.7, "black")
    reflected = rotate_boundary(source, 12.7, "reflect")
    assert np.array_equal(median[20:60, 30:90], black[20:60, 30:90])
    assert np.array_equal(median[20:60, 30:90], reflected[20:60, 30:90])
    assert np.all(black[0, 0] == 0)
    assert not np.array_equal(median, reflected)


def test_median_control_matches_existing_attack_pixel_for_pixel() -> None:
    source = np.random.default_rng(6).integers(0, 256, (91, 123, 3), dtype=np.uint8)
    actual = rotate_boundary(source, -12.7, "median")
    expected = apply_attack(
        source, AttackSpec("rotation", {"angle": -12.7}), np.random.default_rng(42)
    )
    assert np.array_equal(actual, expected)


@pytest.mark.parametrize("shape", [(80, 120, 3), (120, 80, 3), (80, 80, 3)])
@pytest.mark.parametrize("angle", [-12.7, 8.3, 12.7])
def test_inscribed_crop_removes_rotated_corner_support(shape, angle) -> None:
    # A white border around a black interior would expose any remaining padded corner.
    source = np.zeros(shape, dtype=np.uint8)
    source[1:-1, 1:-1] = 230
    result = rotate_boundary(source, angle, "crop_resize")
    assert result.shape == source.shape
    assert result.min() >= 220


def test_all_boundary_modes_preserve_identity() -> None:
    source = np.random.default_rng(5).integers(0, 256, (30, 40, 3), dtype=np.uint8)
    for boundary in ("median", "black", "reflect", "crop_resize"):
        assert np.array_equal(source, rotate_boundary(source, 0, boundary))


def test_bootstrap_uses_image_units_and_is_reproducible() -> None:
    values = np.asarray([0, 1 / 3, 2 / 3, 1])
    first = paired_bootstrap(values, 2000, 42)
    assert first == paired_bootstrap(values, 2000, 42)
    assert first["mean"] == 0.5
    assert first["ci95_low"] < 0.5 < first["ci95_high"]
