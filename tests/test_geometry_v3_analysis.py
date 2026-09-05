from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.analyze_geometry_v3 import full_decision, paired_ci, thresholds
from watermark_lab.innovations.budget_geometry import BudgetGeometryConfig, CandidateEvidence
from watermark_lab.models.budget_wam import POLICY_CODE_PATH, BudgetWamModel, load_budget_policy
from watermark_lab.models.wam_adapter import WamSpatialPrediction


def test_frozen_loader_requires_calibration_and_valid_budget(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    artifact = {
        "suite_id": "geometry-v3",
        "selection_split": "test",
        "selection": {"policy": asdict(BudgetGeometryConfig())},
        "policy_code_sha256": hashlib.sha256(POLICY_CODE_PATH.read_bytes()).hexdigest(),
        "detection_thresholds": {"budget_wam": BudgetGeometryConfig().detection_fraction_threshold},
    }
    path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(RuntimeError):
        load_budget_policy(path)
    artifact["selection_split"] = "calibration"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    assert load_budget_policy(path).max_candidates == 7
    artifact["selection"]["policy"]["max_candidates"] = 100
    path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(RuntimeError):
        load_budget_policy(path)


@pytest.mark.parametrize("mismatch", ["policy_code_sha256", "detection_thresholds"])
def test_live_model_rejects_policy_source_or_threshold_drift(tmp_path: Path, mismatch: str) -> None:
    artifact = {
        "suite_id": "geometry-v3", "selection_split": "calibration",
        "selection": {"policy": asdict(BudgetGeometryConfig())},
        "policy_code_sha256": hashlib.sha256(POLICY_CODE_PATH.read_bytes()).hexdigest(),
        "detection_thresholds": {"budget_wam": BudgetGeometryConfig().detection_fraction_threshold},
    }
    artifact[mismatch] = "0" * 64 if mismatch == "policy_code_sha256" else {"budget_wam": 0.9}
    path = tmp_path / "changed_policy.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(RuntimeError):
        load_budget_policy(path)


def test_full_ungated_control_can_recover_without_border_evidence() -> None:
    from scripts.analyze_geometry_v3 import ORIGINAL_ORDER

    identity = CandidateEvidence("identity", 0.6, 0.8, 0.9, 0.8, 0.1, 0.3, (-1.0,) * 32)
    row = {"border_evidence": 0, "evidence": {}}
    for name in ORIGINAL_ORDER:
        row["evidence"][name] = CandidateEvidence(name, 0.9, 0.9, 0.99, 1, 2, 2, (3.0,) * 32)
    row["evidence"]["identity"] = identity
    gated, _, visited = full_decision(row, fused=True, gated=True)
    ungated, _, all_visited = full_decision(row, fused=False)
    assert not gated.any()
    assert ungated.all()
    assert visited == ["identity"]
    assert len(all_visited) == 10


def test_calibration_cutoffs_use_only_negative_labels_and_strict_maximum() -> None:
    frame = pd.DataFrame(
        {"method": ["m"] * 3, "positive": [False, False, True], "detection_score": [0.1, 0.2, 0.9]}
    )
    threshold = thresholds(frame)["m"]
    assert 0.2 < threshold < 0.9


def test_paired_interval_clusters_repeated_attacks_within_images() -> None:
    rows = []
    for image_id, old, new in (("a", 0, 1), ("b", 1, 0)):
        for attack in ("one", "two"):
            for method, recovered in (("full_best", old), ("budget_wam", new)):
                rows.append(
                    {
                        "dataset": "d",
                        "image_id": image_id,
                        "attack": attack,
                        "positive": True,
                        "method": method,
                        "complete_recovery": recovered,
                    }
                )
    frame = pd.DataFrame(rows)
    result = paired_ci(frame, "full_best", iterations=1000, seed=8)
    assert result["image_units"] == 2
    assert result["paired_records"] == 4
    assert result["rescued"] == result["regressed"] == 2
    assert result["recovery_gain_pp"] == 0
    assert result["ci95_pp"] == [-100, 100]


class Backend:
    device_name = "fixture"
    checkpoint_sha256 = "fixture"

    def encode(self, image, message, *, strength):
        self.message = message.copy()
        return image.copy()

    def predict(self, image):
        logits = np.broadcast_to((self.message * 6.0 - 3)[:, None, None], (32, 8, 8)).copy()
        return WamSpatialPrediction(np.full((8, 8), 0.99), logits)


def test_budget_model_reuses_encoder_and_exposes_live_decision_metadata() -> None:
    model = BudgetWamModel(
        backend=Backend(), budget_config=BudgetGeometryConfig(), adaptive_strength=False
    )
    image = np.full((128, 160, 3), 128, np.uint8)
    expected = np.asarray([0, 1] * 16, np.uint8)
    encoded = model.encode(image, expected)
    decoded = model.decode(encoded.image)
    np.testing.assert_array_equal(decoded.message, expected)
    assert model.name == "budget_wam"
    assert encoded.metadata["variant"] == "budget_wam"
    assert decoded.metadata["candidate_count"] == 1
    assert decoded.metadata["evaluation_suite"] == "geometry-v3"
    assert decoded.metadata["stop_reason"] == "reliable_identity"
