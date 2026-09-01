from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from watermark_lab.core.model import WatermarkModel


@dataclass(frozen=True)
class ModelSpec:
    name: str
    stage: str
    role: str
    factory: Callable[..., WatermarkModel] | None = None

    @property
    def ready(self) -> bool:
        return self.factory is not None


def _lsb_factory(**kwargs: Any) -> WatermarkModel:
    from watermark_lab.models.lsb_reference import LSBReferenceModel

    return LSBReferenceModel(**kwargs)


def _dwt_dct_factory(**kwargs: Any) -> WatermarkModel:
    from watermark_lab.models.dwt_dct import DwtDctWatermarkModel

    return DwtDctWatermarkModel(**kwargs)


def _trustmark_factory(**kwargs: Any) -> WatermarkModel:
    from watermark_lab.models.trustmark_adapter import TrustMarkQModel

    return TrustMarkQModel(**kwargs)


def _wam_factory(**kwargs: Any) -> WatermarkModel:
    from watermark_lab.models.wam_adapter import WamModel

    return WamModel(**kwargs)


def _am_wam_factory(**kwargs: Any) -> WatermarkModel:
    from watermark_lab.models.am_wam import AmWamModel

    return AmWamModel(**kwargs)


MODEL_SPECS: tuple[ModelSpec, ...] = (
    ModelSpec("lsb_reference", "M1", "管线自检模型", _lsb_factory),
    ModelSpec("dwt_dct", "M2", "传统频域主基线", _dwt_dct_factory),
    ModelSpec("trustmark_q", "M2", "强全局深度水印基线", _trustmark_factory),
    ModelSpec("wam", "M3", "核心前沿复现模型", _wam_factory),
    ModelSpec("am_wam", "M4", "几何同步与内容自适应改进模型", _am_wam_factory),
    ModelSpec("hidden", "可选", "早期端到端深度水印基线"),
)


def list_model_specs() -> tuple[ModelSpec, ...]:
    return MODEL_SPECS


def create_model(name: str, **kwargs: Any) -> WatermarkModel:
    for spec in MODEL_SPECS:
        if spec.name == name:
            if spec.factory is None:
                raise RuntimeError(
                    f"model '{name}' is planned for milestone {spec.stage} "
                    "but is not implemented yet"
                )
            return spec.factory(**kwargs)
    available = ", ".join(spec.name for spec in MODEL_SPECS)
    raise KeyError(f"unknown model '{name}'. Known models: {available}")
