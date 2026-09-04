import numpy as np
import pytest

from watermark_lab.attacks.basic import AttackSpec, apply_attack


def _sample_image() -> np.ndarray:
    values = np.arange(72 * 96 * 3, dtype=np.uint32).reshape(72, 96, 3)
    return (values % 251).astype(np.uint8)


@pytest.mark.parametrize(
    ("name", "parameters"),
    [
        ("identity", {}),
        ("jpeg", {"quality": 80}),
        ("gaussian_blur", {"radius": 1.0}),
        ("gaussian_noise", {"sigma": 0.01}),
        ("brightness", {"factor": 1.2}),
        ("contrast", {"factor": 1.2}),
        ("horizontal_flip", {}),
        ("rotation", {"angle": 3.0}),
        ("perspective", {"magnitude": 0.05}),
        ("resize_roundtrip", {"scale": 0.75}),
        ("crop_resize", {"keep_ratio": 0.8}),
        ("local_splice", {"mask_ratio": 0.1}),
        ("copy_move", {"mask_ratio": 0.1}),
        ("local_inpaint", {"mask_ratio": 0.1}),
    ],
)
def test_attack_preserves_image_contract(name: str, parameters: dict[str, float]) -> None:
    image = np.full((48, 64, 3), 127, dtype=np.uint8)
    attacked = apply_attack(
        image,
        AttackSpec(name, parameters),
        np.random.default_rng(1),
    )
    assert attacked.shape == image.shape
    assert attacked.dtype == np.uint8


def test_noise_attack_is_reproducible() -> None:
    image = np.full((32, 32, 3), 127, dtype=np.uint8)
    attack = AttackSpec("gaussian_noise", {"sigma": 0.02})
    first = apply_attack(image, attack, np.random.default_rng(9))
    second = apply_attack(image, attack, np.random.default_rng(9))
    assert np.array_equal(first, second)


def test_copy_move_attack_is_reproducible() -> None:
    image = np.arange(64 * 64 * 3, dtype=np.uint32).reshape(64, 64, 3)
    image = (image % 256).astype(np.uint8)
    attack = AttackSpec("copy_move", {"mask_ratio": 0.2})
    first = apply_attack(image, attack, np.random.default_rng(9))
    second = apply_attack(image, attack, np.random.default_rng(9))
    assert np.array_equal(first, second)


@pytest.mark.parametrize(
    ("name", "parameters"),
    [
        ("gamma", {"gamma": 0.75}),
        ("color_shift", {"gains": [1.08, 1.0, 0.9]}),
        ("pixelate", {"scale": 0.2}),
        (
            "perspective",
            {
                "offsets": [0.03, 0.01, -0.02, 0.04, -0.01, -0.03, 0.04, -0.02]
            },
        ),
        (
            "local_splice",
            {"mask_ratio": 0.12, "center_x": 0.25, "center_y": 0.75, "aspect_ratio": 2.0},
        ),
        (
            "copy_move",
            {
                "mask_ratio": 0.12,
                "center_x": 0.75,
                "center_y": 0.7,
                "source_x": 0.2,
                "source_y": 0.25,
                "aspect_ratio": 0.5,
            },
        ),
    ],
)
def test_robustness_v2_attacks_preserve_contract(
    name: str, parameters: dict[str, object]
) -> None:
    image = _sample_image()
    attacked = apply_attack(image, AttackSpec(name, parameters), np.random.default_rng(7))
    assert attacked.shape == image.shape
    assert attacked.dtype == np.uint8
    assert not np.array_equal(attacked, image)
