from __future__ import annotations

import hashlib
import io
import math
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError

from watermark_lab.api.schemas import DecodeResponse, ExperimentRecord
from watermark_lab.attacks.basic import AttackSpec, apply_attack
from watermark_lab.attacks.protocol import AttackCase, apply_attack_case
from watermark_lab.core.registry import create_model
from watermark_lab.core.types import BitArray, ImageArray
from watermark_lab.metrics.image_quality import psnr, ssim
from watermark_lab.metrics.message import ber, bit_accuracy, complete_recovery

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
SUPPORTED_API_MODELS = ("lsb_reference", "dwt_dct", "trustmark_q", "wam", "am_wam")
SUPPORTED_API_ATTACKS = ("none", "jpeg", "noise", "crop", "resize", "rotate", "tamper", "compound")

_model_lock = threading.Lock()


@dataclass(frozen=True)
class CompletedExperiment:
    record: ExperimentRecord
    images: dict[str, ImageArray]


def read_rgb_image(payload: bytes) -> ImageArray:
    if not payload:
        raise ValueError("上传图片不能为空")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise ValueError("图片不能超过 15 MB")
    try:
        with Image.open(io.BytesIO(payload)) as source:
            width, height = source.size
            if width * height > MAX_IMAGE_PIXELS:
                raise ValueError("图片像素数量不能超过 2500 万")
            if width < 128 or height < 128:
                raise ValueError("图片尺寸至少为 128×128")
            image = np.asarray(source.convert("RGB"), dtype=np.uint8)
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("无法读取图片，请上传有效的 PNG/JPEG/WebP 文件") from error
    return np.ascontiguousarray(image)


def message_to_bits(message: str, width: int) -> BitArray:
    normalized = message.strip()
    if not normalized:
        raise ValueError("水印消息不能为空")
    if len(normalized) == width and set(normalized) <= {"0", "1"}:
        return np.fromiter((int(value) for value in normalized), dtype=np.uint8)
    digest = hashlib.sha256(normalized.encode("utf-8")).digest()
    return np.unpackbits(np.frombuffer(digest, dtype=np.uint8))[:width].astype(np.uint8)


def _bounded(value: float, minimum: float, maximum: float) -> float:
    return min(max(float(value), minimum), maximum)


def build_attack(attack: str, parameter: float) -> AttackSpec | AttackCase:
    if attack not in SUPPORTED_API_ATTACKS:
        raise ValueError(f"不支持的攻击类型：{attack}")
    if attack == "none":
        return AttackSpec("identity")
    if attack == "jpeg":
        return AttackSpec("jpeg", {"quality": int(_bounded(parameter, 1, 100))})
    if attack == "noise":
        return AttackSpec("gaussian_noise", {"sigma": _bounded(parameter, 0, 0.2)})
    if attack == "crop":
        return AttackSpec("crop_resize", {"keep_ratio": _bounded(parameter, 0.1, 1)})
    if attack == "resize":
        return AttackSpec("resize_roundtrip", {"scale": _bounded(parameter, 0.1, 2)})
    if attack == "rotate":
        return AttackSpec("rotation", {"angle": _bounded(parameter, -180, 180)})
    if attack == "tamper":
        return AttackSpec("local_splice", {"mask_ratio": _bounded(parameter, 0.001, 0.9)})
    return AttackCase(
        case_id="api_compound",
        category="compound",
        steps=(
            AttackSpec("gaussian_blur", {"radius": 1.0}),
            AttackSpec("contrast", {"factor": 1.15}),
            AttackSpec("jpeg", {"quality": 80}),
        ),
    )


@lru_cache(maxsize=3)
def get_wam_backend(device: str):
    from watermark_lab.models.wam_adapter import OfficialWamBackend

    return OfficialWamBackend(device=device)


@lru_cache(maxsize=12)
def get_model(model_name: str, strength: float, device: str):
    if model_name not in SUPPORTED_API_MODELS:
        raise ValueError(f"不支持的模型：{model_name}")
    arguments: dict[str, Any] = {}
    if model_name != "lsb_reference":
        arguments["strength"] = strength
    if model_name in {"wam", "am_wam"}:
        arguments["device"] = device
        # WAM and AM-WAM are lightweight wrappers around the same official network.
        # Sharing one backend per device avoids loading duplicate GPU weights when
        # users switch model or strength in the Web interface.
        arguments["backend"] = get_wam_backend(device)
    return create_model(model_name, **arguments)


def _finite(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _identifier(prefix: str) -> str:
    return f"{prefix}-{datetime.now().strftime('%y%m%d')}-{uuid.uuid4().hex[:10].upper()}"


def run_single_experiment(
    *,
    image_payload: bytes,
    image_name: str,
    model_name: str,
    message: str,
    strength: float,
    attack_name: str,
    attack_parameter: float,
    device: str,
) -> CompletedExperiment:
    image = read_rgb_image(image_payload)
    attack = build_attack(attack_name, attack_parameter)
    generator = np.random.default_rng(42)

    # Official inference modules reuse mutable objects. Serialize one process's
    # inference while keeping HTTP file and catalog requests responsive.
    with _model_lock:
        model = get_model(model_name, float(strength), device)
        bits = message_to_bits(message, model.message_bits)
        encode_started = time.perf_counter()
        embedded = model.encode(image, bits)
        encode_ms = (time.perf_counter() - encode_started) * 1000.0
        attacked = (
            apply_attack_case(embedded.image, attack, generator)
            if isinstance(attack, AttackCase)
            else apply_attack(embedded.image, attack, generator)
        )
        decode_started = time.perf_counter()
        decoded = model.decode(attacked)
        decode_ms = (time.perf_counter() - decode_started) * 1000.0

    record = ExperimentRecord(
        id=_identifier("EXP"),
        created_at=datetime.now().astimezone(),
        image_name=image_name,
        model=model.name,
        message_bits=model.message_bits,
        expected_message="".join(map(str, bits.tolist())),
        decoded_message="".join(map(str, decoded.message.tolist())),
        attack=attack_name,
        attack_parameters=(
            attack.parameters_for_record()
            if isinstance(attack, AttackCase)
            else {"name": attack.name, **attack.parameters}
        ),
        detected=decoded.detected,
        detection_confidence=float(np.clip(decoded.confidence, 0.0, 1.0)),
        bit_accuracy=bit_accuracy(bits, decoded.message),
        ber=ber(bits, decoded.message),
        complete_recovery=complete_recovery(bits, decoded.message),
        embed_psnr_db=_finite(psnr(image, embedded.image)),
        embed_ssim=ssim(image, embedded.image),
        post_attack_psnr_db=_finite(psnr(image, attacked)),
        post_attack_ssim=ssim(image, attacked),
        encode_ms=encode_ms,
        decode_ms=decode_ms,
        metadata={"embed": embedded.metadata, "decode": decoded.metadata, "device": device},
    )
    return CompletedExperiment(
        record=record,
        images={"original": image, "embedded": embedded.image, "attacked": attacked},
    )


def run_embed(
    *,
    image_payload: bytes,
    image_name: str,
    model_name: str,
    message: str,
    strength: float,
    device: str,
) -> tuple[str, datetime, ImageArray, dict[str, Any]]:
    image = read_rgb_image(image_payload)
    with _model_lock:
        model = get_model(model_name, float(strength), device)
        bits = message_to_bits(message, model.message_bits)
        started = time.perf_counter()
        embedded = model.encode(image, bits)
        encode_ms = (time.perf_counter() - started) * 1000.0
    values = {
        "image_name": image_name,
        "model": model.name,
        "message_bits": model.message_bits,
        "expected_message": "".join(map(str, bits.tolist())),
        "embed_psnr_db": _finite(psnr(image, embedded.image)),
        "embed_ssim": ssim(image, embedded.image),
        "encode_ms": encode_ms,
        "metadata": {"embed": embedded.metadata, "device": device},
    }
    return _identifier("EMB"), datetime.now().astimezone(), embedded.image, values


def run_decode(
    *,
    image_payload: bytes,
    image_name: str,
    model_name: str,
    expected_message: str | None,
    strength: float,
    device: str,
) -> DecodeResponse:
    image = read_rgb_image(image_payload)
    with _model_lock:
        model = get_model(model_name, float(strength), device)
        started = time.perf_counter()
        decoded = model.decode(image)
        decode_ms = (time.perf_counter() - started) * 1000.0
    expected = message_to_bits(expected_message, model.message_bits) if expected_message else None
    return DecodeResponse(
        image_name=image_name,
        model=model.name,
        message_bits=model.message_bits,
        decoded_message="".join(map(str, decoded.message.tolist())),
        detected=decoded.detected,
        detection_confidence=float(np.clip(decoded.confidence, 0.0, 1.0)),
        bit_accuracy=bit_accuracy(expected, decoded.message) if expected is not None else None,
        ber=ber(expected, decoded.message) if expected is not None else None,
        complete_recovery=(
            complete_recovery(expected, decoded.message) if expected is not None else None
        ),
        decode_ms=decode_ms,
        metadata={"decode": decoded.metadata, "device": device},
    )
