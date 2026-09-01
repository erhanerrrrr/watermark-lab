from __future__ import annotations

from functools import lru_cache

import numpy as np

from watermark_lab.core.model import WatermarkModel
from watermark_lab.core.types import BitArray, DecodeResult, EmbedResult, ImageArray


def _integer_to_bits(value: int, width: int) -> BitArray:
    return np.array(
        [(value >> shift) & 1 for shift in range(width - 1, -1, -1)],
        dtype=np.uint8,
    )


@lru_cache(maxsize=1)
def _dct_matrix() -> np.ndarray:
    size = 8
    positions = np.arange(size, dtype=np.float64)
    frequencies = positions[:, None]
    matrix = np.cos(np.pi * (2.0 * positions + 1.0) * frequencies / (2.0 * size))
    matrix[0] *= np.sqrt(1.0 / size)
    matrix[1:] *= np.sqrt(2.0 / size)
    return matrix


def _dct2(block: np.ndarray) -> np.ndarray:
    matrix = _dct_matrix()
    return matrix @ block @ matrix.T


def _idct2(coefficients: np.ndarray) -> np.ndarray:
    matrix = _dct_matrix()
    return matrix.T @ coefficients @ matrix


def _rgb_to_ycbcr(image: ImageArray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rgb = image.astype(np.float64)
    red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    y = 0.299 * red + 0.587 * green + 0.114 * blue
    cb = -0.168736 * red - 0.331264 * green + 0.5 * blue + 128.0
    cr = 0.5 * red - 0.418688 * green - 0.081312 * blue + 128.0
    return y, cb, cr


def _ycbcr_to_rgb(y: np.ndarray, cb: np.ndarray, cr: np.ndarray) -> ImageArray:
    cb_offset = cb - 128.0
    cr_offset = cr - 128.0
    red = y + 1.402 * cr_offset
    green = y - 0.344136 * cb_offset - 0.714136 * cr_offset
    blue = y + 1.772 * cb_offset
    rgb = np.stack((red, green, blue), axis=2)
    return np.ascontiguousarray(np.clip(np.rint(rgb), 0, 255).astype(np.uint8))


def _haar_forward(channel: np.ndarray) -> tuple[np.ndarray, ...]:
    even_height = channel.shape[0] - channel.shape[0] % 2
    even_width = channel.shape[1] - channel.shape[1] % 2
    working = channel[:even_height, :even_width]
    top_left = working[0::2, 0::2]
    top_right = working[0::2, 1::2]
    bottom_left = working[1::2, 0::2]
    bottom_right = working[1::2, 1::2]
    ll = (top_left + top_right + bottom_left + bottom_right) / 2.0
    lh = (top_left - top_right + bottom_left - bottom_right) / 2.0
    hl = (top_left + top_right - bottom_left - bottom_right) / 2.0
    hh = (top_left - top_right - bottom_left + bottom_right) / 2.0
    return ll, lh, hl, hh


def _haar_inverse(
    ll: np.ndarray,
    lh: np.ndarray,
    hl: np.ndarray,
    hh: np.ndarray,
    original: np.ndarray,
) -> np.ndarray:
    restored = original.copy()
    even_height = ll.shape[0] * 2
    even_width = ll.shape[1] * 2
    restored[:even_height:2, :even_width:2] = (ll + lh + hl + hh) / 2.0
    restored[:even_height:2, 1:even_width:2] = (ll - lh + hl - hh) / 2.0
    restored[1:even_height:2, :even_width:2] = (ll + lh - hl - hh) / 2.0
    restored[1:even_height:2, 1:even_width:2] = (ll - lh - hl + hh) / 2.0
    return restored


class DwtDctWatermarkModel(WatermarkModel):
    """Blind Haar-DWT/DCT baseline using differential coefficient modulation.

    The payload is embedded repeatedly in seeded 8x8 blocks of the luminance LL
    sub-band. A 16-bit synchronization word enables blind watermark detection.
    This implementation intentionally has no learned parameters, making it a
    reproducible traditional baseline for comparison with deep models.
    """

    name = "dwt_dct"
    message_bits = 32
    sync_bits = _integer_to_bits(0xC39A, 16)
    coefficient_a = (2, 3)
    coefficient_b = (3, 2)

    def __init__(
        self,
        strength: float = 60.0,
        max_repetition: int = 5,
        seed: int = 731992,
        detection_threshold: float = 0.9375,
    ) -> None:
        if strength <= 0:
            raise ValueError("strength must be positive")
        if max_repetition < 1 or max_repetition % 2 == 0:
            raise ValueError("max_repetition must be a positive odd number")
        if not 0.5 <= detection_threshold <= 1.0:
            raise ValueError("detection_threshold must be between 0.5 and 1.0")
        self.strength = float(strength)
        self.max_repetition = max_repetition
        self.seed = seed
        self.detection_threshold = detection_threshold

    @property
    def payload_bits(self) -> int:
        return int(self.sync_bits.size + self.message_bits)

    def _layout(self, ll_shape: tuple[int, int]) -> tuple[np.ndarray, int, int]:
        block_rows = ll_shape[0] // 8
        block_columns = ll_shape[1] // 8
        block_count = block_rows * block_columns
        possible_repetition = min(self.max_repetition, block_count // self.payload_bits)
        repetition = (
            possible_repetition
            if possible_repetition % 2 == 1
            else possible_repetition - 1
        )
        if repetition < 1:
            raise ValueError(
                "DWT-DCT requires at least 48 LL blocks; use an image of roughly "
                "112x112 pixels or larger"
            )
        used_blocks = self.payload_bits * repetition
        generator = np.random.default_rng(
            self.seed + ll_shape[0] * 1_000_003 + ll_shape[1] * 10_007
        )
        indices = generator.choice(block_count, size=used_blocks, replace=False)
        return indices, repetition, block_columns

    @staticmethod
    def _block_view(ll: np.ndarray, index: int, block_columns: int) -> np.ndarray:
        row = (index // block_columns) * 8
        column = (index % block_columns) * 8
        return ll[row : row + 8, column : column + 8]

    def encode(self, image: ImageArray, message: BitArray) -> EmbedResult:
        source = self.validate_image(image)
        bits = self.validate_message(message)
        y, cb, cr = _rgb_to_ycbcr(source)
        ll, lh, hl, hh = _haar_forward(y)
        positions, repetition, block_columns = self._layout(ll.shape)
        payload = np.concatenate((self.sync_bits, bits))

        modified_ll = ll.copy()
        for bit, block_index in zip(np.repeat(payload, repetition), positions, strict=True):
            block = self._block_view(modified_ll, int(block_index), block_columns)
            coefficients = _dct2(block)
            first = float(coefficients[self.coefficient_a])
            second = float(coefficients[self.coefficient_b])
            difference = first - second
            target = self.strength if bit else -self.strength
            if (bit and difference < target) or (not bit and difference > target):
                adjustment = (target - difference) / 2.0
                coefficients[self.coefficient_a] += adjustment
                coefficients[self.coefficient_b] -= adjustment
                block[:] = _idct2(coefficients)

        watermarked_y = _haar_inverse(modified_ll, lh, hl, hh, y)
        output = _ycbcr_to_rgb(watermarked_y, cb, cr)
        return EmbedResult(
            image=output,
            metadata={
                "transform": "haar-dwt-ll+dct8x8",
                "strength": self.strength,
                "repetition": repetition,
                "sync_bits": int(self.sync_bits.size),
            },
        )

    def decode(self, image: ImageArray) -> DecodeResult:
        source = self.validate_image(image)
        y, _, _ = _rgb_to_ycbcr(source)
        ll, _, _, _ = _haar_forward(y)
        positions, repetition, block_columns = self._layout(ll.shape)

        differences: list[float] = []
        raw_bits: list[int] = []
        for block_index in positions:
            block = self._block_view(ll, int(block_index), block_columns)
            coefficients = _dct2(block)
            difference = float(
                coefficients[self.coefficient_a] - coefficients[self.coefficient_b]
            )
            differences.append(difference)
            raw_bits.append(int(difference >= 0.0))

        bit_matrix = np.asarray(raw_bits, dtype=np.uint8).reshape(
            self.payload_bits, repetition
        )
        decoded = (bit_matrix.sum(axis=1) > repetition // 2).astype(np.uint8)
        sync = decoded[: self.sync_bits.size]
        message = decoded[self.sync_bits.size :]
        sync_score = float(np.mean(sync == self.sync_bits))
        difference_matrix = np.abs(np.asarray(differences)).reshape(
            self.payload_bits, repetition
        )
        confidence = float(np.mean(np.clip(difference_matrix / self.strength, 0.0, 1.0)))
        return DecodeResult(
            message=message,
            detected=sync_score >= self.detection_threshold,
            confidence=confidence,
            metadata={
                "sync_score": sync_score,
                "strength": self.strength,
                "repetition": repetition,
            },
        )
