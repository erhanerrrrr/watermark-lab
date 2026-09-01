from __future__ import annotations

from pathlib import Path

from watermark_lab.core.model import WatermarkModel
from watermark_lab.core.types import BitArray, DecodeResult, EmbedResult, ImageArray
from watermark_lab.innovations.content_adaptive import (
    AdaptiveStrengthConfig,
    ContentAdaptiveStrengthController,
)
from watermark_lab.innovations.geometry_sync import GeometrySyncConfig, GeometrySyncDecoder
from watermark_lab.models.wam_adapter import WamBackend, WamModel


class AmWamModel(WatermarkModel):
    """M4 WAM variant with quality-aware embedding and blind geometry sync."""

    name = "am_wam"
    message_bits = 32

    def __init__(
        self,
        *,
        strength: float = 2.0,
        adaptive_strength: bool = True,
        geometry_sync: bool = True,
        adaptive_config: AdaptiveStrengthConfig | None = None,
        geometry_config: GeometrySyncConfig | None = None,
        detection_threshold: float = 0.5,
        minimum_detected_fraction: float = 0.01,
        bit_logit_threshold: float = 0.5,
        source_root: str | Path | None = None,
        checkpoint_path: str | Path | None = None,
        device: str = "auto",
        backend: WamBackend | None = None,
    ) -> None:
        self.base_model = WamModel(
            strength=strength,
            detection_threshold=detection_threshold,
            minimum_detected_fraction=minimum_detected_fraction,
            bit_logit_threshold=bit_logit_threshold,
            source_root=source_root,
            checkpoint_path=checkpoint_path,
            device=device,
            backend=backend,
        )
        self.adaptive_strength = bool(adaptive_strength)
        self.geometry_sync = bool(geometry_sync)
        self._strength_controller = ContentAdaptiveStrengthController(
            self.base_model,
            base_strength=strength,
            config=adaptive_config,
        )
        self._geometry_decoder = GeometrySyncDecoder(
            self.base_model,
            config=geometry_config,
        )

    @property
    def strength(self) -> float:
        return self.base_model.strength

    @strength.setter
    def strength(self, value: float) -> None:
        if value <= 0:
            raise ValueError("strength must be positive")
        self.base_model.strength = float(value)
        self._strength_controller.base_strength = float(value)

    def encode(self, image: ImageArray, message: BitArray) -> EmbedResult:
        source = self.validate_image(image)
        bits = self.validate_message(message)
        if self.adaptive_strength:
            result = self._strength_controller.encode(source, bits)
        else:
            result = self.base_model.encode(source, bits)
        result.metadata.update(
            {
                "variant": "am_wam",
                "adaptive_strength_enabled": self.adaptive_strength,
                "geometry_sync_enabled": self.geometry_sync,
            }
        )
        return result

    def decode(self, image: ImageArray) -> DecodeResult:
        source = self.validate_image(image)
        if self.geometry_sync:
            result = self._geometry_decoder.decode(source)
        else:
            result = self.base_model.decode(source)
        result.metadata.update(
            {
                "am_wam": True,
                "adaptive_strength_enabled": self.adaptive_strength,
                "geometry_sync_enabled": self.geometry_sync,
            }
        )
        return result
