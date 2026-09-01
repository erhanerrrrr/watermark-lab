from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from watermark_lab.core.types import ImageArray

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


@dataclass(frozen=True)
class ImageSample:
    sample_id: str
    path: Path
    image: ImageArray


def iter_image_folder(root: str | Path, limit: int | None = None) -> Iterator[ImageSample]:
    directory = Path(root)
    if not directory.is_dir():
        raise FileNotFoundError(f"dataset directory does not exist: {directory}")

    paths = sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    if limit is not None:
        paths = paths[:limit]

    for path in paths:
        with Image.open(path) as image:
            array = np.ascontiguousarray(np.asarray(image.convert("RGB"), dtype=np.uint8))
        yield ImageSample(sample_id=path.relative_to(directory).as_posix(), path=path, image=array)
