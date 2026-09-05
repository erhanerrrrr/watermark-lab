from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from watermark_lab.api import geometry_research
from watermark_lab.api.app import create_app


def test_geometry_evidence_is_complete_and_export_matches(tmp_path: Path) -> None:
    client = TestClient(create_app(storage_dir=tmp_path / "store"))
    response = client.get("/api/research/geometry-v3")
    assert response.status_code == 200
    evidence = response.json()
    assert evidence["suite_id"] == "geometry-v3"
    assert evidence["calibration_images"] == 48
    assert evidence["test_images"] == 80
    assert len(evidence["methods"]) == 6
    assert evidence["positive_records_per_method"] == 80 * 16
    assert evidence["negative_records_per_method"] == 80 * 4
    assert len(evidence["by_family"]) == 8 * 3
    assert len(evidence["by_dataset"]) == 4 * 3
    assert evidence["timing"]["live_replay_bitwise_verified"]
    assert evidence["timing"]["measured_conditions"] == 12 * 4
    for pair in evidence["paired"]:
        assert pair["image_units"] == 80
        assert pair["recovery_gain_pp"] == pytest.approx(
            100 * (pair["rescued"] - pair["regressed"]) / pair["paired_records"]
        )
        assert pair["recovery_gain_pp"] == pytest.approx(
            100 * (pair["budget_recovery"] - pair["baseline_recovery"])
        )
    export = client.get("/api/research/geometry-v3/export.json")
    assert "attachment" in export.headers["content-disposition"]
    assert export.json() == evidence


@pytest.mark.parametrize("invalid", ["missing", "suite", "counts", "nonfinite", "budget"])
def test_geometry_invalid_evidence_fails_explicitly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    path = tmp_path / "evidence.json"
    if invalid != "missing":
        evidence = json.loads(geometry_research.GEOMETRY_EVIDENCE_PATH.read_text("utf-8"))
        if invalid == "suite":
            evidence["suite_id"] = "formal-v1"
        elif invalid == "counts":
            evidence["test_images"] = 81
        elif invalid == "nonfinite":
            evidence["methods"][0]["complete_recovery"] = float("nan")
        else:
            evidence["policy"]["max_candidates"] = 11
        path.write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setattr(geometry_research, "GEOMETRY_EVIDENCE_PATH", path)
    client = TestClient(create_app(storage_dir=tmp_path / "store"))
    for suffix in ("", "/export.json"):
        assert client.get(f"/api/research/geometry-v3{suffix}").status_code == 503
