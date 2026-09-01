from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from watermark_lab.attacks.basic import AttackSpec, apply_attack, supported_attacks
from watermark_lab.core.types import ImageArray


@dataclass(frozen=True)
class AttackCase:
    case_id: str
    category: str
    steps: tuple[AttackSpec, ...]

    def parameters_for_record(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "pipeline": [
                {"name": step.name, **step.parameters}
                for step in self.steps
            ],
        }


@dataclass(frozen=True)
class AttackProtocol:
    protocol_id: str
    version: int
    seed: int
    cases: tuple[AttackCase, ...]

    def select(self, categories: Iterable[str] | None = None) -> tuple[AttackCase, ...]:
        if categories is None:
            return self.cases
        selected = set(categories)
        return tuple(case for case in self.cases if case.category in selected)


def _require_mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a mapping")
    return value


def load_attack_protocol(path: str | Path) -> AttackProtocol:
    source = Path(path)
    with source.open("r", encoding="utf-8") as stream:
        raw = _require_mapping(yaml.safe_load(stream), "attack protocol")

    metadata = _require_mapping(raw.get("protocol"), "protocol metadata")
    protocol_id = str(metadata.get("id", "")).strip()
    if not protocol_id:
        raise ValueError("protocol.id must be non-empty")
    version = int(metadata.get("version", 0))
    seed = int(metadata.get("seed", 0))
    if version < 1:
        raise ValueError("protocol.version must be at least 1")

    raw_cases = raw.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("cases must be a non-empty list")
    known_attacks = set(supported_attacks())
    cases: list[AttackCase] = []
    case_ids: set[str] = set()
    for case_index, raw_case in enumerate(raw_cases):
        case = _require_mapping(raw_case, f"cases[{case_index}]")
        case_id = str(case.get("id", "")).strip()
        category = str(case.get("category", "")).strip()
        if not case_id or not category:
            raise ValueError(f"cases[{case_index}] requires id and category")
        if case_id in case_ids:
            raise ValueError(f"duplicate attack case id: {case_id}")
        case_ids.add(case_id)
        raw_steps = case.get("pipeline")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError(f"attack case '{case_id}' requires a non-empty pipeline")

        steps: list[AttackSpec] = []
        for step_index, raw_step in enumerate(raw_steps):
            step = _require_mapping(raw_step, f"{case_id}.pipeline[{step_index}]").copy()
            name = str(step.pop("name", "")).strip()
            if name not in known_attacks:
                raise ValueError(f"attack case '{case_id}' uses unsupported attack: {name}")
            steps.append(AttackSpec(name=name, parameters=step))
        cases.append(AttackCase(case_id=case_id, category=category, steps=tuple(steps)))

    return AttackProtocol(
        protocol_id=protocol_id,
        version=version,
        seed=seed,
        cases=tuple(cases),
    )


def apply_attack_case(
    image: ImageArray,
    case: AttackCase,
    rng: np.random.Generator | None = None,
) -> ImageArray:
    output = np.array(image, copy=True)
    for step in case.steps:
        output = apply_attack(output, step, rng)
    return output
