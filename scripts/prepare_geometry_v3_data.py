"""Recover new project-disjoint images; never edit old manifests or select by model outcome."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import requests
import yaml
from huggingface_hub import HfApi, hf_hub_url

from watermark_lab.datasets.manifest import build_manifest, read_manifest, write_manifest

if __package__ in {None, ""}:
    from download_debug_datasets import _download_file
    from prepare_formal_datasets import COCO_ZIP_URL, DIV2K_TRAIN_URL, _extract_selected
else:
    from .download_debug_datasets import _download_file
    from .prepare_formal_datasets import COCO_ZIP_URL, DIV2K_TRAIN_URL, _extract_selected

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("coco", "div2k", "diffusiondb", "w_bench")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datasets", nargs="+", choices=SOURCES, default=SOURCES)
    args = parser.parse_args()
    config = yaml.safe_load((ROOT / "configs/geometry_v3_protocol.yaml").read_text("utf-8"))
    historical = [
        entry
        for path in (ROOT / "data/manifests").glob("*.csv")
        if not path.name.startswith("geometry_v3_")
        for entry in read_manifest(path)
    ]
    excluded_names = {Path(entry.relative_path).name for entry in historical}
    excluded_hashes = {entry.sha256 for entry in historical}
    metadata_path = ROOT / config["data"]["metadata"]
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text("utf-8"))
    else:
        api = HfApi()
        metadata = {
            "selection": config["suite"]["selection"],
            "historical_names": sorted(excluded_names),
            "historical_sha256": sorted(excluded_hashes),
            "diffusiondb_revision": api.repo_info("poloclub/diffusiondb", repo_type="dataset").sha,
            "w_bench_revision": api.repo_info("Shilin-LU/W-Bench", repo_type="dataset").sha,
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), "utf-8")
    if set(metadata["historical_sha256"]) != excluded_hashes:
        raise RuntimeError("historical manifests changed after source selection was frozen")
    calibration_count = config["suite"]["calibration_per_dataset"]
    count = calibration_count + config["suite"]["test_per_dataset"]

    def prepare(dataset: str) -> tuple[str, set[str]]:
        session = requests.Session()
        session.headers["User-Agent"] = "watermark-lab/geometry-v3"
        destination = ROOT / config["data"]["roots"] / dataset
        if dataset == "w_bench":
            revision = metadata["w_bench_revision"]
            names = [
                name
                for name in HfApi().list_repo_files(
                    "Shilin-LU/W-Bench", repo_type="dataset", revision=revision
                )
                if name.startswith("DET_INVERSION_1K/image/")
                and Path(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
                and Path(name).name not in excluded_names
            ]
            names.sort(key=lambda name: int(Path(name).stem.split("_", 1)[0]))
            for index, name in enumerate(names[:count]):
                _download_file(
                    session,
                    hf_hub_url("Shilin-LU/W-Bench", name, repo_type="dataset", revision=revision),
                    destination / Path(name).name,
                )
                print(f"download {dataset} {index + 1}/{count}", flush=True)
        else:
            url = {"coco": COCO_ZIP_URL, "div2k": DIV2K_TRAIN_URL}.get(dataset)
            if dataset == "diffusiondb":
                url = hf_hub_url(
                    "poloclub/diffusiondb",
                    "images/part-000001.zip",
                    repo_type="dataset",
                    revision=metadata["diffusiondb_revision"],
                )
            _extract_selected(
                session,
                url,
                count=count,
                excluded_names=excluded_names,
                predicate=lambda name: True,
                sort_key=lambda name: Path(name).name,
                destination=destination,
            )
        entries = build_manifest(destination, dataset=f"geometry_v3_{dataset}", split="pending")
        if dataset == "w_bench":
            entries.sort(key=lambda entry: int(Path(entry.sample_id).stem.split("_", 1)[0]))
        if len(entries) != count:
            raise RuntimeError(f"{dataset}: expected exactly {count} images, got {len(entries)}")
        hashes = {entry.sha256 for entry in entries}
        if len(hashes) != count or hashes & excluded_hashes:
            raise RuntimeError(f"{dataset}: duplicate or historical SHA-256 overlap")
        for split, selected in (
            ("calibration", entries[:calibration_count]),
            ("test", entries[calibration_count:]),
        ):
            path = ROOT / f"{config['data']['manifest_prefix']}_{dataset}_{split}.csv"
            chosen = [replace(entry, split=split) for entry in selected]
            if path.exists() and read_manifest(path) != chosen:
                raise RuntimeError(f"refusing to change frozen manifest {path}")
            write_manifest(chosen, path)
        print(
            f"ready {dataset}: {calibration_count} calibration + {count - calibration_count} test",
            flush=True,
        )
        return dataset, hashes

    hashes_seen: set[str] = set()
    with ThreadPoolExecutor(max_workers=4) as pool:
        for dataset, hashes in pool.map(prepare, args.datasets):
            if hashes_seen & hashes:
                raise RuntimeError(f"cross-dataset duplicate SHA-256: {dataset}")
            hashes_seen.update(hashes)
    print("Requested geometry-v3 sources verified; no overlap with historical image hashes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
