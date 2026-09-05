"""Interactive boundary rotations matching the frozen geometry-v3 attack pixels.

The research collector retains its frozen helper for historical reproducibility.
This module exposes the same operation without importing research scripts in the API.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image

BOUNDARIES = ("median", "black", "reflect", "crop_resize")


def rotate_boundary(image: np.ndarray, angle: float, boundary: str) -> np.ndarray:
    """Rotate around the same center; reflection changes only out-of-frame samples."""
    if boundary not in BOUNDARIES:
        raise ValueError(f"unknown boundary: {boundary}")
    if not math.isfinite(angle) or abs(angle) >= 45:
        raise ValueError("angle must be finite and within (-45, 45)")
    source = np.asarray(image, dtype=np.uint8)
    height, width = source.shape[:2]
    if height < 8 or width < 8:
        raise ValueError("border stress requires image dimensions of at least eight")
    fill = tuple(int(value) for value in np.median(source, axis=(0, 1)))
    if boundary == "reflect":
        padding = max(height, width)
        padded = np.pad(source, ((padding, padding), (padding, padding), (0, 0)), mode="reflect")
        rotated = Image.fromarray(padded).rotate(angle, Image.Resampling.BICUBIC)
        rotated = rotated.crop((padding, padding, padding + width, padding + height))
    else:
        rotated = Image.fromarray(source).rotate(
            angle,
            Image.Resampling.BICUBIC,
            expand=False,
            fillcolor=(0, 0, 0) if boundary == "black" else fill,
        )
    if boundary == "crop_resize" and angle != 0:
        radians = math.radians(abs(angle))
        cosine, sine = math.cos(radians), math.sin(radians)
        scale = min(
            width / (width * cosine + height * sine), height / (width * sine + height * cosine)
        )
        crop_width = max(1, math.floor(width * scale) - 4)
        crop_height = max(1, math.floor(height * scale) - 4)
        left, top = (width - crop_width) // 2, (height - crop_height) // 2
        rotated = rotated.crop((left, top, left + crop_width, top + crop_height))
        rotated = rotated.resize((width, height), Image.Resampling.BICUBIC)
    return np.ascontiguousarray(np.asarray(rotated, dtype=np.uint8))
