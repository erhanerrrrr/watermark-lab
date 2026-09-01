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
