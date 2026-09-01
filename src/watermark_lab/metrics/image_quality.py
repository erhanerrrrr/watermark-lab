from __future__ import annotations

import math

import numpy as np

from watermark_lab.core.types import ImageArray


def _matching_float_arrays(
    reference: ImageArray,
    candidate: ImageArray,
) -> tuple[np.ndarray, np.ndarray]:
    first = np.asarray(reference)
    second = np.asarray(candidate)
    if first.shape != second.shape:
        raise ValueError(f"image shapes differ: {first.shape} vs {second.shape}")
    return first.astype(np.float64), second.astype(np.float64)


def mse(reference: ImageArray, candidate: ImageArray) -> float:
    first, second = _matching_float_arrays(reference, candidate)
    return float(np.mean((first - second) ** 2))


def psnr(reference: ImageArray, candidate: ImageArray, data_range: float = 255.0) -> float:
    error = mse(reference, candidate)
    if error == 0.0:
        return math.inf
    return float(10.0 * math.log10((data_range**2) / error))


def ssim(reference: ImageArray, candidate: ImageArray) -> float:
    try:
        from skimage.metrics import structural_similarity
    except ImportError as exc:
        raise RuntimeError("SSIM requires 'pip install -e .[research]'") from exc
    first, second = _matching_float_arrays(reference, candidate)
    return float(structural_similarity(first, second, channel_axis=2, data_range=255.0))
