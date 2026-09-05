"""Evidence-driven, lazy geometric synchronization with an explicit inference budget.

The policy consumes only decoder evidence, never an expected message, attack label,
padding color or dataset identity. The same policy can replay recorded branches.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from watermark_lab.core.types import DecodeResult, ImageArray
from watermark_lab.innovations.geometry_sync import (
    GeometrySyncDecoder,
    correct_perspective,
    correct_rotation,
    localization_in_input_coordinates,
)

CANDIDATES = (
    "identity",
    "rotation_-6",
    "rotation_+6",
    "perspective_0.06",
    "rotation_-10",
    "rotation_+10",
    "rotation_-3",
    "rotation_+3",
    "perspective_0.03",
    "perspective_0.1",
)


@dataclass(frozen=True)
class BudgetGeometryConfig:
    max_candidates: int = 7
    minimum_search_fraction: float = 0.05
    reliable_fraction: float = 0.25
    identity_minimum_margin: float = 0.8
    stop_minimum_margin: float = 0.8
    reliable_agreement: float = 0.95
    minimum_score_improvement: float = 0.006
    detection_fraction_threshold: float = 0.05

    def __post_init__(self) -> None:
        if not isinstance(self.max_candidates, int) or not 1 <= self.max_candidates <= 10:
            raise ValueError("max_candidates must be an integer within [1, 10]")
        for name, value in asdict(self).items():
            if not np.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        for name in (
            "minimum_search_fraction",
            "reliable_fraction",
            "reliable_agreement",
            "detection_fraction_threshold",
        ):
            if not 0 < getattr(self, name) <= 1:
                raise ValueError(f"{name} must be within (0, 1]")
        if self.minimum_search_fraction > self.reliable_fraction:
            raise ValueError("search fraction cannot exceed reliable fraction")


@dataclass(frozen=True)
class CandidateEvidence:
    name: str
    score: float
    selected_fraction: float
    confidence: float
    agreement: float
    minimum_margin: float
    mean_margin: float
    pooled_logits: tuple[float, ...]

    @classmethod
    def from_branch(cls, branch: Any) -> CandidateEvidence:
        logits = np.nan_to_num(branch.pooled_logits, neginf=0.0, posinf=0.0)
        return cls(
            branch.name,
            branch.score,
            branch.selected_fraction,
            branch.confidence,
            branch.agreement,
            branch.minimum_margin,
            branch.mean_margin,
            tuple(float(value) for value in logits),
        )

    def bits(self, threshold: float = 0.5) -> np.ndarray:
        if self.selected_fraction <= 0:
            return np.zeros(len(self.pooled_logits), dtype=np.uint8)
        return (np.asarray(self.pooled_logits) > threshold).astype(np.uint8)


@dataclass(frozen=True)
class BudgetDecision:
    selected: CandidateEvidence
    visited: tuple[CandidateEvidence, ...]
    stop_reason: str


def _reliable(candidate: CandidateEvidence, config: BudgetGeometryConfig, margin: float) -> bool:
    return (
        candidate.selected_fraction >= config.reliable_fraction
        and candidate.agreement >= config.reliable_agreement
        and candidate.minimum_margin >= margin
    )


def _remaining_priority(visited: list[CandidateEvidence]) -> list[str]:
    """Probe both rotation signs and perspective before prioritizing refinements."""
    seen = {candidate.name for candidate in visited}
    probes = [name for name in CANDIDATES[1:4] if name not in seen]
    if probes:
        return probes
    best = max(visited[1:], key=lambda candidate: candidate.score)
    if best.name.startswith("perspective"):
        preferred = ["perspective_0.03", "perspective_0.1"]
    elif best.name.startswith("rotation_-"):
        preferred = ["rotation_-10", "rotation_-3"]
    else:
        preferred = ["rotation_+10", "rotation_+3"]
    return [name for name in dict.fromkeys([*preferred, *CANDIDATES[4:]]) if name not in seen]


def run_budget_policy(
    fetch: Callable[[str], CandidateEvidence], config: BudgetGeometryConfig
) -> BudgetDecision:
    """Pure sequential decision logic shared by live inference and calibration replay."""
    identity = fetch("identity")
    visited = [identity]
    if identity.selected_fraction < config.minimum_search_fraction:
        return BudgetDecision(identity, tuple(visited), "insufficient_watermark_evidence")
    if _reliable(identity, config, config.identity_minimum_margin):
        return BudgetDecision(identity, tuple(visited), "reliable_identity")
    reason = "candidate_budget_exhausted"
    while len(visited) < config.max_candidates:
        remaining = _remaining_priority(visited)
        if not remaining:
            reason = "all_candidates_evaluated"
            break
        visited.append(fetch(remaining[0]))
        best = max(visited, key=lambda candidate: candidate.score)
        # Both signs must be probed before early exit, preventing one-sided routing.
        if (
            len(visited) >= 3
            and best.name != "identity"
            and best.score - identity.score >= config.minimum_score_improvement
            and _reliable(best, config, config.stop_minimum_margin)
        ):
            reason = "reliable_correction"
            break
    best = max(visited, key=lambda candidate: candidate.score)
    if (
        best.selected_fraction < config.reliable_fraction
        or best.score - identity.score < config.minimum_score_improvement
    ):
        best = identity
    return BudgetDecision(best, tuple(visited), reason)


def transform_candidate(image: ImageArray, name: str) -> ImageArray:
    if name == "identity":
        return image
    if name not in CANDIDATES:
        raise ValueError(f"unknown budgeted candidate {name}")
    if name.startswith("rotation_"):
        return correct_rotation(image, float(name.removeprefix("rotation_")))
    return correct_perspective(image, float(name.removeprefix("perspective_")))


class BudgetGeometryDecoder(GeometrySyncDecoder):
    """Generate and evaluate only branches requested by the evidence policy."""

    def __init__(self, model, *, budget_config: BudgetGeometryConfig | None = None) -> None:
        super().__init__(model)
        self.budget_config = budget_config or BudgetGeometryConfig()

    def decode(self, image: ImageArray) -> DecodeResult:
        source = self.model.validate_image(image)
        branches = {}

        def fetch(name: str) -> CandidateEvidence:
            branch = self._score(name, transform_candidate(source, name))
            branches[name] = branch
            return CandidateEvidence.from_branch(branch)

        decision = run_budget_policy(fetch, self.budget_config)
        selected = decision.selected
        return DecodeResult(
            message=selected.bits(self.model.bit_logit_threshold),
            detected=selected.selected_fraction >= self.budget_config.detection_fraction_threshold,
            confidence=selected.confidence,
            localization=localization_in_input_coordinates(
                branches[selected.name].prediction.detection_probabilities,
                selected.name,
                source.shape,
            ),
            metadata={
                "variant": "budget_wam_geometry_v3",
                "selected_transform": selected.name,
                "candidate_count": len(decision.visited),
                "configured_candidate_count": len(CANDIDATES),
                "candidate_budget": self.budget_config.max_candidates,
                "stop_reason": decision.stop_reason,
                "geometry_search_skipped": len(decision.visited) == 1,
                "geometry_candidate_accepted": selected.name != "identity",
                "detected_fraction": selected.selected_fraction,
                "detection_fraction_threshold": self.budget_config.detection_fraction_threshold,
                "minimum_absolute_bit_margin": selected.minimum_margin,
                "localization_coordinate_system": "input_image",
                "localization_grid": "detector",
                "policy": asdict(self.budget_config),
                "geometry_branches": [asdict(candidate) for candidate in decision.visited],
            },
        )
