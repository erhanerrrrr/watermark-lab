from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from watermark_lab.core.types import BitArray, DecodeResult, EmbedResult, ImageArray
from watermark_lab.metrics.image_quality import psnr
from watermark_lab.metrics.message import bit_accuracy, complete_recovery


class StrengthControllableModel(Protocol):
    strength: float
    message_bits: int

    def encode(self, image: ImageArray, message: BitArray) -> EmbedResult: ...

    def decode(self, image: ImageArray) -> DecodeResult: ...


@dataclass(frozen=True)
class AdaptiveStrengthConfig:
    """Quality-constrained feedback controller settings.

    The controller first normalizes every image to ``target_psnr_db``. If the
    clean decoder remains uncertain, it spends at most ``minimum_psnr_db`` of
    the per-image quality budget to strengthen that image.
    """

    target_psnr_db: float = 40.0
    minimum_psnr_db: float = 38.0
    minimum_strength: float = 0.25
    maximum_strength: float = 8.0
    psnr_tolerance_db: float = 0.15
    quality_refinement_steps: int = 2
    robustness_steps: int = 4
    required_minimum_bit_margin: float = 0.20

    def __post_init__(self) -> None:
        if self.minimum_psnr_db >= self.target_psnr_db:
            raise ValueError("minimum_psnr_db must be below target_psnr_db")
        if self.minimum_strength <= 0 or self.maximum_strength <= self.minimum_strength:
            raise ValueError("invalid adaptive strength bounds")
        if self.psnr_tolerance_db <= 0:
            raise ValueError("psnr_tolerance_db must be positive")
        if self.quality_refinement_steps < 0:
            raise ValueError("quality_refinement_steps must be non-negative")
        if self.robustness_steps < 2:
            raise ValueError("robustness_steps must be at least 2")


@dataclass
class _Evaluation:
    strength: float
    embedded: EmbedResult
    psnr_db: float
    decoded: DecodeResult | None = None
    bit_accuracy: float = 0.0
    complete_recovery: bool = False
    minimum_bit_margin: float = 0.0


def content_features(image: ImageArray) -> dict[str, float]:
    """Return inexpensive, deterministic features for audit and later regression."""

    rgb = np.asarray(image, dtype=np.float32) / 255.0
    luminance = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]
    dx = np.diff(luminance, axis=1)
    dy = np.diff(luminance, axis=0)
    gradient_energy = 0.5 * (float(np.mean(np.abs(dx))) + float(np.mean(np.abs(dy))))
    inner = luminance[1:-1, 1:-1]
    if inner.size:
        laplacian = (
            -4.0 * inner
            + luminance[:-2, 1:-1]
            + luminance[2:, 1:-1]
            + luminance[1:-1, :-2]
            + luminance[1:-1, 2:]
        )
        laplacian_variance = float(np.var(laplacian))
    else:
        laplacian_variance = 0.0
    histogram, _ = np.histogram(luminance, bins=32, range=(0.0, 1.0))
    probabilities = histogram.astype(np.float64) / max(1, luminance.size)
    nonzero = probabilities[probabilities > 0]
    entropy = float(-np.sum(nonzero * np.log2(nonzero)) / np.log2(32.0))
    return {
        "luminance_standard_deviation": float(np.std(luminance)),
        "gradient_energy": gradient_energy,
        "laplacian_variance": laplacian_variance,
        "normalized_luminance_entropy": entropy,
    }


class ContentAdaptiveStrengthController:
    """Select WAM strength per image with decoder feedback and a PSNR floor."""

    def __init__(
        self,
        model: StrengthControllableModel,
        *,
        base_strength: float,
        config: AdaptiveStrengthConfig | None = None,
    ) -> None:
        if base_strength <= 0:
            raise ValueError("base_strength must be positive")
        self.model = model
        self.base_strength = float(base_strength)
        self.config = config or AdaptiveStrengthConfig()

    def _bounded(self, strength: float) -> float:
        return float(
            np.clip(
                strength,
                self.config.minimum_strength,
                self.config.maximum_strength,
            )
        )

    def _embed(
        self,
        image: ImageArray,
        message: BitArray,
        strength: float,
    ) -> _Evaluation:
        selected = self._bounded(strength)
        self.model.strength = selected
        embedded = self.model.encode(image, message)
        return _Evaluation(
            strength=selected,
            embedded=embedded,
            psnr_db=psnr(image, embedded.image),
        )

    def _refine_for_quality(
        self,
        image: ImageArray,
        message: BitArray,
        initial_strength: float,
        target_psnr_db: float,
    ) -> _Evaluation:
        evaluation = self._embed(image, message, initial_strength)
        for _ in range(self.config.quality_refinement_steps):
            error = evaluation.psnr_db - target_psnr_db
            if abs(error) <= self.config.psnr_tolerance_db:
                break
            # For additive watermark residuals MSE is approximately proportional
            # to strength squared, hence delta-PSNR ~= -20 log10(strength ratio).
            adjusted = evaluation.strength * 10.0 ** (error / 20.0)
            adjusted = self._bounded(adjusted)
            if np.isclose(adjusted, evaluation.strength):
                break
            evaluation = self._embed(image, message, adjusted)
        return evaluation

    def _decode_evaluation(
        self,
        evaluation: _Evaluation,
        expected: BitArray,
    ) -> _Evaluation:
        if evaluation.decoded is not None:
            return evaluation
        decoded = self.model.decode(evaluation.embedded.image)
        evaluation.decoded = decoded
        evaluation.bit_accuracy = bit_accuracy(expected, decoded.message)
        evaluation.complete_recovery = complete_recovery(expected, decoded.message)
        evaluation.minimum_bit_margin = float(
            decoded.metadata.get("minimum_absolute_bit_margin", 0.0)
        )
        return evaluation

    def encode(self, image: ImageArray, message: BitArray) -> EmbedResult:
        features = content_features(image)
        first = self._embed(image, message, self.base_strength)
        target_guess = first.strength * 10.0 ** (
            (first.psnr_db - self.config.target_psnr_db) / 20.0
        )
        target = self._refine_for_quality(
            image,
            message,
            target_guess,
            self.config.target_psnr_db,
        )
        target = self._decode_evaluation(target, message)
        evaluations = [target]

        selected = target
        target_is_robust = (
            target.complete_recovery
            and target.minimum_bit_margin >= self.config.required_minimum_bit_margin
        )
        if not target_is_robust:
            floor_guess = target.strength * 10.0 ** (
                (self.config.target_psnr_db - self.config.minimum_psnr_db) / 20.0
            )
            floor = self._refine_for_quality(
                image,
                message,
                floor_guess,
                self.config.minimum_psnr_db,
            )
            strengths = np.linspace(
                target.strength,
                max(target.strength, floor.strength),
                self.config.robustness_steps,
            )[1:]
            for strength in strengths:
                candidate = self._decode_evaluation(
                    self._embed(image, message, float(strength)),
                    message,
                )
                if candidate.psnr_db + self.config.psnr_tolerance_db < (
                    self.config.minimum_psnr_db
                ):
                    continue
                evaluations.append(candidate)
                selected = max(
                    evaluations,
                    key=lambda item: (
                        item.complete_recovery,
                        item.bit_accuracy,
                        item.minimum_bit_margin,
                        item.psnr_db,
                    ),
                )
                if (
                    candidate.complete_recovery
                    and candidate.minimum_bit_margin
                    >= self.config.required_minimum_bit_margin
                ):
                    selected = candidate
                    break

        self.model.strength = selected.strength
        records = [
            {
                "strength": item.strength,
                "psnr_db": item.psnr_db,
                "bit_accuracy": item.bit_accuracy,
                "complete_recovery": item.complete_recovery,
                "minimum_bit_margin": item.minimum_bit_margin,
            }
            for item in evaluations
        ]
        metadata = dict(selected.embedded.metadata)
        metadata.update(
            {
                "adaptive_strength": True,
                "base_strength": self.base_strength,
                "selected_strength": selected.strength,
                "target_psnr_db": self.config.target_psnr_db,
                "minimum_psnr_db": self.config.minimum_psnr_db,
                "selected_psnr_db": selected.psnr_db,
                "quality_budget_spent_db": max(
                    0.0,
                    self.config.target_psnr_db - selected.psnr_db,
                ),
                "content_features": features,
                "strength_search": records,
            }
        )
        return EmbedResult(image=selected.embedded.image, metadata=metadata)
