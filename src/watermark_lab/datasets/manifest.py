from __future__ import annotations

import csv
import hashlib
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from watermark_lab.datasets.folder import SUPPORTED_EXTENSIONS, ImageSample


@dataclass(frozen=True)
class ManifestEntry:
    dataset: str
    split: str
    sample_id: str
    relative_path: str
    width: int
    height: int
    image_format: str
    sha256: str


MANIFEST_FIELDS = tuple(ManifestEntry.__dataclass_fields__)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    dataset_root: str | Path,
    *,
    dataset: str,
    split: str,
    limit: int | None = None,
) -> list[ManifestEntry]:
    root = Path(dataset_root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"dataset directory does not exist: {root}")
    if not dataset.strip() or not split.strip():
        raise ValueError("dataset and split must be non-empty")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")

    paths = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    if limit is not None:
        paths = paths[:limit]

    entries: list[ManifestEntry] = []
    for path in paths:
        relative_path = path.relative_to(root).as_posix()
        with Image.open(path) as image:
            width, height = image.size
            image_format = image.format or path.suffix.lstrip(".").upper()
        entries.append(
            ManifestEntry(
                dataset=dataset.strip(),
                split=split.strip(),
                sample_id=relative_path,
                relative_path=relative_path,
                width=width,
                height=height,
                image_format=image_format,
                sha256=_file_sha256(path),
            )
        )
    if not entries:
        raise ValueError(f"no supported images found under {root}")
    return entries


def write_manifest(entries: Iterable[ManifestEntry], output_path: str | Path) -> Path:
    rows = [asdict(entry) for entry in entries]
    if not rows:
        raise ValueError("cannot write an empty manifest")
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return destination


def read_manifest(path: str | Path) -> list[ManifestEntry]:
    source = Path(path)
    with source.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or tuple(reader.fieldnames) != MANIFEST_FIELDS:
            raise ValueError(
                f"invalid manifest columns: expected {MANIFEST_FIELDS}, got {reader.fieldnames}"
            )
        entries = [
            ManifestEntry(
                dataset=row["dataset"],
                split=row["split"],
                sample_id=row["sample_id"],
                relative_path=row["relative_path"],
                width=int(row["width"]),
                height=int(row["height"]),
                image_format=row["image_format"],
                sha256=row["sha256"],
            )
            for row in reader
        ]
    if not entries:
        raise ValueError("manifest is empty")
    sample_ids = [entry.sample_id for entry in entries]
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("manifest contains duplicate sample_id values")
    return entries


def iter_manifest_images(
    manifest_path: str | Path,
    dataset_root: str | Path,
    *,
    verify_sha256: bool = False,
) -> Iterator[ImageSample]:
    root = Path(dataset_root).resolve()
    for entry in read_manifest(manifest_path):
        path = (root / Path(entry.relative_path)).resolve()
        try:
            path.relative_to(root)
        except ValueError as error:
            raise ValueError(
                f"manifest path escapes dataset root: {entry.relative_path}"
            ) from error
        if not path.is_file():
            raise FileNotFoundError(f"manifest image does not exist: {path}")
        if verify_sha256 and _file_sha256(path) != entry.sha256:
            raise ValueError(f"SHA-256 mismatch for sample: {entry.sample_id}")
        with Image.open(path) as image:
            array = np.ascontiguousarray(np.asarray(image.convert("RGB"), dtype=np.uint8))
        if array.shape[:2] != (entry.height, entry.width):
            raise ValueError(f"image dimensions changed for sample: {entry.sample_id}")
        yield ImageSample(sample_id=entry.sample_id, path=path, image=array)
