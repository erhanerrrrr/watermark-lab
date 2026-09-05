"""Portable, typed evidence for the separately frozen geometry-v3 experiment."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, ValidationError, model_validator

from watermark_lab.api.research import EvidenceSchema, EvidenceSource
from watermark_lab.api.storage import project_root
from watermark_lab.innovations.budget_geometry import BudgetGeometryConfig

GEOMETRY_EVIDENCE_PATH = project_root() / "docs/evidence/geometry_v3.json"
Rate = Annotated[float, Field(ge=0, le=1)]
Method = Literal[
    "wam_fixed", "adaptive_identity", "legacy_am", "full_best", "full_soft", "budget_wam"
]


class GeometryMethod(EvidenceSchema):
    method: Method
    label: str
    positive_records: int = Field(gt=0)
    negative_records: int = Field(gt=0)
    bit_accuracy: Rate
    complete_recovery: Rate
    mean_candidates: float = Field(ge=1, le=10)
    mean_trace_cost_ms: float | None = Field(ge=0)
    threshold: float = Field(ge=0)
    tpr: Rate
    fpr: Rate
    false_positive_images: int = Field(ge=0)
    negative_images: int = Field(gt=0)
    mean_psnr_db: float
    false_positive_image_ci95: tuple[Rate, Rate]


class GeometryPair(EvidenceSchema):
    baseline: Method
    image_units: int = Field(gt=0)
    paired_records: int = Field(gt=0)
    recovery_gain_pp: float = Field(ge=-100, le=100)
    ci95_pp: tuple[float, float]
    rescued: int = Field(ge=0)
    regressed: int = Field(ge=0)
    budget_recovery: Rate
    baseline_recovery: Rate


class GeometryFamilyPair(GeometryPair):
    family: str


class GeometryDatasetPair(GeometryPair):
    dataset: str


class GeometryCriteria(EvidenceSchema):
    recovery_tolerance_pp: float = Field(ge=0)
    recovery_point_target_met: bool
    noninferiority_ci_supported: bool
    candidate_target_met: bool


class GeometryDecisionAudit(EvidenceSchema):
    stop_reason: str
    records: int = Field(gt=0)
    mean_candidates: float = Field(ge=1, le=10)
    complete_recovery: Rate
    rescued_vs_full_best: int = Field(ge=0)
    regressed_vs_full_best: int = Field(ge=0)


class GeometryTimingMethod(EvidenceSchema):
    method: Method
    runs: int = Field(gt=0)
    mean_ms: float = Field(gt=0)
    p50_ms: float = Field(gt=0)
    p95_ms: float = Field(gt=0)
    mean_candidates: float = Field(ge=1, le=10)
    peak_cuda_allocated_mb: float = Field(ge=0)


class GeometryTiming(EvidenceSchema):
    policy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    measured_conditions: int = Field(gt=0)
    image_units: int = Field(gt=0)
    repetitions: int = Field(gt=0)
    device: str
    torch_threads: int = Field(gt=0)
    methods: list[GeometryTimingMethod]
    live_replay_bitwise_verified: Literal[True]
    note: str


class GeometryEvidence(EvidenceSchema):
    version: Literal[1]
    suite_id: Literal["geometry-v3"]
    complete: Literal[True]
    generated_at: str
    calibration_images: int = Field(gt=0)
    test_images: int = Field(gt=0)
    attack_cases: int = Field(gt=0)
    negative_attack_cases: int = Field(gt=0)
    max_input_side: int = Field(gt=0)
    positive_records_per_method: int = Field(gt=0)
    negative_records_per_method: int = Field(gt=0)
    policy: BudgetGeometryConfig
    calibration_targets_met: bool
    test_criteria: GeometryCriteria
    methods: list[GeometryMethod]
    paired: list[GeometryPair]
    by_family: list[GeometryFamilyPair]
    by_dataset: list[GeometryDatasetPair]
    decision_audit: list[GeometryDecisionAudit]
    timing: GeometryTiming
    notes: list[str]
    provenance: list[EvidenceSource]

    @model_validator(mode="after")
    def validate_counts(self) -> GeometryEvidence:
        if len(self.methods) != 6 or len({row.method for row in self.methods}) != 6:
            raise ValueError("geometry-v3 requires six unique comparisons")
        if self.positive_records_per_method != self.test_images * self.attack_cases:
            raise ValueError("positive image/attack counts disagree")
        if self.negative_records_per_method != self.test_images * self.negative_attack_cases:
            raise ValueError("negative image/attack counts disagree")
        for row in self.methods:
            if (
                row.positive_records != self.positive_records_per_method
                or row.negative_records != self.negative_records_per_method
                or row.negative_images != self.test_images
                or row.false_positive_images > row.negative_images
            ):
                raise ValueError("method sample counts disagree")
        if sum(row.records for row in self.decision_audit) != self.positive_records_per_method:
            raise ValueError("decision audit counts disagree")
        full_pair = next((row for row in self.paired if row.baseline == "full_best"), None)
        if full_pair is None or (
            sum(row.rescued_vs_full_best for row in self.decision_audit) != full_pair.rescued
            or sum(row.regressed_vs_full_best for row in self.decision_audit) != full_pair.regressed
        ):
            raise ValueError("decision audit and paired outcomes disagree")
        return self


def load_geometry_evidence(path: Path | None = None) -> GeometryEvidence:
    try:
        return GeometryEvidence.model_validate_json(
            (path or GEOMETRY_EVIDENCE_PATH).read_bytes()
        )
    except (OSError, ValidationError) as error:
        raise RuntimeError(
            "geometry-v3 独立证据尚未就绪或文件无效；"
            "请完成冻结测试与在线计时后运行 scripts/export_geometry_v3.py。"
        ) from error
