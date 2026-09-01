from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from watermark_lab.core.types import BitArray, DecodeResult, EmbedResult, ImageArray


class WatermarkModel(ABC):
    """Common interface implemented by every comparison and proposed model."""

    name: str
    message_bits: int

    @abstractmethod
    def encode(self, image: ImageArray, message: BitArray) -> EmbedResult:
        """Embed a binary message into an RGB uint8 image."""

    @abstractmethod
    def decode(self, image: ImageArray) -> DecodeResult:
        """Detect and decode a watermark from an RGB uint8 image."""

    def validate_image(self, image: ImageArray) -> ImageArray:
        array = np.asarray(image)
        if array.dtype != np.uint8:
            raise ValueError(f"image dtype must be uint8, got {array.dtype}")
        if array.ndim != 3 or array.shape[2] != 3:
            raise ValueError(f"image must have shape HxWx3, got {array.shape}")
        return np.ascontiguousarray(array)

    def validate_message(self, message: BitArray) -> BitArray:
        bits = np.asarray(message, dtype=np.uint8).reshape(-1)
        if bits.size != self.message_bits:
            raise ValueError(
                f"{self.name} requires {self.message_bits} bits, got {bits.size}"
            )
        if not np.all((bits == 0) | (bits == 1)):
            raise ValueError("message must contain only 0 and 1")
        return bits
