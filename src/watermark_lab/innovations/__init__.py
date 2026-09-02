"""Inference-time innovations used by the AM-WAM model."""

from watermark_lab.innovations.content_adaptive import (
    AdaptiveStrengthConfig,
    ContentAdaptiveStrengthController,
)
from watermark_lab.innovations.geometry_sync import (
    GeometrySyncConfig,
    GeometrySyncDecoder,
)

__all__ = [
    "AdaptiveStrengthConfig",
    "ContentAdaptiveStrengthController",
    "GeometrySyncConfig",
    "GeometrySyncDecoder",
]
from watermark_lab.innovations.multi_message import (
    AdaptiveSoftMessageClusterer,
    MultiEmbedResult,
    MultiMessageConfig,
    MultiMessageResult,
    OfficialHardDbscanDecoder,
    embed_multiple_regions,
    rectangular_region_masks,
    small_patch_region_masks,
)

__all__ = [
    "AdaptiveSoftMessageClusterer",
    "MultiEmbedResult",
    "MultiMessageConfig",
    "MultiMessageResult",
    "OfficialHardDbscanDecoder",
    "embed_multiple_regions",
    "rectangular_region_masks",
    "small_patch_region_masks",
]
