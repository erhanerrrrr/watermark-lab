"""Supervise the optional TrustMark interpreter without mixing model dependencies."""

from __future__ import annotations

import atexit
import base64
import importlib.util
import io
import json
import math
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from watermark_lab.core.model import WatermarkModel
from watermark_lab.core.types import BitArray, DecodeResult, EmbedResult, ImageArray

MAX_FRAME_BYTES = 112 * 1024 * 1024


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def trustmark_mode() -> str:
    mode = os.environ.get("WATERMARK_LAB_TRUSTMARK_MODE", "auto").strip().lower()
    if mode not in {"auto", "isolated", "local", "disabled"}:
        raise RuntimeError("WATERMARK_LAB_TRUSTMARK_MODE 必须为 auto/isolated/local/disabled")
    return mode


def create_trustmark_worker() -> TrustMarkWorkerClient | None:
    mode = trustmark_mode()
    if mode in {"local", "disabled"}:
        return None
    configured = os.environ.get("WATERMARK_LAB_TRUSTMARK_PYTHON")
    executable = (
        Path(configured).expanduser().resolve() if configured
        else _root() / ".venv-trustmark" / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
    )
    if mode == "auto" and not configured:
        local_available = importlib.util.find_spec("trustmark") is not None
        if local_available and (
            not executable.is_file() or executable.resolve() == Path(sys.executable).resolve()
        ):
            return None
    return TrustMarkWorkerClient(executable)


class TrustMarkWorkerClient:
    """One serialized, restartable JSON pipe per API process; no listening socket."""

    def __init__(
        self,
        executable: Path,
        *,
        startup_timeout: float = 45.0,
        request_timeout: float = 180.0,
        retry_delay: float = 5.0,
        command: list[str] | None = None,
    ) -> None:
        self.executable = executable.resolve()
        self.startup_timeout = startup_timeout
        self.request_timeout = request_timeout
        self.retry_delay = retry_delay
        self._command = command
        self._rpc_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._responses: queue.Queue[dict[str, Any] | Exception] = queue.Queue()
        self._stderr: deque[str] = deque(maxlen=12)
        self._health: dict[str, Any] | None = None
        self._last_error = "TrustMark 独立进程正在启动"
        self._failed_at = 0.0
        self._starting = False
        self._closed = False
        atexit.register(self.close)

    @property
    def pid(self) -> int | None:
        process = self._process
        return process.pid if process is not None and process.poll() is None else None

    @property
    def runtime_info(self) -> dict[str, Any]:
        with self._state_lock:
            health = dict(self._health or {})
        return {
            "execution_backend": "isolated",
            "worker_pid": health.get("worker_pid", self.pid),
            "python_version": health.get("python_version"),
            "device": health.get("device"),
        }

    def availability(self) -> tuple[bool, str | None]:
        """Catalog reads stay fast even while another request is doing inference."""
        with self._state_lock:
            if self._closed:
                return False, "TrustMark 独立进程已停止"
            if self.pid is not None and self._health is not None:
                return True, None
            if not self._starting and time.monotonic() - self._failed_at >= self.retry_delay:
                self._starting = True
                threading.Thread(target=self._recover, daemon=True).start()
            return False, self._last_error or "TrustMark 独立进程已退出，正在重新启动"

    def _recover(self) -> None:
        try:
            self.ensure_ready()
        except RuntimeError:
            pass
        finally:
            with self._state_lock:
                self._starting = False

    def _read_responses(
        self, process: subprocess.Popen[bytes], responses: queue.Queue
    ) -> None:
        try:
            assert process.stdout is not None
            reader = io.BufferedReader(process.stdout)
            while line := reader.readline(MAX_FRAME_BYTES + 1):
                if len(line) > MAX_FRAME_BYTES or not line.endswith(b"\n"):
                    raise RuntimeError("TrustMark 进程返回的数据帧无效或过大")
                response = json.loads(line.decode("utf-8"))
                if not isinstance(response, dict):
                    raise RuntimeError("TrustMark 进程返回的协议格式无效")
                responses.put(response)
            responses.put(RuntimeError("TrustMark 独立进程意外退出"))
        except (OSError, ValueError, RuntimeError) as error:
            responses.put(RuntimeError(f"TrustMark 进程通信失败：{error}"))

    def _read_stderr(self, process: subprocess.Popen[bytes]) -> None:
        try:
            assert process.stderr is not None
            while line := process.stderr.readline(8192):
                self._stderr.append(line.decode("utf-8", errors="replace").strip())
        except (OSError, ValueError):
            pass

    def _dispose(self) -> None:
        process, self._process = self._process, None
        with self._state_lock:
            self._health = None
        if process is None:
            return
        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

    def _spawn(self) -> None:
        self._dispose()
        if self._closed:
            raise RuntimeError("TrustMark 独立进程已停止")
        if not self.executable.is_file():
            raise RuntimeError(
                "未找到 TrustMark 独立环境；请运行 setup_trustmark_windows.ps1，"
                "或配置 WATERMARK_LAB_TRUSTMARK_PYTHON"
            )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, [str(_root() / "src"), environment.get("PYTHONPATH")])
        )
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONUNBUFFERED"] = "1"
        self._stderr.clear()
        responses: queue.Queue[dict[str, Any] | Exception] = queue.Queue()
        process = subprocess.Popen(
            self._command or [
                str(self.executable), "-u", "-m", "watermark_lab.api.trustmark_worker"
            ],
            cwd=_root(), env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self._process, self._responses = process, responses
        threading.Thread(
            target=self._read_responses, args=(process, responses), daemon=True
        ).start()
        threading.Thread(target=self._read_stderr, args=(process,), daemon=True).start()

    def _exchange(self, operation: str, values: dict[str, Any], timeout: float) -> dict[str, Any]:
        process, responses = self._process, self._responses
        assert process is not None and process.stdin is not None
        request_id = uuid.uuid4().hex
        frame = (json.dumps(
            {"id": request_id, "op": operation, **values}, allow_nan=False,
            ensure_ascii=False, separators=(",", ":"),
        ) + "\n").encode("utf-8")
        if len(frame) > MAX_FRAME_BYTES:
            raise ValueError("TrustMark 进程请求过大")

        def write_request() -> None:
            try:
                assert process.stdin is not None
                remaining = memoryview(frame)
                while remaining:
                    written = process.stdin.write(remaining)
                    if not written:
                        raise OSError("worker pipe closed")
                    remaining = remaining[written:]
                process.stdin.flush()
            except (OSError, ValueError) as error:
                responses.put(RuntimeError(f"TrustMark 请求发送失败：{error}"))

        # A paused or dead worker must not leave an HTTP thread blocked writing a pipe.
        threading.Thread(target=write_request, daemon=True).start()
        try:
            response = responses.get(timeout=timeout)
        except queue.Empty as error:
            raise RuntimeError(f"TrustMark 推理进程响应超时（{timeout:g} 秒），请重试") from error
        if isinstance(response, Exception):
            raise response
        if response.get("id") != request_id:
            raise RuntimeError("TrustMark 进程响应编号不匹配")
        if response.get("ok") is not True:
            failure = response.get("error", {})
            if not isinstance(failure, dict):
                raise RuntimeError("TrustMark 进程返回的错误格式无效")
            message = str(failure.get("message", "TrustMark 推理失败"))
            if failure.get("code") == "invalid_request":
                raise ValueError(message)
            raise RuntimeError(f"TrustMark 独立进程：{message}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("TrustMark 进程缺少有效结果")
        return result

    def _ensure_ready(self) -> dict[str, Any]:
        if self._closed:
            raise RuntimeError("TrustMark 独立进程已停止")
        if self.pid is not None and self._health is not None:
            return dict(self._health)
        self._spawn()
        result = self._exchange("health", {}, self.startup_timeout)
        if (
            result.get("protocol_version") != 1 or result.get("model") != "trustmark_q"
            or result.get("message_bits") != 32 or result.get("ready") is not True
        ):
            raise RuntimeError("TrustMark 进程的协议或模型信息不匹配")
        with self._state_lock:
            self._health = result
            self._last_error = ""
            self._failed_at = 0.0
        return dict(result)

    def _fail(self, error: Exception) -> None:
        self._dispose()
        with self._state_lock:
            self._last_error = str(error)
            self._failed_at = time.monotonic()

    def ensure_ready(self) -> dict[str, Any]:
        with self._rpc_lock:
            try:
                return self._ensure_ready()
            except (RuntimeError, OSError) as error:
                self._fail(error)
                raise RuntimeError(str(error)) from error

    def request(self, operation: str, **values: Any) -> dict[str, Any]:
        if not self._rpc_lock.acquire(timeout=self.request_timeout):
            raise RuntimeError("TrustMark 独立进程正忙，请稍后重试")
        try:
            self._ensure_ready()
            return self._exchange(operation, values, self.request_timeout)
        except (RuntimeError, OSError) as error:
            self._fail(error)
            raise RuntimeError(str(error)) from error
        finally:
            self._rpc_lock.release()

    def close(self) -> None:
        self._closed = True
        # Also ends any pipe write/read before waiting for its RPC lock.
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
        with self._rpc_lock:
            self._dispose()
        atexit.unregister(self.close)


def _image_base64(image: ImageArray) -> str:
    stream = io.BytesIO()
    Image.fromarray(image).save(stream, format="PNG")
    return base64.b64encode(stream.getvalue()).decode("ascii")


class IsolatedTrustMarkModel(WatermarkModel):
    name = "trustmark_q"
    message_bits = 32

    def __init__(self, client: TrustMarkWorkerClient, strength: float) -> None:
        if not math.isfinite(strength) or strength <= 0:
            raise ValueError("strength must be finite and positive")
        self.client, self.strength = client, float(strength)

    def encode(self, image: ImageArray, message: BitArray) -> EmbedResult:
        source, bits = self.validate_image(image), self.validate_message(message)
        result = self.client.request(
            "encode", image_png=_image_base64(source), bits=bits.tolist(), strength=self.strength
        )
        try:
            image_bytes = base64.b64decode(result["image_png"], validate=True)
            with Image.open(io.BytesIO(image_bytes)) as png:
                if png.size != (source.shape[1], source.shape[0]):
                    raise ValueError("encoded dimensions changed")
                encoded = np.array(png.convert("RGB"), dtype=np.uint8)
            metadata = dict(result["metadata"])
        except (KeyError, TypeError, ValueError, OSError) as error:
            raise RuntimeError("TrustMark 进程返回的嵌入结果无效") from error
        metadata["runtime"] = self.client.runtime_info
        return EmbedResult(image=encoded, metadata=metadata)

    def decode(self, image: ImageArray) -> DecodeResult:
        source = self.validate_image(image)
        result = self.client.request(
            "decode", image_png=_image_base64(source), strength=self.strength
        )
        try:
            raw_bits = result["message"]
            if not isinstance(raw_bits, list) or len(raw_bits) != 32 or any(
                type(bit) is not int or bit not in (0, 1) for bit in raw_bits
            ):
                raise ValueError("invalid payload bits")
            confidence = float(result["confidence"])
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError("invalid confidence")
            if not isinstance(result["detected"], bool):
                raise ValueError("invalid detection flag")
            metadata = dict(result["metadata"])
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("TrustMark 进程返回的提取结果无效") from error
        metadata["runtime"] = self.client.runtime_info
        return DecodeResult(
            message=np.asarray(raw_bits, dtype=np.uint8), detected=result["detected"],
            confidence=confidence, metadata=metadata,
        )
