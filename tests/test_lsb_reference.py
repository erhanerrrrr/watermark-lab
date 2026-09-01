import numpy as np

from watermark_lab.models.lsb_reference import LSBReferenceModel


def test_lsb_round_trip_preserves_source() -> None:
    rng = np.random.default_rng(7)
    image = rng.integers(0, 256, size=(64, 64, 3), dtype=np.uint8)
    original = image.copy()
    message = rng.integers(0, 2, size=32, dtype=np.uint8)
    model = LSBReferenceModel()

    embedded = model.encode(image, message)
    decoded = model.decode(embedded.image)

    assert np.array_equal(image, original)
    assert not np.array_equal(embedded.image, original)
    assert decoded.detected
    assert np.array_equal(decoded.message, message)
