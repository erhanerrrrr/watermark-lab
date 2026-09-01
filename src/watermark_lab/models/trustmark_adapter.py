from __future__ import annotations

import importlib.util
from typing import Protocol

import numpy as np
from PIL import Image

from watermark_lab.core.model import WatermarkModel
from watermark_lab.core.types import BitArray, DecodeResult, EmbedResult, ImageArray


class TrustMarkBackend(Protocol):
    def schemaCapacity(self) -> int: ...

    def encode(
        self,
        image: Image.Image,
        payload: str,
        *,
        MODE: str,
        WM_STRENGTH: float,
    ) -> Image.Image: ...

    def decode(
        self,
        image: Image.Image,
        *,
        MODE: str,
        DETECTFIRST: bool,
        ROTATION: bool,
    ) -> tuple[str, bool, int]: ...


def trustmark_package_available() -> bool:
    return importlib.util.find_spec("trustmark") is not None


class TrustMarkQModel(WatermarkModel):
    """Adapter for Adobe's official TrustMark Q model in binary BCH_5 mode."""

    name = "trustmark_q"
    message_bits = 32
    variant = "Q"
    encoding_name = "BCH_5"

    def __init__(
        self,
        *,
        strength: float = 1.0,
        detect_first: bool = False,
        rotation_search: bool = False,
        verbose: bool = False,
        backend: TrustMarkBackend | None = None,
    ) -> None:
        if strength <= 0:
            raise ValueError("strength must be positive")
        self.strength = float(strength)
        self.detect_first = detect_first
        self.rotation_search = rotation_search
        self._backend = backend or self._load_official_backend(verbose)
        self.schema_capacity = int(self._backend.schemaCapacity())
        if self.schema_capacity < self.message_bits:
            raise RuntimeError(
                f"TrustMark schema capacity {self.schema_capacity} is below the required "
                f"{self.message_bits} bits"
            )

    @classmethod
    def _load_official_backend(cls, verbose: bool) -> TrustMarkBackend:
        try:
            from trustmark import TrustMark
        except ImportError as error:
            raise RuntimeError(
                "TrustMark is an optional dependency. Install the Windows research "
                "environment with: pip install -e \".[trustmark]\""
            ) from error
        return TrustMark(
            verbose=verbose,
            model_type=cls.variant,
            encoding_type=TrustMark.Encoding.BCH_5,
            loadBBoxDetector=False,
        )

    @staticmethod
    def _to_pil(image: ImageArray) -> Image.Image:
        return Image.fromarray(np.asarray(image, dtype=np.uint8))

    @staticmethod
    def _to_array(image: Image.Image) -> ImageArray:
        return np.ascontiguousarray(np.asarray(image.convert("RGB"), dtype=np.uint8))

    def encode(self, image: ImageArray, message: BitArray) -> EmbedResult:
        source = self.validate_image(image)
        bits = self.validate_message(message)
        payload = "".join(str(int(bit)) for bit in bits)
        encoded = self._backend.encode(
            self._to_pil(source),
            payload,
            MODE="binary",
            WM_STRENGTH=self.strength,
        )
        return EmbedResult(
            image=self._to_array(encoded),
            metadata={
                "variant": self.variant,
                "encoding": self.encoding_name,
                "schema_capacity": self.schema_capacity,
                "strength": self.strength,
            },
        )

    def decode(self, image: ImageArray) -> DecodeResult:
        source = self.validate_image(image)
        secret, present, schema = self._backend.decode(
            self._to_pil(source),
            MODE="binary",
            DETECTFIRST=self.detect_first,
            ROTATION=self.rotation_search,
        )
        recovered = [int(character) for character in str(secret) if character in "01"]
        recovered = (recovered + [0] * self.message_bits)[: self.message_bits]
        message = np.asarray(recovered, dtype=np.uint8)
        return DecodeResult(
            message=message,
            detected=bool(present),
            confidence=1.0 if present else 0.0,
            metadata={
                "variant": self.variant,
                "encoding": self.encoding_name,
                "schema": int(schema),
                "schema_capacity": self.schema_capacity,
                "raw_payload_bits": len(str(secret)),
                "confidence_note": "official API exposes a detection flag, not a probability",
            },
        )
