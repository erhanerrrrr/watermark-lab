from __future__ import annotations

import numpy as np

from watermark_lab.core.model import WatermarkModel
from watermark_lab.core.types import BitArray, DecodeResult, EmbedResult, ImageArray


def _integer_to_bits(value: int, width: int) -> BitArray:
    return np.array([(value >> shift) & 1 for shift in range(width - 1, -1, -1)], dtype=np.uint8)


class LSBReferenceModel(WatermarkModel):
    """Small deterministic model used only to validate the experiment pipeline."""

    name = "lsb_reference"
    message_bits = 32
    sync_bits = _integer_to_bits(0xA55A, 16)

    def __init__(self, repetition: int = 9, seed: int = 20260901) -> None:
        if repetition < 1 or repetition % 2 == 0:
            raise ValueError("repetition must be a positive odd number")
        self.repetition = repetition
        self.seed = seed

    @property
    def payload_bits(self) -> int:
        return int(self.sync_bits.size + self.message_bits)

    def _positions(self, flat_size: int) -> np.ndarray:
        required = self.payload_bits * self.repetition
        if flat_size < required:
            raise ValueError(f"image has {flat_size} channels but {required} are required")
        rng = np.random.default_rng(self.seed + flat_size)
        return rng.choice(flat_size, size=required, replace=False)

    def encode(self, image: ImageArray, message: BitArray) -> EmbedResult:
        source = self.validate_image(image)
        bits = self.validate_message(message)
        payload = np.concatenate((self.sync_bits, bits))
        repeated = np.repeat(payload, self.repetition)

        output = source.copy()
        flat = output.reshape(-1)
        positions = self._positions(flat.size)
        flat[positions] = (flat[positions] & 0xFE) | repeated
        return EmbedResult(
            image=output,
            metadata={"repetition": self.repetition, "sync_bits": int(self.sync_bits.size)},
        )

    def decode(self, image: ImageArray) -> DecodeResult:
        source = self.validate_image(image)
        flat = source.reshape(-1)
        positions = self._positions(flat.size)
        repeated = (flat[positions] & 1).reshape(self.payload_bits, self.repetition)
        ones = repeated.sum(axis=1)
        decoded = (ones > self.repetition // 2).astype(np.uint8)

        sync = decoded[: self.sync_bits.size]
        message = decoded[self.sync_bits.size :]
        sync_score = float(np.mean(sync == self.sync_bits))
        bit_certainty = np.maximum(ones, self.repetition - ones) / self.repetition
        confidence = float(np.mean(bit_certainty))
        return DecodeResult(
            message=message,
            detected=sync_score >= 0.875,
            confidence=confidence,
            metadata={"sync_score": sync_score, "repetition": self.repetition},
        )
