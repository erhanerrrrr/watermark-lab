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
        "gamma",
        "color_shift",
        "pixelate",
    )


def _mask_rectangle(
    width: int,
    height: int,
    mask_ratio: float,
    *,
    center_x: float = 0.5,
    center_y: float = 0.5,
    aspect_ratio: float = 1.0,
) -> tuple[int, int, int, int]:
    if not 0 < mask_ratio < 1:
        raise ValueError("mask_ratio must be in (0, 1)")
    if not 0.0 <= center_x <= 1.0 or not 0.0 <= center_y <= 1.0:
        raise ValueError("mask center coordinates must be in [0, 1]")
    if aspect_ratio <= 0:
        raise ValueError("mask aspect_ratio must be positive")
    patch_width = max(1, round(width * (mask_ratio * aspect_ratio) ** 0.5))
    patch_height = max(1, round(height * (mask_ratio / aspect_ratio) ** 0.5))
    patch_width = min(width, patch_width)
    patch_height = min(height, patch_height)
    left = round(center_x * width - patch_width / 2)
    top = round(center_y * height - patch_height / 2)
    left = min(max(0, left), width - patch_width)
    top = min(max(0, top), height - patch_height)
    return left, top, left + patch_width, top + patch_height


def _perspective_coefficients(
    width: int,
    height: int,
    magnitude: float,
    offsets: list[float] | tuple[float, ...] | None = None,
) -> tuple[float, ...]:
    max_x = float(width - 1)
    max_y = float(height - 1)
    source = np.array(((0, 0), (max_x, 0), (max_x, max_y), (0, max_y)), dtype=float)
    if offsets is None:
        if not 0 < magnitude < 0.25:
            raise ValueError("perspective magnitude must be in (0, 0.25)")
        dx = max_x * magnitude
        dy = max_y * magnitude
        destination = np.array(
            ((dx, dy), (max_x - dx, 0), (max_x, max_y - dy), (0, max_y)),
            dtype=float,
        )
    else:
        values = np.asarray(offsets, dtype=float).reshape(-1)
        if values.size != 8 or not np.all(np.isfinite(values)):
            raise ValueError("perspective offsets must contain eight finite values")
        if np.max(np.abs(values)) >= 0.25:
            raise ValueError("perspective offsets must stay within (-0.25, 0.25)")
        destination = source + values.reshape(4, 2) * np.array((max_x, max_y))
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
        offsets = params.get("offsets")
        coefficients = _perspective_coefficients(width, height, magnitude, offsets)
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
        center_x = float(params.get("center_x", 0.5))
        center_y = float(params.get("center_y", 0.5))
        aspect_ratio = float(params.get("aspect_ratio", 1.0))
        left, top, right, bottom = _mask_rectangle(
            width,
            height,
            mask_ratio,
            center_x=center_x,
            center_y=center_y,
            aspect_ratio=aspect_ratio,
        )
        output = np.array(image, copy=True)
        if attack.name == "local_splice":
            donor = np.flip(image, axis=1)
            output[top:bottom, left:right] = donor[top:bottom, left:right]
        elif attack.name == "copy_move":
            patch_height = bottom - top
            patch_width = right - left
            if "source_x" in params or "source_y" in params:
                source_x = float(params.get("source_x", 0.5))
                source_y = float(params.get("source_y", 0.5))
                if not 0.0 <= source_x <= 1.0 or not 0.0 <= source_y <= 1.0:
                    raise ValueError("copy-move source coordinates must be in [0, 1]")
                source_left = round(source_x * width - patch_width / 2)
                source_top = round(source_y * height - patch_height / 2)
                source_left = min(max(0, source_left), width - patch_width)
                source_top = min(max(0, source_top), height - patch_height)
            else:
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
    if attack.name == "gamma":
        gamma = float(params.get("gamma", 1.0))
        if not 0.1 <= gamma <= 5.0:
            raise ValueError("gamma must be in [0.1, 5.0]")
        normalized = np.asarray(image, dtype=np.float32) / 255.0
        corrected = np.power(normalized, gamma)
        return np.ascontiguousarray(
            np.clip(np.rint(corrected * 255.0), 0, 255).astype(np.uint8)
        )
    if attack.name == "color_shift":
        gains = np.asarray(params.get("gains", (1.0, 1.0, 1.0)), dtype=np.float32)
        if gains.shape != (3,) or not np.all(np.isfinite(gains)):
            raise ValueError("color_shift gains must contain three finite values")
        if np.any(gains < 0.25) or np.any(gains > 4.0):
            raise ValueError("color_shift gains must be in [0.25, 4.0]")
        shifted = np.asarray(image, dtype=np.float32) * gains.reshape(1, 1, 3)
        return np.ascontiguousarray(np.clip(np.rint(shifted), 0, 255).astype(np.uint8))
    if attack.name == "pixelate":
        scale = float(params.get("scale", 0.125))
        if not 0.01 <= scale <= 1.0:
            raise ValueError("pixelate scale must be in [0.01, 1.0]")
        reduced = pil_image.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))),
            Image.Resampling.BOX,
        )
        return _to_array(reduced.resize((width, height), Image.Resampling.NEAREST))

    choices = ", ".join(supported_attacks())
    raise KeyError(f"unknown attack '{attack.name}'. Supported attacks: {choices}")
