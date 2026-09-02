from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations

import numpy as np


@dataclass(frozen=True)
class MultiMessageMetrics:
    expected_count: int
    predicted_count: int
    count_correct: bool
    matched_count: int
    exact_match_count: int
    message_precision: float
    message_recall: float
    mean_matched_bit_accuracy: float
    all_messages_recovered: bool
    mean_matched_iou: float
    assignments: tuple[tuple[int, int], ...]


def _iou(first: np.ndarray, second: np.ndarray) -> float:
    left = np.asarray(first, dtype=bool)
    right = np.asarray(second, dtype=bool)
    if left.shape != right.shape:
        raise ValueError("localization masks must share a shape")
    union = np.sum(left | right)
    return float(np.sum(left & right) / union) if union else 1.0


def _best_assignments(scores: np.ndarray) -> tuple[tuple[int, int], ...]:
    expected_count, predicted_count = scores.shape
    if not expected_count or not predicted_count:
        return ()
    if expected_count <= predicted_count:
        candidates = (
            tuple((expected, predicted) for expected, predicted in enumerate(choice))
            for choice in permutations(range(predicted_count), expected_count)
        )
    else:
        candidates = (
            tuple((expected, predicted) for predicted, expected in enumerate(choice))
            for choice in permutations(range(expected_count), predicted_count)
        )
    return max(
        candidates,
        key=lambda pairs: sum(scores[expected, predicted] for expected, predicted in pairs),
    )


def evaluate_multi_message_result(
    expected_messages: np.ndarray,
    predicted_messages: np.ndarray,
    *,
    expected_masks: np.ndarray | None = None,
    predicted_localizations: np.ndarray | None = None,
    localization_threshold: float = 0.25,
) -> MultiMessageMetrics:
    expected = np.asarray(expected_messages, dtype=np.uint8)
    predicted = np.asarray(predicted_messages, dtype=np.uint8)
    if expected.ndim != 2 or predicted.ndim != 2:
        raise ValueError("message arrays must have shape KxB")
    if expected.shape[1] != predicted.shape[1]:
        raise ValueError("expected and predicted messages must use the same bit length")
    bit_scores = np.mean(expected[:, None, :] == predicted[None, :, :], axis=2)

    iou_scores = np.zeros_like(bit_scores, dtype=np.float64)
    if expected_masks is not None or predicted_localizations is not None:
        if expected_masks is None or predicted_localizations is None:
            raise ValueError("both expected masks and predicted localizations are required")
        masks = np.asarray(expected_masks, dtype=bool)
        localizations = np.asarray(predicted_localizations, dtype=np.float32)
        if masks.shape[0] != len(expected) or localizations.shape[0] != len(predicted):
            raise ValueError("localization counts must match message counts")
        for expected_index in range(len(expected)):
            for predicted_index in range(len(predicted)):
                iou_scores[expected_index, predicted_index] = _iou(
                    masks[expected_index],
                    localizations[predicted_index] >= localization_threshold,
                )
    combined_scores = bit_scores + 0.01 * iou_scores
    assignments = _best_assignments(combined_scores)
    matched_bit_scores = [bit_scores[left, right] for left, right in assignments]
    matched_ious = [iou_scores[left, right] for left, right in assignments]
    exact_count = sum(score == 1.0 for score in matched_bit_scores)
    expected_count = len(expected)
    predicted_count = len(predicted)
    return MultiMessageMetrics(
        expected_count=expected_count,
        predicted_count=predicted_count,
        count_correct=expected_count == predicted_count,
        matched_count=len(assignments),
        exact_match_count=exact_count,
        message_precision=(exact_count / predicted_count if predicted_count else 0.0),
        message_recall=(exact_count / expected_count if expected_count else 1.0),
        mean_matched_bit_accuracy=(
            float(np.mean(matched_bit_scores)) if matched_bit_scores else 0.0
        ),
        all_messages_recovered=(
            expected_count == predicted_count and exact_count == expected_count
        ),
        mean_matched_iou=float(np.mean(matched_ious)) if matched_ious else 0.0,
        assignments=assignments,
    )
