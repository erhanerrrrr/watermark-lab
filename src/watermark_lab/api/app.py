from __future__ import annotations

import importlib.util

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from watermark_lab.api.schemas import ApiModelInfo, ExperimentResult, HealthResponse
from watermark_lab.api.service import (
    SUPPORTED_API_MODELS,
    experiment_history,
    run_single_experiment,
)
from watermark_lab.core.registry import list_model_specs
from watermark_lab.models.wam_adapter import wam_assets_available, wam_runtime_available

app = FastAPI(
    title="Watermark Lab API",
    version="0.1.0",
    description="Minimal HTTP adapter for single-image watermark experiments.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _runtime_availability(model_id: str) -> tuple[bool, str | None]:
    if model_id == "trustmark_q" and importlib.util.find_spec("trustmark") is None:
        return False, "当前环境未安装 TrustMark；请使用 .venv-trustmark 启动 API"
    if model_id in {"wam", "am_wam"}:
        if not wam_runtime_available():
            return False, "当前环境未安装 WAM runtime；请使用 .venv-wam 启动 API"
        if not wam_assets_available():
            return False, "缺少 WAM 官方源码或权重"
    return True, None


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/api/models", response_model=list[ApiModelInfo])
def models() -> list[ApiModelInfo]:
    items: list[ApiModelInfo] = []
    for spec in list_model_specs():
        if spec.name not in SUPPORTED_API_MODELS:
            continue
        available, reason = _runtime_availability(spec.name)
        items.append(
            ApiModelInfo(
                id=spec.name,
                stage=spec.stage,
                role=spec.role,
                available=available and spec.ready,
                reason=reason,
            )
        )
    return items


@app.get("/api/experiments", response_model=list[ExperimentResult])
def experiments() -> list[ExperimentResult]:
    return experiment_history()


@app.post("/api/experiments/single", response_model=ExperimentResult)
def single_experiment(
    image: UploadFile = File(...),  # noqa: B008 - FastAPI declares multipart fields this way.
    model: str = Form("lsb_reference"),
    message: str = Form("WATERMARK-LAB"),
    strength: float = Form(2.0),
    attack: str = Form("none"),
    attack_parameter: float = Form(0.0),
    device: str = Form("auto"),
) -> ExperimentResult:
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="只接受图片文件")
    available, reason = _runtime_availability(model)
    if not available:
        raise HTTPException(status_code=503, detail=reason)
    try:
        return run_single_experiment(
            image_payload=image.file.read(),
            image_name=image.filename or "uploaded-image",
            model_name=model,
            message=message,
            strength=strength,
            attack_name=attack,
            attack_parameter=attack_parameter,
            device=device,
        )
    except (ValueError, KeyError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
