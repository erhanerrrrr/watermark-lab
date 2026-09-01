from __future__ import annotations

import numpy as np

from watermark_lab.core.types import BitArray


def _matching_bits(expected: BitArray, actual: BitArray) -> tuple[np.ndarray, np.ndarray]:
    first = np.asarray(expected, dtype=np.uint8).reshape(-1)
    second = np.asarray(actual, dtype=np.uint8).reshape(-1)
    if first.shape != second.shape:
        raise ValueError(f"message shapes differ: {first.shape} vs {second.shape}")
    return first, second


def bit_accuracy(expected: BitArray, actual: BitArray) -> float:
    first, second = _matching_bits(expected, actual)
    return float(np.mean(first == second))


def ber(expected: BitArray, actual: BitArray) -> float:
    return 1.0 - bit_accuracy(expected, actual)


def complete_recovery(expected: BitArray, actual: BitArray) -> bool:
    first, second = _matching_bits(expected, actual)
    return bool(np.array_equal(first, second))
