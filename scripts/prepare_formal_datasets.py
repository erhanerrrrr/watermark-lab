from __future__ import annotations

import argparse
import shutil
import zipfile
from collections.abc import Callable
from pathlib import Path

import requests
from download_debug_datasets import (
    DIFFUSIONDB_URL,
    DIV2K_URL,
    HttpRangeReader,
    _download_file,
    _valid_existing_image,
)
from huggingface_hub import HfApi, hf_hub_url

from watermark_lab.datasets.manifest import build_manifest, write_manifest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "data/raw/formal_v1"
MANIFEST_ROOT = PROJECT_ROOT / "data/manifests"
COCO_ZIP_URL = "http://images.cocodataset.org/zips/val2017.zip"
DIV2K_TRAIN_URL = "https://data.vision.ee.ethz.ch/cvl/DIV2K/DIV2K_train_HR.zip"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def _debug_names(folder: Path) -> set[str]:
    return {path.name for path in folder.glob("*") if path.is_file()}


def _extract_selected(
    session: requests.Session,
    url: str,
    *,
    count: int,
    excluded_names: set[str],
    predicate: Callable[[str], bool],
    sort_key: Callable[[str], object],
    destination: Path,
) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    reader = HttpRangeReader(url, session, cache_blocks=64)
    with zipfile.ZipFile(reader) as archive:
        members = [
            name
            for name in archive.namelist()
            if not name.endswith("/")
            and Path(name).suffix.lower() in IMAGE_EXTENSIONS
            and Path(name).name not in excluded_names
            and predicate(name)
        ]
        members.sort(key=sort_key)
        selected = members[:count]
        if len(selected) != count:
            raise RuntimeError(f"expected {count} images from {url}, found {len(selected)}")
        outputs: list[Path] = []
        for index, member in enumerate(selected, start=1):
            output_path = destination / Path(member).name
            outputs.append(output_path)
            if _valid_existing_image(output_path):
                continue
            temporary = output_path.with_suffix(output_path.suffix + ".part")
            temporary.unlink(missing_ok=True)
            with archive.open(member) as source, temporary.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
            if not _valid_existing_image(temporary):
                temporary.unlink(missing_ok=True)
                raise RuntimeError(f"invalid extracted image: {member}")
            temporary.replace(output_path)
            if index % 20 == 0 or index == count:
                print(f"  extracted {index}/{count}: {destination.name}", flush=True)
        return outputs


def _split_files(files: list[Path], calibration_count: int) -> tuple[list[Path], list[Path]]:
    return files[:calibration_count], files[calibration_count:]


def _move_split(files: list[Path], destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for source in files:
        target = destination / source.name
        if target == source:
            continue
        if _valid_existing_image(target):
            source.unlink(missing_ok=True)
        else:
            source.replace(target)


def _write_fixed_manifest(
    root: Path,
    *,
    dataset: str,
    split: str,
    filename: str,
) -> Path:
    entries = build_manifest(root, dataset=dataset, split=split)
    return write_manifest(entries, MANIFEST_ROOT / filename)


def _prepare_coco(session: requests.Session, output_root: Path) -> None:
    print("[formal COCO: cal40/test200]", flush=True)
    staging = output_root / "coco2017_val/staging"
    excluded = _debug_names(PROJECT_ROOT / "data/raw/debug10/coco2017_val")
    files = _extract_selected(
        session,
        COCO_ZIP_URL,
        count=240,
        excluded_names=excluded,
        predicate=lambda name: Path(name).stem.isdigit(),
        sort_key=lambda name: int(Path(name).stem),
        destination=staging,
    )
    calibration, test = _split_files(files, 40)
    calibration_root = output_root / "coco2017_val/calibration"
    test_root = output_root / "coco2017_val/test"
    _move_split(calibration, calibration_root)
    _move_split(test, test_root)
    _write_fixed_manifest(
        calibration_root,
        dataset="coco2017_val_formal",
        split="calibration",
        filename="coco2017_val_formal_cal40.csv",
    )
    _write_fixed_manifest(
        test_root,
        dataset="coco2017_val_formal",
        split="test",
        filename="coco2017_val_formal_test200.csv",
    )


def _prepare_div2k(session: requests.Session, output_root: Path) -> None:
    print("[formal DIV2K: train cal20/validation test90]", flush=True)
    calibration_root = output_root / "div2k/calibration"
    _extract_selected(
        session,
        DIV2K_TRAIN_URL,
        count=20,
        excluded_names=set(),
        predicate=lambda name: Path(name).stem.isdigit(),
        sort_key=lambda name: int(Path(name).stem),
        destination=calibration_root,
    )
    test_root = output_root / "div2k/test"
    excluded = _debug_names(PROJECT_ROOT / "data/raw/debug10/div2k_valid_hr")
    _extract_selected(
        session,
        DIV2K_URL,
        count=90,
        excluded_names=excluded,
        predicate=lambda name: Path(name).stem.isdigit(),
        sort_key=lambda name: int(Path(name).stem),
        destination=test_root,
    )
    _write_fixed_manifest(
        calibration_root,
        dataset="div2k_formal",
        split="calibration_train",
        filename="div2k_formal_cal20.csv",
    )
    _write_fixed_manifest(
        test_root,
        dataset="div2k_formal",
        split="test_validation",
        filename="div2k_formal_test90.csv",
    )


def _prepare_diffusiondb(session: requests.Session, output_root: Path) -> None:
    print("[formal DiffusionDB: cal40/test200]", flush=True)
    staging = output_root / "diffusiondb_2m/staging"
    excluded = _debug_names(PROJECT_ROOT / "data/raw/debug10/diffusiondb_2m")
    files = _extract_selected(
        session,
        DIFFUSIONDB_URL,
        count=240,
        excluded_names=excluded,
        predicate=lambda name: True,
        sort_key=lambda name: Path(name).name,
        destination=staging,
    )
    calibration, test = _split_files(files, 40)
    calibration_root = output_root / "diffusiondb_2m/calibration"
    test_root = output_root / "diffusiondb_2m/test"
    _move_split(calibration, calibration_root)
    _move_split(test, test_root)
    _write_fixed_manifest(
        calibration_root,
        dataset="diffusiondb_2m_formal",
        split="calibration",
        filename="diffusiondb_2m_formal_cal40.csv",
    )
    _write_fixed_manifest(
        test_root,
        dataset="diffusiondb_2m_formal",
        split="test",
        filename="diffusiondb_2m_formal_test200.csv",
    )


def _prepare_w_bench(session: requests.Session, output_root: Path) -> None:
    print("[formal W-Bench: cal40/test200]", flush=True)
    repo_id = "Shilin-LU/W-Bench"
    prefix = "DET_INVERSION_1K/image/"
    excluded = _debug_names(PROJECT_ROOT / "data/raw/debug10/w_bench_det_inversion")
    remote_files = [
        name
        for name in HfApi().list_repo_files(repo_id, repo_type="dataset")
        if name.startswith(prefix)
        and Path(name).suffix.lower() in IMAGE_EXTENSIONS
        and Path(name).name not in excluded
    ]
    remote_files.sort(key=lambda name: int(Path(name).stem.split("_", 1)[0]))
    selected = remote_files[:240]
    if len(selected) != 240:
        raise RuntimeError(f"expected 240 W-Bench files, found {len(selected)}")
    for index, filename in enumerate(selected, start=1):
        split = "calibration" if index <= 40 else "test"
        destination = output_root / "w_bench_det_inversion" / split / Path(filename).name
        _download_file(session, hf_hub_url(repo_id, filename, repo_type="dataset"), destination)
        if index % 20 == 0:
            print(f"  downloaded {index}/240: W-Bench", flush=True)
    _write_fixed_manifest(
        output_root / "w_bench_det_inversion/calibration",
        dataset="w_bench_det_inversion_formal",
        split="calibration",
        filename="w_bench_det_inversion_formal_cal40.csv",
    )
    _write_fixed_manifest(
        output_root / "w_bench_det_inversion/test",
        dataset="w_bench_det_inversion_formal",
        split="test",
        filename="w_bench_det_inversion_formal_test200.csv",
    )


PREPARERS = {
    "coco": _prepare_coco,
    "div2k": _prepare_div2k,
    "diffusiondb": _prepare_diffusiondb,
    "w_bench": _prepare_w_bench,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare frozen formal-v1 datasets")
    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=tuple(PREPARERS),
        default=tuple(PREPARERS),
    )
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    session = requests.Session()
    session.headers["User-Agent"] = "watermark-lab-course-research/0.1"
    for dataset in args.datasets:
        PREPARERS[dataset](session, args.output_root.resolve())
    print(f"formal-v1 datasets ready: {args.output_root.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
