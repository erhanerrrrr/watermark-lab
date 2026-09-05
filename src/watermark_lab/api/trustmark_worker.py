"""Private, sequential JSON-lines worker for the isolated TrustMark environment.

The parent API owns process lifetime and timeouts. This module opens no network
socket and never receives filesystem paths. Model weights are loaded lazily on
the first inference request, then reused for the lifetime of the worker.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import importlib.metadata
import io
import json
import math
import os
import platform
import sys
from collections.abc import Callable
from typing import Any, TextIO

PROTOCOL_VERSION = 1
MAX_IMAGE_PIXELS = 25_000_000
# An RGB image accepted by the API can grow when converted to lossless PNG.
MAX_PNG_BYTES = 80 * 1024 * 1024
MAX_REQUEST_CHARS = ((MAX_PNG_BYTES + 2) // 3) * 4 + 4096


class RequestError(ValueError):
    """A malformed request which must not terminate the worker."""


def _reject_json_constant(value: str) -> None:
    raise RequestError(f"Non-finite JSON number is not allowed: {value}")


def _default_model_factory(*, strength: float) -> Any:
    from watermark_lab.models.trustmark_adapter import TrustMarkQModel

    return TrustMarkQModel(strength=strength)


def probe_runtime() -> dict[str, Any]:
    """Import the real runtime without constructing a model or downloading weights."""
    import numpy as np
    import torch
    from trustmark import TrustMark

    from watermark_lab.models.trustmark_adapter import TrustMarkQModel

    if not callable(TrustMark) or TrustMarkQModel.message_bits != 32:
        raise RuntimeError("TrustMark Q runtime does not expose the required model interface")
    if int(np.__version__.split(".", maxsplit=1)[0]) >= 2:
        raise RuntimeError("TrustMark 0.9 requires NumPy < 2 in its isolated environment")
    return {
        "ready": True,
        "protocol_version": PROTOCOL_VERSION,
        "model": "trustmark_q",
        "message_bits": 32,
        "python_version": platform.python_version(),
        "executable": sys.executable,
        "worker_pid": os.getpid(),
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("trustmark", "numpy", "Pillow", "torch")
        },
    }


def image_from_png(value: Any) -> Any:
    import numpy as np
    from PIL import Image, UnidentifiedImageError

    if not isinstance(value, str) or not value:
        raise RequestError("image_png must be a nonempty base64 PNG string")
    if len(value) > ((MAX_PNG_BYTES + 2) // 3) * 4:
        raise RequestError("Encoded image exceeds the PNG transport limit")
    try:
        payload = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise RequestError("image_png is not valid base64") from error
    if len(payload) > MAX_PNG_BYTES:
        raise RequestError("Image exceeds the PNG transport limit")
    try:
        with Image.open(io.BytesIO(payload)) as source:
            if source.format != "PNG":
                raise RequestError("Worker image transport requires PNG")
            width, height = source.size
            if width < 128 or height < 128:
                raise RequestError("Image dimensions must be at least 128 x 128")
            if width * height > MAX_IMAGE_PIXELS:
                raise RequestError("Image exceeds 25 million pixels")
            return np.ascontiguousarray(np.asarray(source.convert("RGB"), dtype=np.uint8))
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise RequestError("Cannot read image_png as a valid PNG image") from error


def image_to_png(image: Any) -> str:
    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(image).save(buffer, format="PNG")
    payload = buffer.getvalue()
    if len(payload) > MAX_PNG_BYTES:
        raise RuntimeError("Encoded image exceeds the PNG transport limit")
    return base64.b64encode(payload).decode("ascii")


class TrustMarkWorker:
    def __init__(
        self,
        *,
        model_factory: Callable[..., Any] = _default_model_factory,
        health_probe: Callable[[], dict[str, Any]] = probe_runtime,
    ) -> None:
        self._model_factory = model_factory
        self._health_probe = health_probe
        self._model: Any = None

    def handle(self, request: Any) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise RequestError("Request must be a JSON object")
        request_id = request.get("id")
        if (
            isinstance(request_id, bool)
            or not isinstance(request_id, (str, int))
            or (isinstance(request_id, str) and not 0 < len(request_id) <= 128)
        ):
            raise RequestError("Request id must be an integer or a nonempty string up to 128 chars")
        operation = request.get("op")
        if operation == "health":
            return {**self._health_probe(), "model_loaded": self._model is not None}
        if operation == "shutdown":
            return {"shutdown": True}
        if not isinstance(operation, str) or operation not in {"encode", "decode"}:
            raise RequestError("Unknown operation; use health, encode, decode, or shutdown")

        strength = request.get("strength", 1.0)
        if (
            isinstance(strength, bool)
            or not isinstance(strength, (float, int))
            or not 0 < strength <= 1000
            or not math.isfinite(strength)
        ):
            raise RequestError("strength must be a finite number in (0, 1000]")
        if operation == "encode":
            bits = request.get("bits")
            if (
                not isinstance(bits, list)
                or len(bits) != 32
                or any(type(bit) is not int or bit not in (0, 1) for bit in bits)
            ):
                raise RequestError("bits must contain exactly 32 integer zeroes or ones")
        source = image_from_png(request.get("image_png"))
        if self._model is None:
            self._model = self._model_factory(strength=float(strength))
        # The adapter reads strength only when invoking backend.encode. Requests
        # are serialized, so changing it reuses the network without cache growth.
        self._model.strength = float(strength)
        if operation == "encode":
            import numpy as np

            embedded = self._model.encode(source, np.asarray(bits, dtype=np.uint8))
            return {"image_png": image_to_png(embedded.image), "metadata": embedded.metadata}
        decoded = self._model.decode(source)
        return {
            "message": decoded.message.tolist(),
            "detected": bool(decoded.detected),
            "confidence": float(decoded.confidence),
            "metadata": decoded.metadata,
        }


def _response_error(request_id: Any, code: str, message: str) -> dict[str, Any]:
    return {"id": request_id, "ok": False, "error": {"code": code, "message": message}}


def serve(
    incoming: TextIO,
    outgoing: TextIO,
    *,
    worker: TrustMarkWorker | None = None,
    diagnostics: TextIO | None = None,
    max_request_chars: int = MAX_REQUEST_CHARS,
) -> None:
    """Serve one bounded request per line; a bad request leaves subsequent ones usable."""
    handler = worker or TrustMarkWorker()
    diagnostic_stream = diagnostics if diagnostics is not None else sys.stderr
    while True:
        line = incoming.readline(max_request_chars + 1)
        if not line:
            return
        request: Any = None
        request_id: Any = None
        try:
            if len(line) > max_request_chars:
                while not line.endswith("\n"):
                    line = incoming.readline(max_request_chars + 1)
                    if not line:
                        break
                raise RequestError("Request exceeds the transport size limit")
            request = json.loads(line, parse_constant=_reject_json_constant)
            if isinstance(request, dict) and type(request.get("id")) in (str, int):
                request_id = request["id"]
                if isinstance(request_id, str) and not 0 < len(request_id) <= 128:
                    request_id = None
            with contextlib.redirect_stdout(diagnostic_stream):
                result = handler.handle(request)
            response = {"id": request_id, "ok": True, "result": result}
            # Validate serializability before writing any bytes to the protocol stream.
            encoded = json.dumps(
                response, ensure_ascii=True, allow_nan=False, separators=(",", ":")
            )
        except (RequestError, json.JSONDecodeError) as error:
            response = _response_error(request_id, "invalid_request", str(error))
            encoded = json.dumps(response, ensure_ascii=True)
        except Exception as error:
            code = (
                "runtime_unavailable"
                if isinstance(request, dict) and request.get("op") == "health"
                else "inference_error"
            )
            response = _response_error(request_id, code, f"{type(error).__name__}: {error}")
            encoded = json.dumps(response, ensure_ascii=True)
        outgoing.write(encoded + "\n")
        outgoing.flush()
        if response["ok"] and isinstance(request, dict) and request.get("op") == "shutdown":
            return


def main() -> None:
    # Keep a private protocol descriptor, then redirect fd 1 as well as Python
    # stdout. Native library output must not corrupt the JSON response stream.
    with os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", newline="\n") as protocol:
        sys.stdout.flush()
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        with contextlib.redirect_stdout(sys.stderr):
            serve(sys.stdin, protocol)


if __name__ == "__main__":
    main()
