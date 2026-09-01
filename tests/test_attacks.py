import numpy as np
import pytest

from watermark_lab.attacks.basic import AttackSpec, apply_attack


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
