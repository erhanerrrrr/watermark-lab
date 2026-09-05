"""Serve the portable research evidence without loading models or private datasets."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from watermark_lab.api.storage import project_root

EVIDENCE_PATH = project_root() / "configs" / "research_evidence.json"


class EvidenceSchema(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)


class EvidenceModel(EvidenceSchema):
    id: str
    bit_accuracy: float = Field(ge=0, le=1)
    complete_recovery: float = Field(ge=0, le=1)
    embed_psnr_db: float
    decode_ms: float = Field(ge=0)


class PairedEvidence(EvidenceSchema):
    bit_accuracy_gain_pp: float
    recovery_gain_pp: float
    recovery_ci95_pp: tuple[float, float]
    rescued: int = Field(ge=0)
    regressed: int = Field(ge=0)
    both_recovered: int = Field(ge=0)
    both_failed: int = Field(ge=0)
    decode_overhead_ms: float


class EvidenceRow(EvidenceSchema):
    dataset: str
    attack: str
    category: str
    images: int = Field(gt=0)
    paired_records: int = Field(gt=0)
    models: list[EvidenceModel]
    comparison: PairedEvidence


class EvidenceSensitivity(EvidenceSchema):
    excluded_attack: str
    images: int = Field(gt=0)
    paired_records: int = Field(gt=0)
    recovery_gain_pp: float
    recovery_ci95_pp: tuple[float, float]


class EvidenceDataset(EvidenceSchema):
    id: str
    label: str
    images: int = Field(gt=0)


class EvidenceSource(EvidenceSchema):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ResearchEvidence(EvidenceSchema):
    version: Literal[1]
    suite_id: str
    source: Literal["tracked_evidence_snapshot"]
    records: int = Field(gt=0)
    images: int = Field(gt=0)
    attacks: int = Field(gt=0)
    generated_at: str
    bootstrap_iterations: int = Field(gt=0)
    seed: int
    notes: list[str]
    datasets: list[EvidenceDataset]
    rows: list[EvidenceRow]
    sensitivity: list[EvidenceSensitivity]
    provenance: list[EvidenceSource]


def load_research_evidence(path: Path | None = None) -> ResearchEvidence:
    try:
        return ResearchEvidence.model_validate_json((path or EVIDENCE_PATH).read_bytes())
    except (OSError, ValidationError) as error:
        raise RuntimeError(
            "研究证据快照缺失或无效；请恢复 configs/research_evidence.json，"
            "或在完整正式结果上运行 scripts/build_research_evidence.py。"
        ) from error
