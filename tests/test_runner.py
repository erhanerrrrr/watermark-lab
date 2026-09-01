import numpy as np

from watermark_lab.attacks.basic import AttackSpec
from watermark_lab.attacks.protocol import AttackCase
from watermark_lab.experiments.runner import run_experiment
from watermark_lab.models.lsb_reference import LSBReferenceModel


def test_runner_completes_identity_round_trip() -> None:
    image = np.arange(96 * 96 * 3, dtype=np.uint32).reshape(96, 96, 3)
    image = (image % 256).astype(np.uint8)
    model = LSBReferenceModel()
    records = run_experiment(model, [("sample", image)], [AttackSpec("identity")], seed=3)

    assert len(records) == 1
    assert records[0].detected
    assert records[0].complete_recovery
    assert records[0].bit_accuracy == 1.0


def test_runner_records_compound_attack_pipeline() -> None:
    image = np.arange(128 * 128 * 3, dtype=np.uint32).reshape(128, 128, 3)
    image = (image % 256).astype(np.uint8)
    case = AttackCase(
        case_id="identity_then_identity",
        category="compound",
        steps=(AttackSpec("identity"), AttackSpec("identity")),
    )
    records = run_experiment(LSBReferenceModel(), [("sample", image)], [case], seed=5)

    assert records[0].attack == "identity_then_identity"
    assert '"category": "compound"' in records[0].attack_parameters
    assert records[0].complete_recovery
