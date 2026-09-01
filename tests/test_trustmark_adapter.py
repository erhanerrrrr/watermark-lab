import numpy as np
from PIL import Image

from watermark_lab.models.trustmark_adapter import TrustMarkQModel


class FakeTrustMark:
    def __init__(self) -> None:
        self.payload = ""

    def schemaCapacity(self) -> int:
        return 61

    def encode(
        self,
        image: Image.Image,
        payload: str,
        *,
        MODE: str,
        WM_STRENGTH: float,
    ) -> Image.Image:
        assert MODE == "binary"
        assert WM_STRENGTH == 1.0
        self.payload = payload
        return image.copy()

    def decode(
        self,
        image: Image.Image,
        *,
        MODE: str,
        DETECTFIRST: bool,
        ROTATION: bool,
    ) -> tuple[str, bool, int]:
        assert image.mode == "RGB"
        assert MODE == "binary"
        assert not DETECTFIRST
        assert not ROTATION
        return self.payload + "0" * (61 - len(self.payload)), True, 1


def test_trustmark_adapter_uses_binary_bch_payload() -> None:
    backend = FakeTrustMark()
    model = TrustMarkQModel(backend=backend)
    image = np.full((128, 160, 3), 127, dtype=np.uint8)
    message = np.array(([0, 1] * 16), dtype=np.uint8)

    encoded = model.encode(image, message)
    decoded = model.decode(encoded.image)

    assert backend.payload == "01" * 16
    assert decoded.detected
    assert np.array_equal(decoded.message, message)
    assert encoded.metadata["encoding"] == "BCH_5"
    assert encoded.metadata["schema_capacity"] == 61


def test_trustmark_adapter_returns_fixed_length_on_no_detection() -> None:
    class NoDetectionBackend(FakeTrustMark):
        def decode(self, *args: object, **kwargs: object) -> tuple[str, bool, int]:
            return "", False, -1

    model = TrustMarkQModel(backend=NoDetectionBackend())
    result = model.decode(np.zeros((128, 128, 3), dtype=np.uint8))

    assert not result.detected
    assert result.message.shape == (32,)
    assert not result.message.any()
