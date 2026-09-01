import csv
from pathlib import Path

import numpy as np
from PIL import Image

from watermark_lab.cli import main


def test_cli_manifest_to_dwt_dct_result(tmp_path: Path) -> None:
    dataset_root = tmp_path / "images"
    dataset_root.mkdir()
    axis = np.linspace(0, 255, 128, dtype=np.uint8)
    x_grid, y_grid = np.meshgrid(axis, axis)
    image = np.stack((x_grid, y_grid, np.bitwise_xor(x_grid, y_grid)), axis=2)
    Image.fromarray(image).save(dataset_root / "sample.png")
    manifest_path = tmp_path / "manifest.csv"
    result_path = tmp_path / "results.csv"

    assert (
        main(
            [
                "build-manifest",
                "--dataset",
                "fixture",
                "--split",
                "test",
                "--root",
                str(dataset_root),
                "--output",
                str(manifest_path),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "run-manifest",
                "--model",
                "dwt_dct",
                "--manifest",
                str(manifest_path),
                "--dataset-root",
                str(dataset_root),
                "--attacks-config",
                str(Path("configs/attacks.yaml").resolve()),
                "--categories",
                "control",
                "--verify-sha256",
                "--output",
                str(result_path),
            ]
        )
        == 0
    )

    with result_path.open("r", newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["model"] == "dwt_dct"
    assert rows[0]["attack"] == "clean"
    assert rows[0]["complete_recovery"] == "True"
