from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from watermark_lab.innovations.budget_geometry import (
    CANDIDATES,
    BudgetGeometryConfig,
    BudgetGeometryDecoder,
    CandidateEvidence,
    run_budget_policy,
)
from watermark_lab.models.wam_adapter import WamSpatialPrediction


def evidence(
    name: str, *, score: float = 0.7, margin: float = 0.1, fraction: float = 0.9
) -> CandidateEvidence:
    return CandidateEvidence(name, score, fraction, 0.98, 0.98, margin, 2.0, (3.0,) * 32)


def test_confident_identity_does_not_request_transformed_candidates() -> None:
    calls = []

    def fetch(name: str) -> CandidateEvidence:
        calls.append(name)
        return evidence(name, margin=2)

    result = run_budget_policy(fetch, BudgetGeometryConfig())
    assert calls == ["identity"]
    assert result.stop_reason == "reliable_identity"


def test_absence_of_watermark_evidence_never_launches_blind_search() -> None:
    result = run_budget_policy(lambda name: evidence(name, fraction=0.001), BudgetGeometryConfig())
    assert len(result.visited) == 1
    assert result.stop_reason == "insufficient_watermark_evidence"


@pytest.mark.parametrize("budget", [1, 3, 5, 7, 10])
def test_strict_budget_counts_identity_and_probes_without_duplicates(budget: int) -> None:
    result = run_budget_policy(evidence, BudgetGeometryConfig(max_candidates=budget))
    names = [candidate.name for candidate in result.visited]
    assert len(names) == len(set(names)) == budget
    if budget >= 4:
        assert names[:4] == list(CANDIDATES[:4])


def test_opposite_rotation_is_probed_before_early_stop() -> None:
    def fetch(name: str) -> CandidateEvidence:
        return evidence(
            name,
            score=0.99 if name == "rotation_-6" else 0.7,
            margin=2 if name == "rotation_-6" else 0.1,
        )

    result = run_budget_policy(fetch, BudgetGeometryConfig())
    assert [candidate.name for candidate in result.visited] == list(CANDIDATES[:3])
    assert result.selected.name == "rotation_-6"
    assert result.stop_reason == "reliable_correction"


def test_low_area_high_score_spurious_branch_cannot_take_over() -> None:
    def fetch(name: str) -> CandidateEvidence:
        return evidence(
            name,
            score=0.7 if name == "identity" else 0.99,
            fraction=0.9 if name == "identity" else 0.1,
        )

    result = run_budget_policy(fetch, BudgetGeometryConfig())
    assert result.selected.name == "identity"


def test_branch_serialization_preserves_policy_replay() -> None:
    from dataclasses import asdict

    source = {name: evidence(name) for name in CANDIDATES}
    rebuilt = {name: CandidateEvidence(**asdict(candidate)) for name, candidate in source.items()}
    assert run_budget_policy(source.__getitem__, BudgetGeometryConfig()) == run_budget_policy(
        rebuilt.__getitem__, BudgetGeometryConfig()
    )


@pytest.mark.parametrize("value", [0, 11, 1.5, float("nan")])
def test_invalid_budget_is_rejected(value: float) -> None:
    with pytest.raises(ValueError):
        BudgetGeometryConfig(max_candidates=value)  # type: ignore[arg-type]


def test_nonfinite_policy_threshold_is_rejected() -> None:
    with pytest.raises(ValueError):
        replace(BudgetGeometryConfig(), identity_minimum_margin=float("inf"))


class StableModel:
    message_bits = 32
    detection_threshold = 0.5
    bit_logit_threshold = 0.5
    calls = 0

    def validate_image(self, image):
        return image

    def predict_spatial(self, image):
        self.calls += 1
        return WamSpatialPrediction(np.full((8, 8), 0.99), np.full((32, 8, 8), 3.0))


def test_live_decoder_reliable_image_runs_one_forward_and_returns_aligned_map() -> None:
    model = StableModel()
    decoded = BudgetGeometryDecoder(model).decode(np.zeros((128, 200, 3), dtype=np.uint8))
    assert model.calls == decoded.metadata["candidate_count"] == 1
    assert decoded.detected
    assert decoded.message.tolist() == [1] * 32
    assert decoded.localization.shape == (8, 8)
