from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    mode: str = "local"
    version: str = "0.1.0"


class ApiModelInfo(BaseModel):
    id: str
    stage: str
    role: str
    available: bool
    reason: str | None = None


class ExperimentResult(BaseModel):
    id: str
    created_at: datetime
    image_name: str
    model: str
    message_bits: int
    expected_message: str
    decoded_message: str
    attack: str
    attack_parameters: dict[str, Any]
    detected: bool
    detection_confidence: float = Field(ge=0.0, le=1.0)
    bit_accuracy: float = Field(ge=0.0, le=1.0)
    ber: float = Field(ge=0.0, le=1.0)
    complete_recovery: bool
    embed_psnr_db: float | None
    embed_ssim: float
    post_attack_psnr_db: float | None
    post_attack_ssim: float
    encode_ms: float
    decode_ms: float
    original_image_data_url: str
    embedded_image_data_url: str
    attacked_image_data_url: str
    metadata: dict[str, Any]
