from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from watermark_lab.api import research
from watermark_lab.api.app import create_app


def test_evidence_is_portable_and_export_matches_api(tmp_path: Path) -> None:
    client = TestClient(create_app(storage_dir=tmp_path / "store",
                                  frontend_dir=tmp_path / "frontend"))
    response = client.get("/api/research/evidence")
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "tracked_evidence_snapshot"
    assert payload["records"] == 121440
    assert len(payload["rows"]) == 5 * 45
    assert len(payload["sensitivity"]) == 44
    overall = payload["rows"][0]
    counts = overall["comparison"]
    assert sum(counts[key] for key in ("rescued", "regressed", "both_recovered", "both_failed")) \
        == overall["paired_records"]
    assert counts["recovery_gain_pp"] == pytest.approx(
        (counts["rescued"] - counts["regressed"]) / overall["paired_records"] * 100)
    export = client.get("/api/research/evidence/export.json")
    assert "attachment" in export.headers["content-disposition"]
    assert export.json() == payload


@pytest.mark.parametrize("contents", [None, "{}", "not-json"])
def test_missing_or_invalid_evidence_has_explicit_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, contents: str | None
) -> None:
    path = tmp_path / "evidence.json"
    if contents is not None:
        path.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(research, "EVIDENCE_PATH", path)
    client = TestClient(create_app(storage_dir=tmp_path / "store"))
    assert client.get("/api/research/evidence").status_code == 503
    assert client.get("/api/research/evidence/export.json").status_code == 503


def test_nonfinite_evidence_is_rejected_before_json_serialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = json.loads(research.EVIDENCE_PATH.read_text(encoding="utf-8"))
    payload["rows"][0]["comparison"]["recovery_gain_pp"] = float("nan")
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(research, "EVIDENCE_PATH", path)
    client = TestClient(create_app(storage_dir=tmp_path / "store"))
    assert client.get("/api/research/evidence").status_code == 503
    assert client.get("/api/research/evidence/export.json").status_code == 503
