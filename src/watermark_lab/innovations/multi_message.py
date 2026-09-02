from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from watermark_lab.core.types import BitArray, EmbedResult, ImageArray
from watermark_lab.models.wam_adapter import WamModel, WamSpatialPrediction


class RegionalWatermarkModel(Protocol):
    message_bits: int

    def validate_image(self, image: ImageArray) -> ImageArray: ...

    def validate_message(self, message: BitArray) -> BitArray: ...

    def encode(self, image: ImageArray, message: BitArray) -> EmbedResult: ...


@dataclass(frozen=True)
class MultiMessageConfig:
    """Adaptive soft clustering parameters for WAM pixel predictions."""

    detection_threshold: float = 0.5
    bit_logit_threshold: float = 0.0
    bit_probability_temperature: float = 1.0
    maximum_messages: int = 4
    candidate_limit: int = 512
    seed_hamming_radius: int = 1
    minimum_message_hamming_separation: int = 5
    minimum_cluster_pixels: int = 96
    minimum_cluster_fraction: float = 0.005
    maximum_soft_hamming: float = 0.32
    assignment_temperature: float = 0.08
    refinement_iterations: int = 5
    seed_prior_strength: float = 2.0
    localization_threshold: float = 0.25

    def __post_init__(self) -> None:
        if not 0.0 < self.detection_threshold < 1.0:
            raise ValueError("detection_threshold must be in (0, 1)")
        if self.bit_probability_temperature <= 0:
            raise ValueError("bit_probability_temperature must be positive")
        if self.maximum_messages < 1:
            raise ValueError("maximum_messages must be positive")
        if self.candidate_limit < self.maximum_messages:
            raise ValueError("candidate_limit must cover maximum_messages")
        if not 0 <= self.seed_hamming_radius <= 32:
            raise ValueError("seed_hamming_radius must be within [0, 32]")
        if not 1 <= self.minimum_message_hamming_separation <= 32:
            raise ValueError("minimum_message_hamming_separation must be within [1, 32]")
        if self.minimum_cluster_pixels < 1:
            raise ValueError("minimum_cluster_pixels must be positive")
        if not 0.0 <= self.minimum_cluster_fraction <= 1.0:
            raise ValueError("minimum_cluster_fraction must be in [0, 1]")
        if not 0.0 < self.maximum_soft_hamming < 1.0:
            raise ValueError("maximum_soft_hamming must be in (0, 1)")
        if self.assignment_temperature <= 0:
            raise ValueError("assignment_temperature must be positive")
        if self.refinement_iterations < 1:
            raise ValueError("refinement_iterations must be positive")
        if self.seed_prior_strength < 0:
            raise ValueError("seed_prior_strength must be non-negative")
        if not 0.0 < self.localization_threshold < 1.0:
            raise ValueError("localization_threshold must be in (0, 1)")


@dataclass
class MultiMessageResult:
    messages: np.ndarray
    confidences: np.ndarray
    support_fractions: np.ndarray
    localizations: np.ndarray
    label_map: np.ndarray
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return int(self.messages.shape[0])


@dataclass
class MultiEmbedResult:
    image: ImageArray
    messages: np.ndarray
    masks: np.ndarray
    metadata: dict[str, Any] = field(default_factory=dict)


def rectangular_region_masks(
    height: int,
    width: int,
    count: int,
    *,
    margin_fraction: float = 0.04,
    gap_fraction: float = 0.02,
) -> np.ndarray:
    """Create deterministic, non-overlapping regions for 1--4 messages."""

    if height < 8 or width < 8:
        raise ValueError("multi-message images must be at least 8x8")
    if not 1 <= count <= 4:
        raise ValueError("count must be within [1, 4]")
    if not 0.0 <= margin_fraction < 0.25:
        raise ValueError("margin_fraction must be within [0, 0.25)")
    if not 0.0 <= gap_fraction < 0.25:
        raise ValueError("gap_fraction must be within [0, 0.25)")

    margin_y = max(1, round(height * margin_fraction))
    margin_x = max(1, round(width * margin_fraction))
    gap_y = max(1, round(height * gap_fraction))
    gap_x = max(1, round(width * gap_fraction))
    top, bottom = margin_y, height - margin_y
    left, right = margin_x, width - margin_x
    middle_y = height // 2
    middle_x = width // 2

    if count == 1:
        boxes = ((top, bottom, left, right),)
    elif count == 2:
        boxes = (
            (top, bottom, left, middle_x - gap_x // 2),
            (top, bottom, middle_x + (gap_x + 1) // 2, right),
        )
    elif count == 3:
        first = left + (right - left) // 3
        second = left + 2 * (right - left) // 3
        boxes = (
            (top, bottom, left, first - gap_x // 2),
            (top, bottom, first + (gap_x + 1) // 2, second - gap_x // 2),
            (top, bottom, second + (gap_x + 1) // 2, right),
        )
    else:
        boxes = (
            (top, middle_y - gap_y // 2, left, middle_x - gap_x // 2),
            (top, middle_y - gap_y // 2, middle_x + (gap_x + 1) // 2, right),
            (middle_y + (gap_y + 1) // 2, bottom, left, middle_x - gap_x // 2),
            (
                middle_y + (gap_y + 1) // 2,
                bottom,
                middle_x + (gap_x + 1) // 2,
                right,
            ),
        )
    masks = np.zeros((count, height, width), dtype=bool)
    for index, (y0, y1, x0, x1) in enumerate(boxes):
        if y1 <= y0 or x1 <= x0:
            raise ValueError("image is too small for the requested region layout")
        masks[index, y0:y1, x0:x1] = True
    return masks


def small_patch_region_masks(
    height: int,
    width: int,
    *,
    patch_fraction: float = 0.04,
    margin_fraction: float = 0.04,
) -> np.ndarray:
    """Create one dominant region and one sub-3000-pixel patch at 256x256."""

    if height < 16 or width < 16:
        raise ValueError("small-patch images must be at least 16x16")
    if not 0.01 <= patch_fraction <= 0.20:
        raise ValueError("patch_fraction must be within [0.01, 0.20]")
    margin_y = max(1, round(height * margin_fraction))
    margin_x = max(1, round(width * margin_fraction))
    interior = np.zeros((height, width), dtype=bool)
    interior[margin_y : height - margin_y, margin_x : width - margin_x] = True
    patch_height = max(2, round(height * np.sqrt(patch_fraction)))
    patch_width = max(2, round(width * np.sqrt(patch_fraction)))
    top = height // 2 - patch_height // 2
    left = 3 * width // 4 - patch_width // 2
    patch = np.zeros((height, width), dtype=bool)
    patch[top : top + patch_height, left : left + patch_width] = True
    patch &= interior
    dominant = interior & ~patch
    return np.stack((dominant, patch))


def embed_multiple_regions(
    model: RegionalWatermarkModel,
    image: ImageArray,
    messages: np.ndarray,
    masks: np.ndarray,
) -> MultiEmbedResult:
    """Compose independently generated WAM residuals inside disjoint masks."""

    source = model.validate_image(image)
    bit_matrix = np.asarray(messages, dtype=np.uint8)
    region_masks = np.asarray(masks, dtype=bool)
    if bit_matrix.ndim != 2 or bit_matrix.shape[1] != model.message_bits:
        raise ValueError(f"messages must have shape Kx{model.message_bits}")
    if region_masks.shape != (bit_matrix.shape[0], *source.shape[:2]):
        raise ValueError("masks must have shape KxHxW and match the image")
    if np.any(np.sum(region_masks, axis=0) > 1):
        raise ValueError("multi-message masks must not overlap")
    if np.any(np.sum(region_masks, axis=(1, 2)) == 0):
        raise ValueError("every message mask must contain pixels")

    output = np.array(source, copy=True)
    embedding_metadata: list[dict[str, Any]] = []
    for message, mask in zip(bit_matrix, region_masks, strict=True):
        bits = model.validate_message(message)
        embedded = model.encode(source, bits)
        output[mask] = embedded.image[mask]
        embedding_metadata.append(dict(embedded.metadata))
    return MultiEmbedResult(
        image=np.ascontiguousarray(output),
        messages=np.ascontiguousarray(bit_matrix),
        masks=np.ascontiguousarray(region_masks),
        metadata={
            "message_count": int(bit_matrix.shape[0]),
            "mask_fractions": [float(np.mean(mask)) for mask in region_masks],
            "embeddings": embedding_metadata,
        },
    )


def _sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _empty_result(height: int, width: int, bits: int, **metadata: Any) -> MultiMessageResult:
    return MultiMessageResult(
        messages=np.empty((0, bits), dtype=np.uint8),
        confidences=np.empty(0, dtype=np.float32),
        support_fractions=np.empty(0, dtype=np.float32),
        localizations=np.empty((0, height, width), dtype=np.float32),
        label_map=np.full((height, width), -1, dtype=np.int16),
        metadata=metadata,
    )


class AdaptiveSoftMessageClusterer:
    """Cluster WAM pixels using soft bit evidence and adaptive area support."""

    def __init__(
        self,
        model: WamModel | None = None,
        *,
        config: MultiMessageConfig | None = None,
        message_bits: int = 32,
    ) -> None:
        self.model = model
        self.config = config or MultiMessageConfig()
        self.message_bits = model.message_bits if model is not None else int(message_bits)
        self._last_seed_metadata: dict[str, Any] = {}
        self._last_seed_labels: np.ndarray | None = None

    def _initial_centroids(
        self,
        hard_bits: np.ndarray,
        minimum_support: float,
    ) -> tuple[np.ndarray, list[float]]:
        try:
            from sklearn.cluster import DBSCAN
        except ImportError:
            DBSCAN = None
        signatures, inverse, counts = np.unique(
            hard_bits,
            axis=0,
            return_inverse=True,
            return_counts=True,
        )
        if DBSCAN is not None:
            candidate_indices = np.argsort(counts)[::-1][: self.config.candidate_limit]
            candidate_signatures = signatures[candidate_indices]
            candidate_counts = counts[candidate_indices]
            schedules = sorted(
                {
                    max(1, int(np.ceil(minimum_support))),
                    500,
                    1000,
                    2000,
                    3000,
                }
            )
            solutions: list[dict[str, Any]] = []
            for minimum_samples in schedules:
                if minimum_samples > len(hard_bits):
                    continue
                candidate_labels = DBSCAN(
                    eps=float(np.sqrt(self.config.seed_hamming_radius)),
                    min_samples=minimum_samples,
                ).fit_predict(
                    candidate_signatures.astype(np.float32),
                    sample_weight=candidate_counts,
                )
                signature_labels = np.full(len(signatures), -1, dtype=np.int32)
                signature_labels[candidate_indices] = candidate_labels
                labels = signature_labels[inverse]
                clusters: list[tuple[float, np.ndarray, float, int]] = []
                for label in np.unique(labels):
                    if label < 0:
                        continue
                    selected = labels == label
                    support = float(np.sum(selected))
                    cluster_bits = hard_bits[selected]
                    centroid = np.mean(cluster_bits, axis=0).astype(np.float32)
                    message = centroid >= 0.5
                    agreement = float(np.mean(cluster_bits == message[None, :]))
                    clusters.append((support, centroid, agreement, int(label)))
                clusters.sort(key=lambda item: item[0], reverse=True)
                clusters = clusters[: self.config.maximum_messages]
                if not clusters:
                    continue
                messages = [item[1] >= 0.5 for item in clusters]
                separations = [
                    np.count_nonzero(first != second)
                    for index, first in enumerate(messages)
                    for second in messages[index + 1 :]
                ]
                minimum_separation = min(separations, default=self.message_bits)
                mean_agreement = float(np.mean([item[2] for item in clusters]))
                coverage = float(sum(item[0] for item in clusters) / len(hard_bits))
                valid = (
                    minimum_separation
                    >= self.config.minimum_message_hamming_separation
                    and mean_agreement >= 0.80
                )
                solutions.append(
                    {
                        "minimum_samples": minimum_samples,
                        "clusters": clusters,
                        "cluster_count": len(clusters),
                        "minimum_separation": int(minimum_separation),
                        "mean_agreement": mean_agreement,
                        "coverage": coverage,
                        "valid": valid,
                        "labels": labels,
                    }
                )
            valid_solutions = [item for item in solutions if item["valid"]]
            if valid_solutions:
                selected_solution = max(
                    valid_solutions,
                    key=lambda item: (
                        item["cluster_count"],
                        item["mean_agreement"],
                        item["coverage"],
                    ),
                )
                clusters = selected_solution["clusters"]
                seed_labels = np.full(len(hard_bits), -1, dtype=np.int16)
                for new_label, cluster in enumerate(clusters):
                    seed_labels[selected_solution["labels"] == cluster[3]] = new_label
                self._last_seed_labels = seed_labels
                self._last_seed_metadata = {
                    "density_schedule": schedules,
                    "unique_signature_count": int(len(signatures)),
                    "candidate_signature_count": int(len(candidate_signatures)),
                    "selected_minimum_samples": selected_solution["minimum_samples"],
                    "density_solutions": [
                        {
                            key: value
                            for key, value in item.items()
                            if key not in {"clusters", "labels"}
                        }
                        for item in solutions
                    ],
                }
                return (
                    np.stack([item[1] for item in clusters]),
                    [item[0] for item in clusters],
                )

        order = np.argsort(counts)[::-1][: self.config.candidate_limit]
        candidates = signatures[order]
        candidate_counts = counts[order].astype(np.float64)
        if not len(candidates):
            return np.empty((0, self.message_bits), dtype=np.float32), []
        pairwise_hamming = np.count_nonzero(
            candidates[:, None, :] != candidates[None, :, :],
            axis=2,
        )
        neighborhood_support = (
            pairwise_hamming <= self.config.seed_hamming_radius
        ) @ candidate_counts
        ranked = np.argsort(neighborhood_support)[::-1]
        selected: list[np.ndarray] = []
        supports: list[float] = []
        for index in ranked:
            if neighborhood_support[index] < minimum_support and selected:
                break
            candidate = candidates[index]
            if any(
                np.count_nonzero(candidate != existing)
                < self.config.minimum_message_hamming_separation
                for existing in selected
            ):
                continue
            selected.append(candidate.astype(np.float32))
            supports.append(float(neighborhood_support[index]))
            if len(selected) >= self.config.maximum_messages:
                break
        if not selected:
            selected.append(candidates[int(ranked[0])].astype(np.float32))
            supports.append(float(neighborhood_support[int(ranked[0])]))
        self._last_seed_metadata = {
            "density_schedule": [],
            "unique_signature_count": int(len(signatures)),
            "candidate_signature_count": int(len(candidates)),
            "selected_minimum_samples": None,
            "density_solutions": [],
        }
        self._last_seed_labels = None
        return np.stack(selected), supports

    @staticmethod
    def _soft_distances(probabilities: np.ndarray, centroids: np.ndarray) -> np.ndarray:
        reliability = np.maximum(np.abs(2.0 * probabilities - 1.0), 0.05)
        numerator = np.sum(
            reliability[:, None, :] * np.abs(probabilities[:, None, :] - centroids),
            axis=2,
        )
        denominator = np.sum(reliability, axis=1, keepdims=True)
        return numerator / np.maximum(denominator, 1e-8)

    def _responsibilities(self, distances: np.ndarray) -> np.ndarray:
        scores = -distances / self.config.assignment_temperature
        scores -= np.max(scores, axis=1, keepdims=True)
        responsibilities = np.exp(scores)
        responsibilities /= np.maximum(
            np.sum(responsibilities, axis=1, keepdims=True),
            1e-12,
        )
        responsibilities[
            np.min(distances, axis=1) > self.config.maximum_soft_hamming
        ] = 0.0
        return responsibilities

    def decode_prediction(self, prediction: WamSpatialPrediction) -> MultiMessageResult:
        detection = np.asarray(prediction.detection_probabilities, dtype=np.float32)
        logits = np.asarray(prediction.bit_logits, dtype=np.float32)
        if detection.ndim != 2:
            raise ValueError("detection probabilities must have shape HxW")
        if logits.shape != (self.message_bits, *detection.shape):
            raise ValueError(
                f"bit logits must have shape {self.message_bits}xHxW"
            )
        height, width = detection.shape
        valid_mask = detection > self.config.detection_threshold
        valid_count = int(np.sum(valid_mask))
        if not valid_count:
            return _empty_result(
                height,
                width,
                self.message_bits,
                method="adaptive-soft-message-clustering",
                detected_pixels=0,
                minimum_support=0,
            )

        flat_logits = np.moveaxis(logits, 0, -1)[valid_mask]
        probabilities = _sigmoid(
            (flat_logits - self.config.bit_logit_threshold)
            / self.config.bit_probability_temperature
        ).astype(np.float32)
        minimum_support = max(
            float(self.config.minimum_cluster_pixels),
            self.config.minimum_cluster_fraction * valid_count,
        )
        centroids, seed_supports = self._initial_centroids(
            probabilities >= 0.5,
            minimum_support,
        )
        if not len(centroids):
            return _empty_result(
                height,
                width,
                self.message_bits,
                method="adaptive-soft-message-clustering",
                detected_pixels=valid_count,
                minimum_support=minimum_support,
            )

        detection_weights = detection[valid_mask].astype(np.float64)
        seed_centroids = np.array(centroids, copy=True)
        seed_priors = (
            np.asarray(seed_supports, dtype=np.float64)
            * self.config.seed_prior_strength
        )
        responsibilities = np.zeros((valid_count, len(centroids)), dtype=np.float64)
        for _ in range(self.config.refinement_iterations):
            distances = self._soft_distances(probabilities, centroids)
            responsibilities = self._responsibilities(distances)
            weighted = responsibilities * detection_weights[:, None]
            support = np.sum(weighted, axis=0)
            updated = (
                weighted.T @ probabilities
                + seed_priors[:, None] * seed_centroids
            ) / np.maximum((support + seed_priors)[:, None], 1e-8)
            active = support > 1e-8
            centroids[active] = updated[active].astype(np.float32)

        support = np.sum(
            responsibilities * detection_weights[:, None],
            axis=0,
        )
        retain = (support >= minimum_support) | (
            np.asarray(seed_supports, dtype=np.float64) >= minimum_support
        )
        if not np.any(retain):
            retain[int(np.argmax(support))] = True
        centroids = centroids[retain]
        seed_centroids = seed_centroids[retain]
        responsibilities = responsibilities[:, retain]
        support = support[retain]
        messages = (centroids >= 0.5).astype(np.uint8)
        seed_messages = (seed_centroids >= 0.5).astype(np.uint8)
        refined_separations = [
            np.count_nonzero(first != second)
            for index, first in enumerate(messages)
            for second in messages[index + 1 :]
        ]
        seed_fallback = bool(refined_separations) and min(refined_separations) < (
            self.config.minimum_message_hamming_separation
        )
        if seed_fallback:
            messages = seed_messages
            if self._last_seed_labels is not None:
                retained_indices = np.flatnonzero(retain)
                hard_responsibilities = np.zeros_like(responsibilities)
                for new_index, old_index in enumerate(retained_indices):
                    hard_responsibilities[:, new_index] = (
                        self._last_seed_labels == old_index
                    )
                responsibilities = hard_responsibilities
                support = np.sum(
                    responsibilities * detection_weights[:, None],
                    axis=0,
                )
        order = np.argsort(support)[::-1]
        kept = [int(index) for index in order]
        messages = messages[kept]
        centroids = centroids[kept]
        responsibilities = responsibilities[:, kept]
        support = support[kept]

        localizations = np.zeros((len(kept), height, width), dtype=np.float32)
        for cluster_index in range(len(kept)):
            values = (
                responsibilities[:, cluster_index] * detection_weights
            ).astype(np.float32)
            localizations[cluster_index][valid_mask] = values
        label_map = np.full((height, width), -1, dtype=np.int16)
        if len(kept):
            strongest = np.max(localizations, axis=0)
            assigned = strongest >= self.config.localization_threshold
            label_map[assigned] = np.argmax(localizations[:, assigned], axis=0).astype(
                np.int16
            )

        detected_mass = max(float(np.sum(detection_weights)), 1e-8)
        support_fractions = (support / detected_mass).astype(np.float32)
        centroid_reliability = np.mean(np.abs(2.0 * centroids - 1.0), axis=1)
        confidences = np.clip(
            centroid_reliability * np.minimum(1.0, support / minimum_support),
            0.0,
            1.0,
        ).astype(np.float32)
        return MultiMessageResult(
            messages=np.ascontiguousarray(messages),
            confidences=np.ascontiguousarray(confidences),
            support_fractions=np.ascontiguousarray(support_fractions),
            localizations=np.ascontiguousarray(localizations),
            label_map=np.ascontiguousarray(label_map),
            metadata={
                "method": "adaptive-soft-message-clustering",
                "detected_pixels": valid_count,
                "detected_fraction": valid_count / float(height * width),
                "minimum_support": minimum_support,
                "seed_count": len(seed_supports),
                "seed_supports": seed_supports,
                "spatial_multiscale_seeding": False,
                "adaptive_weighted_dbscan_seeding": True,
                **self._last_seed_metadata,
                "seed_prior_regularization": True,
                "seed_message_fallback": seed_fallback,
                "cluster_count": len(kept),
                "maximum_messages": self.config.maximum_messages,
                "soft_assignment": True,
                "adaptive_minimum_support": True,
            },
        )

    def decode(self, image: ImageArray) -> MultiMessageResult:
        if self.model is None:
            raise RuntimeError("decode(image) requires a WamModel")
        return self.decode_prediction(self.model.predict_spatial(image))


class OfficialHardDbscanDecoder:
    """Project wrapper around WAM's published hard-bit DBSCAN inference rule."""

    def __init__(
        self,
        model: WamModel | None = None,
        *,
        detection_threshold: float = 0.5,
        bit_logit_threshold: float = 0.0,
        epsilon: float = 1.0,
        minimum_samples: int = 500,
        message_bits: int = 32,
    ) -> None:
        self.model = model
        self.detection_threshold = float(detection_threshold)
        self.bit_logit_threshold = float(bit_logit_threshold)
        self.epsilon = float(epsilon)
        self.minimum_samples = int(minimum_samples)
        self.message_bits = model.message_bits if model is not None else int(message_bits)

    def decode_prediction(self, prediction: WamSpatialPrediction) -> MultiMessageResult:
        try:
            from sklearn.cluster import DBSCAN
        except ImportError as error:
            raise RuntimeError(
                'official DBSCAN comparison requires pip install -e ".[research]"'
            ) from error
        detection = np.asarray(prediction.detection_probabilities, dtype=np.float32)
        logits = np.asarray(prediction.bit_logits, dtype=np.float32)
        if logits.shape != (self.message_bits, *detection.shape):
            raise ValueError(
                f"bit logits must have shape {self.message_bits}xHxW"
            )
        height, width = detection.shape
        valid_mask = detection > self.detection_threshold
        valid_count = int(np.sum(valid_mask))
        if not valid_count:
            return _empty_result(
                height,
                width,
                self.message_bits,
                method="official-hard-dbscan",
                detected_pixels=0,
            )
        features = np.moveaxis(logits > self.bit_logit_threshold, 0, -1)[valid_mask]
        unique_features, inverse, counts = np.unique(
            features,
            axis=0,
            return_inverse=True,
            return_counts=True,
        )
        unique_labels = DBSCAN(
            eps=self.epsilon,
            min_samples=self.minimum_samples,
        ).fit_predict(
            unique_features.astype(np.float32),
            sample_weight=counts,
        )
        labels = unique_labels[inverse]
        cluster_labels = [int(label) for label in np.unique(labels) if label >= 0]
        if not cluster_labels:
            return _empty_result(
                height,
                width,
                self.message_bits,
                method="official-hard-dbscan",
                detected_pixels=valid_count,
                minimum_samples=self.minimum_samples,
            )
        messages: list[np.ndarray] = []
        confidences: list[float] = []
        support_fractions: list[float] = []
        localizations: list[np.ndarray] = []
        total_weight = max(float(np.sum(detection[valid_mask])), 1e-8)
        flat_detection = detection[valid_mask]
        for label in cluster_labels:
            selected = labels == label
            centroid = np.mean(features[selected], axis=0)
            messages.append((centroid > 0.5).astype(np.uint8))
            confidences.append(float(np.mean(np.abs(2.0 * centroid - 1.0))))
            support_fractions.append(float(np.sum(flat_detection[selected]) / total_weight))
            localization = np.zeros((height, width), dtype=np.float32)
            values = np.zeros(valid_count, dtype=np.float32)
            values[selected] = flat_detection[selected]
            localization[valid_mask] = values
            localizations.append(localization)
        order = np.argsort(support_fractions)[::-1]
        message_array = np.stack(messages)[order]
        localization_array = np.stack(localizations)[order]
        label_map = np.full((height, width), -1, dtype=np.int16)
        strongest = np.max(localization_array, axis=0)
        assigned = strongest > 0
        label_map[assigned] = np.argmax(localization_array[:, assigned], axis=0).astype(
            np.int16
        )
        return MultiMessageResult(
            messages=np.ascontiguousarray(message_array),
            confidences=np.asarray(confidences, dtype=np.float32)[order],
            support_fractions=np.asarray(support_fractions, dtype=np.float32)[order],
            localizations=np.ascontiguousarray(localization_array),
            label_map=label_map,
            metadata={
                "method": "official-hard-dbscan",
                "detected_pixels": valid_count,
                "cluster_count": len(cluster_labels),
                "compressed_unique_signatures": int(len(unique_features)),
                "epsilon": self.epsilon,
                "minimum_samples": self.minimum_samples,
                "soft_assignment": False,
                "adaptive_minimum_support": False,
            },
        )

    def decode(self, image: ImageArray) -> MultiMessageResult:
        if self.model is None:
            raise RuntimeError("decode(image) requires a WamModel")
        return self.decode_prediction(self.model.predict_spatial(image))
