from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    mode: str = "local"
    version: str = "0.2.0"
    storage: str
    persisted_experiments: int = Field(ge=0)
    frontend_available: bool


class FormalModelMetrics(BaseModel):
    records: int
    detected: float = Field(ge=0.0, le=1.0)
    bit_accuracy: float = Field(ge=0.0, le=1.0)
    complete_recovery: float = Field(ge=0.0, le=1.0)
    embed_psnr_db: float
    encode_ms: float
    decode_ms: float


class ApiModelInfo(BaseModel):
    id: str
    display_name: str
    stage: str
    role: str
    family: str
    description: str
    detail: str
    robustness: str
    default_strength: float = Field(gt=0.0)
    accent: str
    available: bool
    reason: str | None = None
    formal_metrics: FormalModelMetrics | None = None


class DatasetSplitCount(BaseModel):
    found: int = Field(ge=0)
    expected: int = Field(ge=0)


class ApiDatasetInfo(BaseModel):
    id: str
    display_name: str
    source: str
    license: str
    debug_manifest: str
    calibration_manifest: str
    test_manifest: str
    counts: dict[str, DatasetSplitCount]
    found_images: int = Field(ge=0)
    expected_images: int = Field(ge=0)
    progress: float = Field(ge=0.0, le=100.0)
    ready: bool


class AttackStepInfo(BaseModel):
    name: str
    parameters: dict[str, Any]


class AttackCaseInfo(BaseModel):
    id: str
    category: str
    pipeline: list[AttackStepInfo]


class AttackProtocolInfo(BaseModel):
    id: str
    version: int
    seed: int
    cases: list[AttackCaseInfo]


class InteractiveAttackInfo(BaseModel):
    id: str
    display_name: str
    description: str
    parameter_label: str
    minimum: float
    maximum: float
    step: float
    default: float
    unit: str


class FormalSnapshot(BaseModel):
    suite_id: str
    complete: bool
    records: int
    expected_records: int
    calibration_images: int
    test_images: int
    attack_cases: int
    target_psnr_db: float
    source: str
    data_source: str
    models: dict[str, FormalModelMetrics]
    innovation: dict[str, Any]


class CatalogResponse(BaseModel):
    version: int
    updated_at: str
    project: dict[str, str]
    models: list[ApiModelInfo]
    datasets: list[ApiDatasetInfo]
    protocol: AttackProtocolInfo
    interactive_attacks: list[InteractiveAttackInfo]
    formal: FormalSnapshot


class DatasetVerification(BaseModel):
    id: str
    expected: int
    verified: int
    missing: list[str]
    mismatched: list[str]
    valid: bool


class ExperimentSummary(BaseModel):
    id: str
    created_at: datetime
    image_name: str
    model: str
    message_bits: int
    attack: str
    detected: bool
    detection_confidence: float = Field(ge=0.0, le=1.0)
    bit_accuracy: float = Field(ge=0.0, le=1.0)
    ber: float = Field(ge=0.0, le=1.0)
    complete_recovery: bool
    embed_psnr_db: float | None
    embed_ssim: float = Field(ge=0.0, le=1.0)
    post_attack_psnr_db: float | None
    post_attack_ssim: float = Field(ge=0.0, le=1.0)
    encode_ms: float = Field(ge=0.0)
    decode_ms: float = Field(ge=0.0)


class ExperimentRecord(ExperimentSummary):
    expected_message: str
    decoded_message: str
    attack_parameters: dict[str, Any]
    metadata: dict[str, Any]


class ArtifactUrls(BaseModel):
    original: str
    embedded: str
    attacked: str


class ExperimentDetail(ExperimentRecord):
    artifacts: ArtifactUrls


class EmbedResponse(BaseModel):
    id: str
    created_at: datetime
    image_name: str
    model: str
    message_bits: int
    expected_message: str
    embed_psnr_db: float | None
    embed_ssim: float = Field(ge=0.0, le=1.0)
    encode_ms: float = Field(ge=0.0)
    embedded_image_url: str
    metadata: dict[str, Any]


class DecodeResponse(BaseModel):
    image_name: str
    model: str
    message_bits: int
    decoded_message: str
    detected: bool
    detection_confidence: float = Field(ge=0.0, le=1.0)
    bit_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    ber: float | None = Field(default=None, ge=0.0, le=1.0)
    complete_recovery: bool | None = None
    decode_ms: float = Field(ge=0.0)
    metadata: dict[str, Any]
