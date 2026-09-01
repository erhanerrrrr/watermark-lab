from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from watermark_lab.core.model import WatermarkModel
from watermark_lab.core.types import BitArray, DecodeResult, EmbedResult, ImageArray

OFFICIAL_COMMIT = "2c08af04d037d5667c02f6ddebbda9ff04581c3e"
OFFICIAL_WEIGHT_SHA256 = "90ef232384e023bd63245eb0c131abd69d2afc7b8f17a71ccedceb542bf009e2"


@dataclass(frozen=True)
class WamSpatialPrediction:
    """Raw WAM detector output retained for localization and M4 soft fusion."""

    detection_probabilities: np.ndarray
    bit_logits: np.ndarray


class WamBackend(Protocol):
    device_name: str
    checkpoint_sha256: str

    def encode(
        self,
        image: ImageArray,
        message: BitArray,
        *,
        strength: float,
    ) -> ImageArray: ...

    def predict(self, image: ImageArray) -> WamSpatialPrediction: ...


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_wam_source_root() -> Path:
    override = os.environ.get("WAM_SOURCE_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return _default_project_root() / "third_party/wam-official"


def default_wam_checkpoint() -> Path:
    override = os.environ.get("WAM_CHECKPOINT")
    if override:
        return Path(override).expanduser().resolve()
    return _default_project_root() / "checkpoints/wam/wam_mit.pth"


def wam_runtime_available() -> bool:
    required = ("torch", "torchvision", "omegaconf", "einops", "cv2")
    return all(importlib.util.find_spec(name) is not None for name in required)


def wam_assets_available() -> bool:
    source_root = default_wam_source_root()
    return (
        (source_root / "watermark_anything").is_dir()
        and (source_root / "checkpoints/params.json").is_file()
        and default_wam_checkpoint().is_file()
    )


class OfficialWamBackend:
    """Thin inference-only wrapper around Meta's pinned official WAM source."""

    def __init__(
        self,
        *,
        source_root: str | Path | None = None,
        checkpoint_path: str | Path | None = None,
        params_path: str | Path | None = None,
        device: str = "auto",
    ) -> None:
        self.source_root = Path(source_root or default_wam_source_root()).resolve()
        self.checkpoint_path = Path(checkpoint_path or default_wam_checkpoint()).resolve()
        self.params_path = Path(
            params_path or self.source_root / "checkpoints/params.json"
        ).resolve()
        self._validate_files()

        try:
            import torch
            from omegaconf import OmegaConf
        except ImportError as error:
            raise RuntimeError(
                "WAM runtime is missing. Run scripts\\setup_wam_windows.ps1 first."
            ) from error

        source_text = str(self.source_root)
        if source_text not in sys.path:
            sys.path.insert(0, source_text)
        try:
            from watermark_anything.augmentation.augmenter import Augmenter
            from watermark_anything.data.transforms import (
                default_transform,
                normalize_img,
                unnormalize_img,
            )
            from watermark_anything.models import Wam, build_embedder, build_extractor
            from watermark_anything.modules.jnd import JND
        except ImportError as error:
            raise RuntimeError(
                f"failed to import official WAM source from {self.source_root}"
            ) from error

        parameters = json.loads(self.params_path.read_text(encoding="utf-8"))
        args = argparse.Namespace(**parameters)

        def config(relative_path: str):
            return OmegaConf.load(self.source_root / relative_path)

        embedder_config = config(args.embedder_config)
        extractor_config = config(args.extractor_config)
        augmenter_config = config(args.augmentation_config)
        attenuation_config = config(args.attenuation_config)

        embedder = build_embedder(
            args.embedder_model,
            embedder_config[args.embedder_model],
            args.nbits,
        )
        extractor = build_extractor(
            extractor_config.model,
            extractor_config[args.extractor_model],
            args.img_size,
            args.nbits,
        )
        augmenter = Augmenter(**augmenter_config)
        attenuation = JND(
            **attenuation_config[args.attenuation],
            preprocess=unnormalize_img,
            postprocess=normalize_img,
        )
        model = Wam(
            embedder,
            extractor,
            augmenter,
            attenuation,
            args.scaling_w,
            args.scaling_i,
            img_size_extractor=args.img_size_extractor,
        )

        selected_device = (
            "cuda" if device == "auto" and torch.cuda.is_available() else device
        )
        if selected_device == "auto":
            selected_device = "cpu"
        if selected_device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested for WAM, but PyTorch cannot access a GPU")

        checkpoint = torch.load(
            self.checkpoint_path,
            map_location="cpu",
            weights_only=True,
        )
        model.load_state_dict(checkpoint)
        self._torch = torch
        self._default_transform = default_transform
        self._unnormalize_img = unnormalize_img
        self._device = torch.device(selected_device)
        self._model = model.to(self._device).eval()
        self.device_name = str(self._device)
        self.checkpoint_sha256 = OFFICIAL_WEIGHT_SHA256
        self.model_parameters = int(sum(parameter.numel() for parameter in model.parameters()))

    def _validate_files(self) -> None:
        if not self.source_root.is_dir():
            raise RuntimeError(
                f"official WAM source not found at {self.source_root}. "
                "Run scripts\\setup_wam_windows.ps1 first."
            )
        if not self.params_path.is_file():
            raise RuntimeError(f"WAM params file not found: {self.params_path}")
        if not self.checkpoint_path.is_file():
            raise RuntimeError(
                f"official WAM checkpoint not found at {self.checkpoint_path}. "
                "Run scripts\\setup_wam_windows.ps1 first."
            )

    def _image_tensor(self, image: ImageArray):
        from PIL import Image

        pil_image = Image.fromarray(np.asarray(image, dtype=np.uint8), mode="RGB")
        return self._default_transform(pil_image).unsqueeze(0).to(self._device)

    def encode(
        self,
        image: ImageArray,
        message: BitArray,
        *,
        strength: float,
    ) -> ImageArray:
        image_tensor = self._image_tensor(image)
        message_tensor = self._torch.from_numpy(
            np.asarray(message, dtype=np.float32)[None, :]
        ).to(self._device)
        self._model.scaling_w = float(strength)
        with self._torch.inference_mode():
            watermarked = self._model.embed(image_tensor, message_tensor)["imgs_w"]
            rgb = self._unnormalize_img(watermarked).clamp(0.0, 1.0)[0]
        output = (
            rgb.permute(1, 2, 0)
            .mul(255.0)
            .round()
            .to(self._torch.uint8)
            .cpu()
            .numpy()
        )
        return np.ascontiguousarray(output)

    def predict(self, image: ImageArray) -> WamSpatialPrediction:
        image_tensor = self._image_tensor(image)
        with self._torch.inference_mode():
            prediction = self._model.detect(image_tensor)["preds"][0]
            detection = self._torch.sigmoid(prediction[0]).float().cpu().numpy()
            bit_logits = prediction[1:].float().cpu().numpy()
        return WamSpatialPrediction(
            detection_probabilities=np.ascontiguousarray(detection, dtype=np.float32),
            bit_logits=np.ascontiguousarray(bit_logits, dtype=np.float32),
        )


class WamModel(WatermarkModel):
    """Unified 32-bit adapter for the official MIT WAM checkpoint."""

    name = "wam"
    message_bits = 32

    def __init__(
        self,
        *,
        strength: float = 2.0,
        detection_threshold: float = 0.5,
        minimum_detected_fraction: float = 0.01,
        bit_logit_threshold: float = 0.5,
        source_root: str | Path | None = None,
        checkpoint_path: str | Path | None = None,
        device: str = "auto",
        backend: WamBackend | None = None,
    ) -> None:
        if strength <= 0:
            raise ValueError("strength must be positive")
        if not 0.0 < detection_threshold < 1.0:
            raise ValueError("detection_threshold must be in (0, 1)")
        if not 0.0 <= minimum_detected_fraction <= 1.0:
            raise ValueError("minimum_detected_fraction must be in [0, 1]")
        self.strength = float(strength)
        self.detection_threshold = float(detection_threshold)
        self.minimum_detected_fraction = float(minimum_detected_fraction)
        self.bit_logit_threshold = float(bit_logit_threshold)
        self._backend = backend or OfficialWamBackend(
            source_root=source_root,
            checkpoint_path=checkpoint_path,
            device=device,
        )

    def encode(self, image: ImageArray, message: BitArray) -> EmbedResult:
        source = self.validate_image(image)
        bits = self.validate_message(message)
        encoded = self._backend.encode(source, bits, strength=self.strength)
        return EmbedResult(
            image=self.validate_image(encoded),
            metadata={
                "variant": "wam_mit",
                "official_commit": OFFICIAL_COMMIT,
                "checkpoint_sha256": self._backend.checkpoint_sha256,
                "strength": self.strength,
                "device": self._backend.device_name,
                "message_bits": self.message_bits,
            },
        )

    def predict_spatial(self, image: ImageArray) -> WamSpatialPrediction:
        source = self.validate_image(image)
        prediction = self._backend.predict(source)
        detection = np.asarray(prediction.detection_probabilities, dtype=np.float32)
        bit_logits = np.asarray(prediction.bit_logits, dtype=np.float32)
        if detection.ndim != 2:
            raise ValueError(f"WAM detection map must be HxW, got {detection.shape}")
        if bit_logits.ndim != 3 or bit_logits.shape[0] != self.message_bits:
            raise ValueError(
                f"WAM bit logits must be {self.message_bits}xHxW, got {bit_logits.shape}"
            )
        if bit_logits.shape[1:] != detection.shape:
            raise ValueError("WAM detection and bit maps must share the same spatial shape")
        return WamSpatialPrediction(
            detection_probabilities=np.ascontiguousarray(detection),
            bit_logits=np.ascontiguousarray(bit_logits),
        )

    def decode(self, image: ImageArray) -> DecodeResult:
        prediction = self.predict_spatial(image)
        detection = prediction.detection_probabilities
        selected = detection > self.detection_threshold
        detected_fraction = float(np.mean(selected))
        detected = detected_fraction >= self.minimum_detected_fraction

        if np.any(selected):
            pooled_logits = np.mean(prediction.bit_logits[:, selected], axis=1)
            confidence = float(np.mean(detection[selected]))
        else:
            pooled_logits = np.full(self.message_bits, -np.inf, dtype=np.float32)
            confidence = float(np.mean(detection))
        message = (pooled_logits > self.bit_logit_threshold).astype(np.uint8)
        bit_margins = pooled_logits - self.bit_logit_threshold
        return DecodeResult(
            message=message,
            detected=detected,
            confidence=confidence,
            localization=np.ascontiguousarray(detection, dtype=np.float32),
            metadata={
                "variant": "wam_mit",
                "pooling": "official-semihard-positive-mask",
                "detection_threshold": self.detection_threshold,
                "minimum_detected_fraction": self.minimum_detected_fraction,
                "bit_logit_threshold": self.bit_logit_threshold,
                "detected_fraction": detected_fraction,
                "mean_detection_probability": float(np.mean(detection)),
                "maximum_detection_probability": float(np.max(detection)),
                "detector_height": int(detection.shape[0]),
                "detector_width": int(detection.shape[1]),
                "minimum_absolute_bit_margin": float(np.min(np.abs(bit_margins))),
                "mean_absolute_bit_margin": float(np.mean(np.abs(bit_margins))),
                "uncertain_bit_count_margin_025": int(
                    np.sum(np.abs(bit_margins) < 0.25)
                ),
            },
        )
