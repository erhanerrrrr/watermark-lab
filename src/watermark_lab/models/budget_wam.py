"""Geometry-v3 model: the existing adaptive embedder plus a frozen budget policy."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from watermark_lab.core.types import DecodeResult, EmbedResult, ImageArray
from watermark_lab.innovations.budget_geometry import BudgetGeometryConfig, BudgetGeometryDecoder
from watermark_lab.models.am_wam import AmWamModel

POLICY_PATH = Path(__file__).resolve().parents[3] / "configs/geometry_v3_selected_policy.json"
POLICY_CODE_PATH = Path(__file__).resolve().parents[1] / "innovations/budget_geometry.py"


def load_budget_policy(path: Path | None = None) -> BudgetGeometryConfig:
    try:
        artifact = json.loads((path or POLICY_PATH).read_text("utf-8"))
        if artifact["selection_split"] != "calibration" or artifact["suite_id"] != "geometry-v3":
            raise ValueError("policy was not selected on geometry-v3 calibration")
        code_hash = hashlib.sha256(POLICY_CODE_PATH.read_bytes()).hexdigest()
        if artifact["policy_code_sha256"] != code_hash:
            raise ValueError("inference policy source differs from its frozen calibration")
        config = BudgetGeometryConfig(**artifact["selection"]["policy"])
        if config.detection_fraction_threshold != artifact["detection_thresholds"]["budget_wam"]:
            raise ValueError("runtime and evaluation detection thresholds disagree")
        return config
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise RuntimeError(
            "缺少有效的 geometry-v3 校准策略，请先完成校准并冻结策略文件。"
        ) from error


class BudgetWamModel(AmWamModel):
    name = "budget_wam"

    def __init__(self, *, budget_config: BudgetGeometryConfig | None = None, **kwargs) -> None:
        config = budget_config or load_budget_policy()
        self._policy_sha256 = (
            hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest() if budget_config is None else None
        )
        super().__init__(**kwargs)
        self._geometry_decoder = BudgetGeometryDecoder(self.base_model, budget_config=config)

    def encode(self, image: ImageArray, message) -> EmbedResult:
        result = super().encode(image, message)
        result.metadata["variant"] = "budget_wam"
        return result

    def decode(self, image: ImageArray) -> DecodeResult:
        result = super().decode(image)
        result.metadata["budget_wam"] = True
        result.metadata["evaluation_suite"] = "geometry-v3"
        result.metadata["policy_sha256"] = self._policy_sha256
        return result
