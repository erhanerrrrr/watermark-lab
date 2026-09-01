from __future__ import annotations

import csv
import json
import math
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from watermark_lab.attacks.basic import AttackSpec, apply_attack
from watermark_lab.attacks.protocol import AttackCase, apply_attack_case
from watermark_lab.core.model import WatermarkModel
from watermark_lab.core.types import BitArray, ImageArray
from watermark_lab.metrics.image_quality import psnr
from watermark_lab.metrics.message import ber, bit_accuracy, complete_recovery


@dataclass(frozen=True)
class ExperimentRecord:
    image_id: str
    model: str
    embed_metadata: str
    attack: str
    attack_parameters: str
    message_bits: int
    detected: bool
    decode_confidence: float
    bit_accuracy: float
    ber: float
    complete_recovery: bool
    embed_psnr_db: float
    post_attack_psnr_db: float
    encode_ms: float
    decode_ms: float


def _finite_or_text(value: float) -> float | str:
    return value if math.isfinite(value) else "inf"


def run_experiment(
    model: WatermarkModel,
    images: Iterable[tuple[str, ImageArray]],
    attacks: Iterable[AttackSpec | AttackCase],
    *,
    seed: int = 42,
    fixed_message: BitArray | None = None,
) -> list[ExperimentRecord]:
    generator = np.random.default_rng(seed)
    attack_list = tuple(attacks)
    records: list[ExperimentRecord] = []

    for image_id, image in images:
        message = (
            model.validate_message(fixed_message)
            if fixed_message is not None
            else generator.integers(0, 2, size=model.message_bits, dtype=np.uint8)
        )

        encode_started = time.perf_counter()
        embedded = model.encode(image, message)
        encode_ms = (time.perf_counter() - encode_started) * 1000.0
        embed_quality = psnr(image, embedded.image)

        for attack in attack_list:
            if isinstance(attack, AttackCase):
                attack_name = attack.case_id
                attack_parameters = attack.parameters_for_record()
                attacked = apply_attack_case(embedded.image, attack, generator)
            else:
                attack_name = attack.name
                attack_parameters = attack.parameters
                attacked = apply_attack(embedded.image, attack, generator)
            decode_started = time.perf_counter()
            decoded = model.decode(attacked)
            decode_ms = (time.perf_counter() - decode_started) * 1000.0
            records.append(
                ExperimentRecord(
                    image_id=image_id,
                    model=model.name,
                    embed_metadata=json.dumps(
                        embedded.metadata, ensure_ascii=False, sort_keys=True
                    ),
                    attack=attack_name,
                    attack_parameters=json.dumps(
                        attack_parameters, ensure_ascii=False, sort_keys=True
                    ),
                    message_bits=model.message_bits,
                    detected=decoded.detected,
                    decode_confidence=decoded.confidence,
                    bit_accuracy=bit_accuracy(message, decoded.message),
                    ber=ber(message, decoded.message),
                    complete_recovery=complete_recovery(message, decoded.message),
                    embed_psnr_db=embed_quality,
                    post_attack_psnr_db=psnr(image, attacked),
                    encode_ms=encode_ms,
                    decode_ms=decode_ms,
                )
            )
    return records


def write_results_csv(records: Iterable[ExperimentRecord], output_path: str | Path) -> Path:
    rows = [asdict(record) for record in records]
    if not rows:
        raise ValueError("cannot write an empty experiment")
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            row["embed_psnr_db"] = _finite_or_text(float(row["embed_psnr_db"]))
            row["post_attack_psnr_db"] = _finite_or_text(float(row["post_attack_psnr_db"]))
            writer.writerow(row)
    return destination
