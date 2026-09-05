from __future__ import annotations

import hashlib
from pathlib import Path

from watermark_lab.api import catalog


def _manifest(path: Path, dataset: str, split: str, relative: str, digest: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"dataset,split,sample_id,relative_path,sha256\n{dataset},{split},s1,{relative},{digest}\n",
        encoding="utf-8",
    )


def test_verify_datasets_distinguishes_preparation_and_integrity_states(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(catalog, "project_root", lambda: tmp_path)
    datasets = []
    cases = {"ready": b"ready", "not_prepared": None, "partial": b"partial", "mismatch": b"actual"}
    for dataset_id, content in cases.items():
        root = tmp_path / "data" / dataset_id
        relative = "image.bin"
        expected = hashlib.sha256(content).hexdigest() if content is not None else "0" * 64
        if content is not None and dataset_id != "mismatch":
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            (root / relative).write_bytes(content)
        elif dataset_id == "mismatch":
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            (root / relative).write_bytes(content)
            expected = "1" * 64
        manifests = {}
        for split in ("debug", "calibration", "test"):
            manifest = tmp_path / "manifests" / f"{dataset_id}_{split}.csv"
            _manifest(manifest, dataset_id, split, relative, expected)
            manifests[f"{split}_manifest"] = str(manifest.relative_to(tmp_path))
            manifests[f"{split}_root"] = str(root.relative_to(tmp_path))
        if dataset_id == "partial":
            (root / relative).unlink()
            partial_root = root / "debug"
            partial_root.mkdir(parents=True)
            (partial_root / relative).write_bytes(content)
            manifests["debug_root"] = str(partial_root.relative_to(tmp_path))
        datasets.append({"id": dataset_id, **manifests})
    monkeypatch.setattr(catalog, "load_showcase_config", lambda: {"datasets": datasets})

    reports = {report["id"]: report for report in catalog.verify_datasets()}
    assert reports["ready"]["status"] == "ready"
    assert reports["not_prepared"]["status"] == "not_prepared"
    assert reports["partial"]["status"] == "partial"
    assert reports["mismatch"]["status"] == "mismatch"
