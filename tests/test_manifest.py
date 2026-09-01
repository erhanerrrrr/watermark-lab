from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from watermark_lab.datasets.manifest import (
    build_manifest,
    iter_manifest_images,
    read_manifest,
    write_manifest,
)


def _save_image(path: Path, value: int) -> None:
    array = np.full((24, 32, 3), value, dtype=np.uint8)
    Image.fromarray(array).save(path)


def test_manifest_round_trip_and_deterministic_order(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    root.mkdir()
    _save_image(root / "b.png", 20)
    _save_image(root / "a.png", 10)
    entries = build_manifest(root, dataset="fixture", split="val")
    manifest_path = write_manifest(entries, tmp_path / "manifest.csv")

    loaded = read_manifest(manifest_path)
    samples = list(iter_manifest_images(manifest_path, root, verify_sha256=True))

    assert [entry.sample_id for entry in loaded] == ["a.png", "b.png"]
    assert [sample.sample_id for sample in samples] == ["a.png", "b.png"]
    assert loaded[0].width == 32
    assert loaded[0].height == 24
    assert len(loaded[0].sha256) == 64


def test_manifest_detects_changed_file(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    root.mkdir()
    image_path = root / "sample.png"
    _save_image(image_path, 10)
    manifest_path = write_manifest(
        build_manifest(root, dataset="fixture", split="val"),
        tmp_path / "manifest.csv",
    )
    _save_image(image_path, 11)

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        list(iter_manifest_images(manifest_path, root, verify_sha256=True))
