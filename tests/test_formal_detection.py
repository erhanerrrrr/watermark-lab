from __future__ import annotations

import numpy as np

from scripts.analyze_formal_detection import (
    roc_auc,
    select_tie_safe_threshold,
    wilson_interval,
)


def test_tie_safe_threshold_respects_target_fpr() -> None:
    negatives = np.asarray([0.1, 0.2, 0.2, 0.4, 0.9])
    threshold = select_tie_safe_threshold(negatives, 0.2)
    assert threshold == 0.9
    assert np.mean(negatives >= threshold) <= 0.2


def test_tie_safe_threshold_can_select_above_maximum() -> None:
    negatives = np.asarray([0.1, 0.1, 0.1])
    threshold = select_tie_safe_threshold(negatives, 0.01)
    assert threshold > 0.1
    assert np.mean(negatives >= threshold) == 0.0


def test_roc_auc_counts_ties() -> None:
    labels = np.asarray([0, 0, 1, 1])
    scores = np.asarray([0.0, 0.5, 0.5, 1.0])
    assert roc_auc(labels, scores) == 0.875


def test_wilson_interval_contains_observed_rate() -> None:
    lower, upper = wilson_interval(7, 10)
    assert lower < 0.7 < upper
