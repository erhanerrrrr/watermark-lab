from __future__ import annotations

import importlib.util
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, NoReturn

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from watermark_lab import __version__
from watermark_lab.api.catalog import (
    attack_catalog,
    dataset_catalog,
    formal_snapshot,
    load_showcase_config,
    manifest_path,
    verify_datasets,
)
from watermark_lab.api.geometry_research import GeometryEvidence, load_geometry_evidence
from watermark_lab.api.research import ResearchEvidence, load_research_evidence
from watermark_lab.api.schemas import (
    ApiModelInfo,
    CatalogResponse,
    DatasetVerification,
    DecodeResponse,
    EmbedResponse,
    ExperimentDetail,
    ExperimentSummary,
    HealthResponse,
)
from watermark_lab.api.service import (
    MAX_UPLOAD_BYTES,
    SUPPORTED_API_MODELS,
    run_decode,
    run_embed,
    run_single_experiment,
)
from watermark_lab.api.storage import ExperimentStore, project_root
from watermark_lab.api.trustmark_runtime import (
    TrustMarkWorkerClient,
    create_trustmark_worker,
    trustmark_mode,
)
from watermark_lab.core.registry import list_model_specs
from watermark_lab.models.budget_wam import load_budget_policy
from watermark_lab.models.wam_adapter import wam_assets_available, wam_runtime_available


def _runtime_availability(
    model_id: str, worker: TrustMarkWorkerClient | None = None
) -> tuple[bool, str | None]:
    if model_id == "trustmark_q":
        if trustmark_mode() == "disabled":
            return False, "TrustMark 已通过运行配置停用"
        if worker is not None:
            return worker.availability()
        if importlib.util.find_spec("trustmark") is None:
            return False, "当前服务未安装 TrustMark；请启用或配置 TrustMark 独立环境"
    if model_id in {"wam", "am_wam", "budget_wam"}:
        if not wam_runtime_available():
            return False, "当前环境未安装 WAM runtime；请使用 .venv-wam-gpu 启动 API"
        if not wam_assets_available():
            return False, "缺少 WAM 官方源码或权重"
        if model_id == "budget_wam":
            try:
                load_budget_policy()
            except RuntimeError as error:
                return False, str(error)
    return True, None


def _api_models(worker: TrustMarkWorkerClient | None = None) -> list[ApiModelInfo]:
    showcase = load_showcase_config()
    presentation = showcase["models"]
    formal_models = formal_snapshot()["models"]
    items: list[ApiModelInfo] = []
    for spec in list_model_specs():
        if spec.name not in SUPPORTED_API_MODELS:
            continue
        available, reason = _runtime_availability(spec.name, worker)
        isolated = spec.name == "trustmark_q" and worker is not None
        if isolated:
            device = worker.runtime_info.get("device")
            runtime_label = "TrustMark 独立进程" + (f" · {device.upper()}" if device else "")
        elif spec.name in {"wam", "am_wam", "budget_wam"}:
            runtime_label = "主服务 · 自动选择设备"
        elif spec.name == "trustmark_q":
            runtime_label = "主服务 · TrustMark"
        else:
            runtime_label = "主服务 · CPU"
        metadata = presentation[spec.name]
        items.append(
            ApiModelInfo(
                id=spec.name,
                display_name=metadata["display_name"],
                stage=spec.stage,
                role=spec.role,
                family=metadata["family"],
                description=metadata["description"],
                detail=metadata["detail"],
                robustness=metadata["robustness"],
                default_strength=metadata["default_strength"],
                accent=metadata["accent"],
                available=available and spec.ready,
                execution_backend="isolated" if isolated else "local",
                runtime_label=runtime_label,
                reason=reason,
                formal_metrics=formal_models.get(spec.name),
            )
        )
    return items


def _artifact_urls(request: Request, experiment_id: str) -> dict[str, str]:
    return {
        kind: str(
            request.url_for(
                "experiment_artifact", experiment_id=experiment_id, artifact_kind=kind
            )
        )
        for kind in ("original", "embedded", "attacked")
    }


def _detail(request: Request, payload: dict[str, Any]) -> ExperimentDetail:
    return ExperimentDetail.model_validate(
        {**payload, "artifacts": _artifact_urls(request, payload["id"])}
    )


async def _upload_bytes(image: UploadFile) -> bytes:
    payload = await image.read(MAX_UPLOAD_BYTES + 1)
    await image.close()
    return payload


def _raise_api_error(error: Exception) -> NoReturn:
    if isinstance(error, (ValueError, KeyError)):
        raise HTTPException(status_code=422, detail=str(error)) from error
    if isinstance(error, RuntimeError):
        raise HTTPException(status_code=503, detail=str(error)) from error
    raise error


def create_app(
    *,
    storage_dir: Path | None = None,
    frontend_dir: Path | None = None,
    trustmark_worker: TrustMarkWorkerClient | None = None,
) -> FastAPI:
    store = ExperimentStore(storage_dir)
    frontend = (frontend_dir or project_root() / "frontend" / "dist").resolve()
    worker = trustmark_worker if trustmark_worker is not None else create_trustmark_worker()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            if worker is not None:
                try:
                    await run_in_threadpool(worker.ensure_ready)
                except RuntimeError as error:
                    logging.getLogger(__name__).warning("TrustMark worker unavailable: %s", error)
            yield
        finally:
            if worker is not None:
                await run_in_threadpool(worker.close)

    application = FastAPI(
        title="Watermark Lab API",
        version=__version__,
        description="Persistent local API for watermark experiments and the research showcase.",
        lifespan=lifespan,
    )
    application.state.experiment_store = store
    application.state.frontend_dir = frontend
    application.state.trustmark_worker = worker

    @application.middleware("http")
    async def refresh_live_api(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    origins = os.environ.get(
        "WATERMARK_LAB_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[value.strip() for value in origins.split(",") if value.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            version=__version__,
            storage=str(store.database_path),
            persisted_experiments=store.count(),
            frontend_available=(frontend / "index.html").is_file(),
        )

    @application.get("/api/models", response_model=list[ApiModelInfo])
    def models() -> list[ApiModelInfo]:
        return _api_models(worker)

    @application.get("/api/catalog", response_model=CatalogResponse)
    def catalog() -> CatalogResponse:
        configured = load_showcase_config()
        return CatalogResponse(
            version=configured["version"],
            updated_at=configured["updated_at"],
            project=configured["project"],
            models=_api_models(worker),
            datasets=dataset_catalog(),
            protocol=attack_catalog(),
            interactive_attacks=configured["interactive_attacks"],
            formal=formal_snapshot(),
        )

    @application.post("/api/datasets/verify", response_model=list[DatasetVerification])
    async def datasets_verify() -> list[DatasetVerification]:
        reports = await run_in_threadpool(verify_datasets)
        return [DatasetVerification.model_validate(report) for report in reports]

    @application.get("/api/research/evidence", response_model=ResearchEvidence)
    def research_evidence() -> ResearchEvidence:
        try:
            return load_research_evidence()
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @application.get("/api/research/evidence/export.json")
    def research_evidence_export() -> Response:
        evidence = research_evidence()
        return Response(
            evidence.model_dump_json(indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="formal-v1-evidence.json"'
            },
        )

    @application.get("/api/research/geometry-v3", response_model=GeometryEvidence)
    def geometry_evidence() -> GeometryEvidence:
        try:
            return load_geometry_evidence()
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @application.get("/api/research/geometry-v3/export.json")
    def geometry_evidence_export() -> Response:
        return Response(
            geometry_evidence().model_dump_json(indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="geometry-v3-evidence.json"'},
        )

    @application.get("/api/datasets/{dataset_id}/manifest/{split}", name="dataset_manifest")
    def dataset_manifest(dataset_id: str, split: str) -> FileResponse:
        path = manifest_path(dataset_id, split)
        if path is None:
            raise HTTPException(status_code=404, detail="未找到指定 manifest")
        return FileResponse(path, media_type="text/csv", filename=path.name)

    @application.get("/api/experiments", response_model=list[ExperimentSummary])
    def experiments(
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        model: str | None = None,
    ) -> list[ExperimentSummary]:
        if model is not None and model not in SUPPORTED_API_MODELS:
            raise HTTPException(status_code=422, detail=f"不支持的模型：{model}")
        return [
            ExperimentSummary.model_validate(row)
            for row in store.list_experiments(limit=limit, model=model)
        ]

    @application.get("/api/experiments/export.csv", name="experiment_export")
    def experiment_export() -> Response:
        return Response(
            store.export_csv(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="watermark-experiments.csv"'},
        )

    @application.get("/api/experiments/{experiment_id}", response_model=ExperimentDetail)
    def experiment_detail(request: Request, experiment_id: str) -> ExperimentDetail:
        try:
            payload = store.get_experiment(experiment_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="实验记录不存在") from error
        if payload is None:
            raise HTTPException(status_code=404, detail="实验记录不存在")
        return _detail(request, payload)

    @application.get(
        "/api/experiments/{experiment_id}/artifacts/{artifact_kind}",
        name="experiment_artifact",
    )
    def experiment_artifact(experiment_id: str, artifact_kind: str) -> FileResponse:
        try:
            path = store.artifact_path(experiment_id, artifact_kind)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="实验产物不存在") from error
        if path is None:
            raise HTTPException(status_code=404, detail="实验产物不存在")
        return FileResponse(path, media_type="image/png", filename=path.name)

    @application.post("/api/experiments/single", response_model=ExperimentDetail)
    async def single_experiment(
        request: Request,
        image: Annotated[UploadFile, File()],
        model: Annotated[str, Form()] = "lsb_reference",
        message: Annotated[str, Form(max_length=4096)] = "WATERMARK-LAB",
        strength: Annotated[float, Form(gt=0.0, le=1000.0)] = 2.0,
        attack: Annotated[str, Form()] = "none",
        attack_parameter: Annotated[float, Form()] = 0.0,
        device: Annotated[str, Form(pattern=r"^(auto|cpu|cuda(?::\d+)?)$")] = "auto",
    ) -> ExperimentDetail:
        if not image.content_type or not image.content_type.startswith("image/"):
            raise HTTPException(status_code=415, detail="只接受图片文件")
        available, reason = _runtime_availability(model, worker)
        if not available:
            raise HTTPException(status_code=503, detail=reason)
        try:
            completed = await run_in_threadpool(
                run_single_experiment,
                image_payload=await _upload_bytes(image),
                image_name=image.filename or "uploaded-image",
                model_name=model,
                message=message,
                strength=strength,
                attack_name=attack,
                attack_parameter=attack_parameter,
                device=device,
                trustmark_worker=worker,
            )
            payload = completed.record.model_dump(mode="json")
            await run_in_threadpool(store.save_experiment, payload, completed.images)
            return _detail(request, payload)
        except Exception as error:
            return _raise_api_error(error)

    @application.post("/api/watermarks/embed", response_model=EmbedResponse)
    async def watermark_embed(
        request: Request,
        image: Annotated[UploadFile, File()],
        model: Annotated[str, Form()] = "lsb_reference",
        message: Annotated[str, Form(max_length=4096)] = "WATERMARK-LAB",
        strength: Annotated[float, Form(gt=0.0, le=1000.0)] = 2.0,
        device: Annotated[str, Form(pattern=r"^(auto|cpu|cuda(?::\d+)?)$")] = "auto",
    ) -> EmbedResponse:
        if not image.content_type or not image.content_type.startswith("image/"):
            raise HTTPException(status_code=415, detail="只接受图片文件")
        available, reason = _runtime_availability(model, worker)
        if not available:
            raise HTTPException(status_code=503, detail=reason)
        try:
            operation_id, created_at, embedded, values = await run_in_threadpool(
                run_embed,
                image_payload=await _upload_bytes(image),
                image_name=image.filename or "uploaded-image",
                model_name=model,
                message=message,
                strength=strength,
                device=device,
                trustmark_worker=worker,
            )
            await run_in_threadpool(store.save_operation_image, operation_id, "embedded", embedded)
            url = str(
                request.url_for(
                    "watermark_artifact", operation_id=operation_id, artifact_kind="embedded"
                )
            )
            return EmbedResponse(
                id=operation_id,
                created_at=created_at,
                embedded_image_url=url,
                **values,
            )
        except Exception as error:
            return _raise_api_error(error)

    @application.post("/api/watermarks/decode", response_model=DecodeResponse)
    async def watermark_decode(
        image: Annotated[UploadFile, File()],
        model: Annotated[str, Form()] = "lsb_reference",
        expected_message: Annotated[str | None, Form(max_length=4096)] = None,
        strength: Annotated[float, Form(gt=0.0, le=1000.0)] = 2.0,
        device: Annotated[str, Form(pattern=r"^(auto|cpu|cuda(?::\d+)?)$")] = "auto",
    ) -> DecodeResponse:
        if not image.content_type or not image.content_type.startswith("image/"):
            raise HTTPException(status_code=415, detail="只接受图片文件")
        available, reason = _runtime_availability(model, worker)
        if not available:
            raise HTTPException(status_code=503, detail=reason)
        try:
            return await run_in_threadpool(
                run_decode,
                image_payload=await _upload_bytes(image),
                image_name=image.filename or "uploaded-image",
                model_name=model,
                expected_message=expected_message,
                strength=strength,
                device=device,
                trustmark_worker=worker,
            )
        except Exception as error:
            return _raise_api_error(error)

    @application.get(
        "/api/watermarks/artifacts/{operation_id}/{artifact_kind}",
        name="watermark_artifact",
    )
    def watermark_artifact(operation_id: str, artifact_kind: str) -> FileResponse:
        try:
            path = store.operation_artifact_path(operation_id, artifact_kind)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="水印产物不存在") from error
        if path is None:
            raise HTTPException(status_code=404, detail="水印产物不存在")
        return FileResponse(path, media_type="image/png", filename=path.name)

    assets = frontend / "assets"
    if assets.is_dir():
        application.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

    @application.get("/favicon.svg", include_in_schema=False)
    def frontend_favicon() -> FileResponse:
        favicon = frontend / "favicon.svg"
        if not favicon.is_file():
            raise HTTPException(status_code=404, detail="资源不存在")
        return FileResponse(favicon, media_type="image/svg+xml")

    @application.get("/{full_path:path}", include_in_schema=False)
    def frontend_fallback(full_path: str) -> FileResponse:
        if (
            full_path == "api"
            or full_path.startswith("api/")
            or not (frontend / "index.html").is_file()
        ):
            raise HTTPException(status_code=404, detail="资源不存在")
        return FileResponse(
            frontend / "index.html",
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )

    return application


app = create_app()
