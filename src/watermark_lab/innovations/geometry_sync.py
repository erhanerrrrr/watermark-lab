from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from watermark_lab.core.types import DecodeResult, ImageArray
from watermark_lab.models.wam_adapter import WamModel, WamSpatialPrediction


@dataclass(frozen=True)
class GeometrySyncConfig:
    """Blind inverse-transform hypotheses used before WAM decoding."""

    rotation_corrections: tuple[float, ...] = (-10.0, -6.0, -3.0, 3.0, 6.0, 10.0)
    perspective_corrections: tuple[float, ...] = (0.03, 0.06, 0.10)
    fusion_top_k: int = 3
    score_temperature: float = 0.15
    minimum_score_improvement: float = 0.006
    minimum_border_evidence: float = 0.02
    search_strategy: str = "full"

    def __post_init__(self) -> None:
        if self.fusion_top_k < 1:
            raise ValueError("fusion_top_k must be positive")
        if self.score_temperature <= 0:
            raise ValueError("score_temperature must be positive")
        if self.minimum_score_improvement < 0:
            raise ValueError("minimum_score_improvement must be non-negative")
        if self.minimum_border_evidence < 0:
            raise ValueError("minimum_border_evidence must be non-negative")
        if self.search_strategy not in {"full", "coarse_to_fine"}:
            raise ValueError("search_strategy must be 'full' or 'coarse_to_fine'")
        if any(not -45.0 <= angle <= 45.0 for angle in self.rotation_corrections):
            raise ValueError("rotation corrections must be within [-45, 45]")
        if any(not 0.0 < value < 0.25 for value in self.perspective_corrections):
            raise ValueError("perspective corrections must be within (0, 0.25)")


@dataclass
class _Branch:
    name: str
    image: ImageArray
    prediction: WamSpatialPrediction
    pooled_logits: np.ndarray
    message: np.ndarray
    selected_fraction: float
    confidence: float
    agreement: float
    mean_margin: float
    minimum_margin: float
    score: float


def _to_array(image: Image.Image) -> ImageArray:
    return np.ascontiguousarray(np.asarray(image.convert("RGB"), dtype=np.uint8))


def correct_rotation(image: ImageArray, angle: float) -> ImageArray:
    pil_image = Image.fromarray(np.asarray(image, dtype=np.uint8), mode="RGB")
    fill = tuple(int(value) for value in np.median(image, axis=(0, 1)))
    return _to_array(
        pil_image.rotate(
            angle,
            resample=Image.Resampling.BICUBIC,
            expand=False,
            fillcolor=fill,
        )
    )


def _homography(source: np.ndarray, destination: np.ndarray) -> np.ndarray:
    system: list[list[float]] = []
    targets: list[float] = []
    for (source_x, source_y), (dest_x, dest_y) in zip(
        source,
        destination,
        strict=True,
    ):
        system.append(
            [
                source_x,
                source_y,
                1.0,
                0.0,
                0.0,
                0.0,
                -dest_x * source_x,
                -dest_x * source_y,
            ]
        )
        targets.append(dest_x)
        system.append(
            [
                0.0,
                0.0,
                0.0,
                source_x,
                source_y,
                1.0,
                -dest_y * source_x,
                -dest_y * source_y,
            ]
        )
        targets.append(dest_y)
    return np.append(
        np.linalg.solve(np.asarray(system), np.asarray(targets)),
        1.0,
    ).reshape(3, 3)


def correct_perspective(image: ImageArray, magnitude: float) -> ImageArray:
    """Map the protocol's trapezoid-shaped attacked image back to the full canvas."""

    height, width = image.shape[:2]
    max_x = float(width - 1)
    max_y = float(height - 1)
    source = np.array(((0, 0), (max_x, 0), (max_x, max_y), (0, max_y)), dtype=float)
    dx = max_x * magnitude
    dy = max_y * magnitude
    attacked_corners = np.array(
        ((dx, dy), (max_x - dx, 0), (max_x, max_y - dy), (0, max_y)),
        dtype=float,
    )
    # PIL expects output-to-input coefficients. For a canonical output canvas,
    # sample each original corner from its attacked-image location.
    matrix = _homography(source, attacked_corners)
    matrix /= matrix[2, 2]
    coefficients = tuple(float(value) for value in matrix.reshape(-1)[:8])
    pil_image = Image.fromarray(np.asarray(image, dtype=np.uint8), mode="RGB")
    fill = tuple(int(value) for value in np.median(image, axis=(0, 1)))
    return _to_array(
        pil_image.transform(
            (width, height),
            Image.Transform.PERSPECTIVE,
            coefficients,
            resample=Image.Resampling.BICUBIC,
            fillcolor=fill,
        )
    )


def geometry_border_evidence(
    image: ImageArray,
    *,
    corner_fraction: float = 0.15,
    color_tolerance: float = 12.0,
) -> float:
    """Estimate whether median-color padding at the corners suggests a warp.

    The benchmark rotations and perspective transforms retain the canvas and
    fill newly exposed pixels with the image median. JPEG and resizing soften
    that fill, so evidence is measured with a color tolerance and normalized by
    the same-color rate in the image center.
    """

    rgb = np.asarray(image, dtype=np.float32)
    height, width = rgb.shape[:2]
    corner_height = max(1, round(height * corner_fraction))
    corner_width = max(1, round(width * corner_fraction))
    median = np.median(rgb, axis=(0, 1))
    near_fill = np.max(np.abs(rgb - median[None, None, :]), axis=2) <= color_tolerance
    corners = np.zeros((height, width), dtype=bool)
    corners[:corner_height, :corner_width] = True
    corners[:corner_height, -corner_width:] = True
    corners[-corner_height:, :corner_width] = True
    corners[-corner_height:, -corner_width:] = True
    center = np.zeros((height, width), dtype=bool)
    top = height // 4
    bottom = max(top + 1, height - top)
    left = width // 4
    right = max(left + 1, width - left)
    center[top:bottom, left:right] = True
    corner_rate = float(np.mean(near_fill[corners]))
    center_rate = float(np.mean(near_fill[center]))
    return max(0.0, corner_rate - center_rate)


class GeometrySyncDecoder:
    """Blind geometric synchronization through scored WAM decoding branches."""

    def __init__(
        self,
        model: WamModel,
        *,
        config: GeometrySyncConfig | None = None,
    ) -> None:
        self.model = model
        self.config = config or GeometrySyncConfig()

    def candidate_images(self, image: ImageArray) -> list[tuple[str, ImageArray]]:
        source = self.model.validate_image(image)
        candidates: list[tuple[str, ImageArray]] = [("identity", np.array(source, copy=True))]
        candidates.extend(
            (f"rotation_{angle:+g}", correct_rotation(source, angle))
            for angle in self.config.rotation_corrections
        )
        candidates.extend(
            (f"perspective_{magnitude:g}", correct_perspective(source, magnitude))
            for magnitude in self.config.perspective_corrections
        )
        return candidates

    def _score(self, name: str, image: ImageArray) -> _Branch:
        prediction = self.model.predict_spatial(image)
        detection = prediction.detection_probabilities
        selected = detection > self.model.detection_threshold
        selected_fraction = float(np.mean(selected))
        if np.any(selected):
            logits = prediction.bit_logits[:, selected]
            pooled = np.mean(logits, axis=1)
            message = (pooled > self.model.bit_logit_threshold).astype(np.uint8)
            confidence = float(np.mean(detection[selected]))
            agreement = float(
                np.mean(
                    (logits > self.model.bit_logit_threshold)
                    == message[:, None]
                )
            )
        else:
            pooled = np.full(self.model.message_bits, -np.inf, dtype=np.float32)
            message = np.zeros(self.model.message_bits, dtype=np.uint8)
            confidence = float(np.mean(detection))
            agreement = 0.0
        margins = np.abs(pooled - self.model.bit_logit_threshold)
        finite_margins = margins[np.isfinite(margins)]
        mean_margin = float(np.mean(finite_margins)) if finite_margins.size else 0.0
        minimum_margin = float(np.min(finite_margins)) if finite_margins.size else 0.0
        margin_score = float(np.tanh(mean_margin / 2.0))
        coverage_score = min(1.0, selected_fraction / 0.75)
        score = (
            0.30 * confidence
            + 0.30 * agreement
            + 0.30 * margin_score
            + 0.10 * coverage_score
        )
        return _Branch(
            name=name,
            image=image,
            prediction=prediction,
            pooled_logits=np.ascontiguousarray(pooled, dtype=np.float32),
            message=message,
            selected_fraction=selected_fraction,
            confidence=confidence,
            agreement=agreement,
            mean_margin=mean_margin,
            minimum_margin=minimum_margin,
            score=score,
        )

    @staticmethod
    def _middle_by_magnitude(
        candidates: list[tuple[str, ImageArray]],
    ) -> tuple[str, ImageArray] | None:
        if not candidates:
            return None
        ordered = sorted(
            candidates,
            key=lambda item: abs(float(item[0].rsplit("_", maxsplit=1)[1])),
        )
        return ordered[len(ordered) // 2]

    def _coarse_to_fine_branches(
        self,
        candidates: list[tuple[str, ImageArray]],
    ) -> tuple[list[_Branch], str]:
        rotations = [item for item in candidates if item[0].startswith("rotation_")]
        negative = [
            item
            for item in rotations
            if float(item[0].rsplit("_", maxsplit=1)[1]) < 0
        ]
        positive = [
            item
            for item in rotations
            if float(item[0].rsplit("_", maxsplit=1)[1]) > 0
        ]
        perspectives = [
            item for item in candidates if item[0].startswith("perspective_")
        ]
        coarse = [
            item
            for item in (
                self._middle_by_magnitude(negative),
                self._middle_by_magnitude(positive),
                self._middle_by_magnitude(perspectives),
            )
            if item is not None
        ]
        coarse_branches = [self._score(name, image) for name, image in coarse]
        if not coarse_branches:
            return [], "none"
        winner = max(coarse_branches, key=lambda branch: branch.score)
        if winner.name.startswith("perspective_"):
            family = "perspective"
            refinement = perspectives
        else:
            angle = float(winner.name.rsplit("_", maxsplit=1)[1])
            family = "rotation_negative" if angle < 0 else "rotation_positive"
            refinement = negative if angle < 0 else positive
        coarse_names = {name for name, _ in coarse}
        refined_branches = [
            self._score(name, image)
            for name, image in refinement
            if name not in coarse_names
        ]
        return coarse_branches + refined_branches, family

    def decode(self, image: ImageArray) -> DecodeResult:
        candidates = self.candidate_images(image)
        border_evidence = geometry_border_evidence(image)
        identity_name, identity_image = candidates[0]
        identity = self._score(identity_name, identity_image)
        search_skipped = border_evidence < self.config.minimum_border_evidence
        branches = [identity]
        refinement_family = "none"
        if not search_skipped:
            if self.config.search_strategy == "full":
                branches.extend(
                    self._score(name, candidate) for name, candidate in candidates[1:]
                )
                refinement_family = "all"
            else:
                refined, refinement_family = self._coarse_to_fine_branches(
                    candidates[1:]
                )
                branches.extend(refined)
        branches.sort(key=lambda branch: branch.score, reverse=True)
        best_candidate = branches[0]
        accept_geometry = (
            best_candidate.name != "identity"
            and best_candidate.score - identity.score
            >= self.config.minimum_score_improvement
            and border_evidence >= self.config.minimum_border_evidence
        )
        if not accept_geometry:
            branches.remove(identity)
            branches.insert(0, identity)
            top = [identity]
        else:
            top = branches[: min(self.config.fusion_top_k, len(branches))]
        scores = np.asarray([branch.score for branch in top], dtype=np.float64)
        scores -= float(np.max(scores))
        weights = np.exp(scores / self.config.score_temperature)
        weights /= np.sum(weights)
        fused_logits = np.sum(
            np.stack([branch.pooled_logits for branch in top], axis=0)
            * weights[:, None],
            axis=0,
        )
        message = (fused_logits > self.model.bit_logit_threshold).astype(np.uint8)
        best = top[0]
        detected = (
            best.selected_fraction >= self.model.minimum_detected_fraction
        )
        margins = np.abs(fused_logits - self.model.bit_logit_threshold)
        branch_records = [
            {
                "name": branch.name,
                "score": branch.score,
                "selected_fraction": branch.selected_fraction,
                "confidence": branch.confidence,
                "agreement": branch.agreement,
                "mean_bit_margin": branch.mean_margin,
                "minimum_bit_margin": branch.minimum_margin,
            }
            for branch in branches
        ]
        return DecodeResult(
            message=np.ascontiguousarray(message),
            detected=detected,
            confidence=best.confidence,
            localization=np.ascontiguousarray(
                best.prediction.detection_probabilities,
                dtype=np.float32,
            ),
            metadata={
                "variant": "wam_mit_geometry_sync",
                "pooling": "blind-transform-search-soft-fusion",
                "selected_transform": best.name,
                "selected_score": best.score,
                "identity_score": identity.score,
                "score_improvement": best.score - identity.score,
                "geometry_candidate_accepted": accept_geometry,
                "geometry_search_skipped": search_skipped,
                "border_geometry_evidence": border_evidence,
                "minimum_score_improvement": self.config.minimum_score_improvement,
                "minimum_border_evidence": self.config.minimum_border_evidence,
                "candidate_count": len(branches),
                "configured_candidate_count": len(candidates),
                "search_strategy": self.config.search_strategy,
                "refinement_family": refinement_family,
                "fusion_top_k": len(top),
                "fusion_weights": [float(value) for value in weights],
                "fused_transforms": [branch.name for branch in top],
                "detected_fraction": best.selected_fraction,
                "minimum_absolute_bit_margin": float(np.min(margins)),
                "mean_absolute_bit_margin": float(np.mean(margins)),
                "geometry_branches": branch_records,
            },
        )
