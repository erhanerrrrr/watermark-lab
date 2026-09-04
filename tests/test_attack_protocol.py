from pathlib import Path

import numpy as np
import pytest

from watermark_lab.attacks.protocol import apply_attack_case, load_attack_protocol


def test_load_and_apply_formal_attack_protocol() -> None:
    protocol = load_attack_protocol(Path("configs/attacks.yaml"))
    image = np.full((64, 64, 3), 128, dtype=np.uint8)
    compound = next(case for case in protocol.cases if case.category == "compound")
    output = apply_attack_case(image, compound, np.random.default_rng(protocol.seed))

    assert protocol.protocol_id == "wm-course-v1"
    assert protocol.version == 1
    assert len(protocol.select(["control"])) == 1
    assert output.shape == image.shape
    assert output.dtype == np.uint8


def test_protocol_rejects_unknown_attack(tmp_path: Path) -> None:
    protocol_path = tmp_path / "invalid.yaml"
    protocol_path.write_text(
        """protocol: {id: invalid, version: 1, seed: 1}
cases:
  - id: invalid
    category: single
    pipeline: [{name: does_not_exist}]
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported attack"):
        load_attack_protocol(protocol_path)


def test_robustness_v2_protocol_is_frozen_and_executable() -> None:
    protocol = load_attack_protocol(Path("configs/robustness_v2_attacks.yaml"))
    values = np.arange(96 * 128 * 3, dtype=np.uint32).reshape(96, 128, 3)
    image = (values % 251).astype(np.uint8)

    assert protocol.protocol_id == "wm-robustness-v2"
    assert protocol.version == 2
    assert len(protocol.cases) == 24
    assert {case.category for case in protocol.cases} == {
        "off_grid_geometry",
        "spatially_varied_local",
        "photometric_unseen",
        "capture_proxy",
    }
    for index, case in enumerate(protocol.cases):
        output = apply_attack_case(image, case, np.random.default_rng(protocol.seed + index))
        assert output.shape == image.shape
        assert output.dtype == np.uint8
