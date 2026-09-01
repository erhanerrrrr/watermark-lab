from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from watermark_lab.core.types import ImageArray


@dataclass(frozen=True)
class AttackSpec:
    name: str
    parameters: dict[str, Any] = field(default_factory=dict)


def _to_pil(image: ImageArray) -> Image.Image:
    array = np.asarray(image)
    if array.dtype != np.uint8 or array.ndim != 3 or array.shape[2] != 3:
        raise ValueError("attacks require an RGB uint8 image")
    return Image.fromarray(array)


def _to_array(image: Image.Image) -> ImageArray:
    return np.ascontiguousarray(np.asarray(image.convert("RGB"), dtype=np.uint8))


def supported_attacks() -> tuple[str, ...]:
    return (
        "identity",
        "jpeg",
        "gaussian_blur",
        "gaussian_noise",
        "brightness",
        "contrast",
        "horizontal_flip",
        "rotation",
        "perspective",
        "resize_roundtrip",
        "crop_resize",
        "local_splice",
        "copy_move",
        "local_inpaint",
    )


def _mask_rectangle(
    width: int,
    height: int,
    mask_ratio: float,
) -> tuple[int, int, int, int]:
    if not 0 < mask_ratio < 1:
        raise ValueError("mask_ratio must be in (0, 1)")
    side_ratio = mask_ratio**0.5
    patch_width = max(1, round(width * side_ratio))
    patch_height = max(1, round(height * side_ratio))
    left = (width - patch_width) // 2
    top = (height - patch_height) // 2
    return left, top, left + patch_width, top + patch_height


def _perspective_coefficients(
    width: int,
    height: int,
    magnitude: float,
) -> tuple[float, ...]:
    if not 0 < magnitude < 0.25:
        raise ValueError("perspective magnitude must be in (0, 0.25)")
    max_x = float(width - 1)
    max_y = float(height - 1)
    source = np.array(((0, 0), (max_x, 0), (max_x, max_y), (0, max_y)), dtype=float)
    dx = max_x * magnitude
    dy = max_y * magnitude
    destination = np.array(
        ((dx, dy), (max_x - dx, 0), (max_x, max_y - dy), (0, max_y)),
        dtype=float,
    )
    system: list[list[float]] = []
    targets: list[float] = []
    for (source_x, source_y), (dest_x, dest_y) in zip(source, destination, strict=True):
        system.append(
            [source_x, source_y, 1.0, 0.0, 0.0, 0.0, -dest_x * source_x, -dest_x * source_y]
        )
        targets.append(dest_x)
        system.append(
            [0.0, 0.0, 0.0, source_x, source_y, 1.0, -dest_y * source_x, -dest_y * source_y]
        )
        targets.append(dest_y)
    forward = np.append(np.linalg.solve(np.asarray(system), np.asarray(targets)), 1.0).reshape(3, 3)
    inverse = np.linalg.inv(forward)
    inverse /= inverse[2, 2]
    return tuple(float(value) for value in inverse.reshape(-1)[:8])


def apply_attack(
    image: ImageArray,
    attack: AttackSpec,
    rng: np.random.Generator | None = None,
) -> ImageArray:
    params = attack.parameters
    pil_image = _to_pil(image)
    width, height = pil_image.size

    if attack.name == "identity":
        return np.array(image, copy=True)
    if attack.name == "jpeg":
        quality = int(params.get("quality", 80))
        if not 1 <= quality <= 100:
            raise ValueError("JPEG quality must be between 1 and 100")
        stream = BytesIO()
        pil_image.save(stream, format="JPEG", quality=quality, subsampling=0)
        stream.seek(0)
        with Image.open(stream) as decoded:
            return _to_array(decoded)
    if attack.name == "gaussian_blur":
        radius = float(params.get("radius", 1.0))
        return _to_array(pil_image.filter(ImageFilter.GaussianBlur(radius=radius)))
    if attack.name == "gaussian_noise":
        sigma = float(params.get("sigma", 0.01))
        generator = rng or np.random.default_rng()
        normalized = np.asarray(image, dtype=np.float32) / 255.0
        noisy = normalized + generator.normal(0.0, sigma, size=normalized.shape)
        return np.ascontiguousarray(np.clip(np.rint(noisy * 255.0), 0, 255).astype(np.uint8))
    if attack.name == "brightness":
        factor = float(params.get("factor", 1.0))
        return _to_array(ImageEnhance.Brightness(pil_image).enhance(factor))
    if attack.name == "contrast":
        factor = float(params.get("factor", 1.0))
        return _to_array(ImageEnhance.Contrast(pil_image).enhance(factor))
    if attack.name == "horizontal_flip":
        return _to_array(pil_image.transpose(Image.Transpose.FLIP_LEFT_RIGHT))
    if attack.name == "rotation":
        angle = float(params.get("angle", 3.0))
        if not -180.0 <= angle <= 180.0:
            raise ValueError("rotation angle must be between -180 and 180 degrees")
        fill = tuple(int(value) for value in np.median(image, axis=(0, 1)))
        return _to_array(
            pil_image.rotate(
                angle,
                resample=Image.Resampling.BICUBIC,
                expand=False,
                fillcolor=fill,
            )
        )
    if attack.name == "perspective":
        magnitude = float(params.get("magnitude", 0.05))
        coefficients = _perspective_coefficients(width, height, magnitude)
        fill = tuple(int(value) for value in np.median(image, axis=(0, 1)))
        return _to_array(
            pil_image.transform(
                (width, height),
                Image.Transform.PERSPECTIVE,
                coefficients,
                resample=Image.Resampling.BICUBIC,
                fillcolor=fill,
            )
        )
    if attack.name == "resize_roundtrip":
        scale = float(params.get("scale", 0.75))
        if scale <= 0:
            raise ValueError("resize scale must be positive")
        resized = pil_image.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))),
            Image.Resampling.BICUBIC,
        )
        return _to_array(resized.resize((width, height), Image.Resampling.BICUBIC))
    if attack.name == "crop_resize":
        keep_ratio = float(params.get("keep_ratio", 0.8))
        if not 0 < keep_ratio <= 1:
            raise ValueError("crop keep_ratio must be in (0, 1]")
        crop_width = max(1, round(width * keep_ratio**0.5))
        crop_height = max(1, round(height * keep_ratio**0.5))
        left = (width - crop_width) // 2
        top = (height - crop_height) // 2
        cropped = pil_image.crop((left, top, left + crop_width, top + crop_height))
        return _to_array(cropped.resize((width, height), Image.Resampling.BICUBIC))
    if attack.name in {"local_splice", "copy_move", "local_inpaint"}:
        mask_ratio = float(params.get("mask_ratio", 0.1))
        left, top, right, bottom = _mask_rectangle(width, height, mask_ratio)
        output = np.array(image, copy=True)
        if attack.name == "local_splice":
            donor = np.flip(image, axis=1)
            output[top:bottom, left:right] = donor[top:bottom, left:right]
        elif attack.name == "copy_move":
            patch_height = bottom - top
            patch_width = right - left
            generator = rng or np.random.default_rng()
            source_top = int(generator.integers(0, max(1, height - patch_height + 1)))
            source_left = int(generator.integers(0, max(1, width - patch_width + 1)))
            source_patch = image[
                source_top : source_top + patch_height,
                source_left : source_left + patch_width,
            ].copy()
            output[top:bottom, left:right] = source_patch
        else:
            blurred = _to_array(pil_image.filter(ImageFilter.GaussianBlur(radius=12.0)))
            output[top:bottom, left:right] = blurred[top:bottom, left:right]
        return np.ascontiguousarray(output)

    choices = ", ".join(supported_attacks())
    raise KeyError(f"unknown attack '{attack.name}'. Supported attacks: {choices}")
