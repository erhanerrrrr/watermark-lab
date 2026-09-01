from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

ImageArray = NDArray[np.uint8]
BitArray = NDArray[np.uint8]
FloatMap = NDArray[np.float32]


@dataclass(frozen=True)
class ModelCapabilities:
    detection: bool = True
    localization: bool = False
    multiple_messages: bool = False
    arbitrary_resolution: bool = True


@dataclass
class EmbedResult:
    image: ImageArray
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DecodeResult:
    message: BitArray
    detected: bool
    confidence: float
    localization: FloatMap | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
