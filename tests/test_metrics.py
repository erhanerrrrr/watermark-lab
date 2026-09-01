import math

import numpy as np

from watermark_lab.metrics.image_quality import mse, psnr
from watermark_lab.metrics.message import ber, bit_accuracy, complete_recovery


def test_image_metrics() -> None:
    reference = np.zeros((8, 8, 3), dtype=np.uint8)
    same = reference.copy()
    changed = np.ones_like(reference)
    assert mse(reference, same) == 0.0
    assert math.isinf(psnr(reference, same))
    assert mse(reference, changed) == 1.0


def test_message_metrics() -> None:
    expected = np.array([0, 1, 0, 1], dtype=np.uint8)
    actual = np.array([0, 1, 1, 1], dtype=np.uint8)
    assert bit_accuracy(expected, actual) == 0.75
    assert ber(expected, actual) == 0.25
    assert not complete_recovery(expected, actual)
