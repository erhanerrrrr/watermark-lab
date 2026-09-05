from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from scripts.run_border_stress import rotate_boundary as frozen_rotation
from watermark_lab.api.service import run_single_experiment
from watermark_lab.attacks.boundary_rotation import rotate_boundary


@pytest.mark.parametrize("boundary", ["black", "reflect", "crop_resize"])
@pytest.mark.parametrize("shape", [(128, 192, 3), (211, 128, 3)])
@pytest.mark.parametrize("angle", [-12.7, 8.3])
def test_interactive_boundary_matches_frozen_experiment(
    boundary: str, shape: tuple[int, ...], angle: float
) -> None:
    image = np.random.default_rng(123).integers(0, 256, shape, dtype=np.uint8)
    assert np.array_equal(
        rotate_boundary(image, angle, boundary), frozen_rotation(image, angle, boundary)
    )


@pytest.mark.parametrize("boundary", ["black", "reflect", "crop_resize"])
def test_single_experiment_applies_and_records_selected_boundary(boundary: str) -> None:
    image = np.random.default_rng(321).integers(0, 256, (128, 192, 3), dtype=np.uint8)
    stream = io.BytesIO()
    Image.fromarray(image).save(stream, format="PNG")
    result = run_single_experiment(
        image_payload=stream.getvalue(), image_name="boundary.png", model_name="lsb_reference",
        message="boundary-test", strength=2.0, attack_name=f"rotate_{boundary}",
        attack_parameter=8.3, device="cpu",
    )
    assert result.record.attack_parameters == {
        "name": "boundary_rotation", "angle": 8.3, "boundary": boundary,
    }
    if boundary in {"black", "reflect"}:
        assert -1.0 <= result.record.post_attack_ssim < 0.0
    assert np.array_equal(
        result.images["attacked"], frozen_rotation(result.images["embedded"], 8.3, boundary)
    )
