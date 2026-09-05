from __future__ import annotations

import io
import json
import os
import sys
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from watermark_lab.api import trustmark_runtime as runtime

FAKE_WORKER = r'''
import json
import os
import sys
import time

log_path, config_path = sys.argv[1:]
message = [0, 1] * 16
for line in sys.stdin:
    request = json.loads(line)
    with open(log_path, "a", encoding="utf-8") as output:
        output.write(json.dumps(request) + "\n")
    with open(config_path, encoding="utf-8") as source:
        config = json.load(source)
    operation = request["op"]
    response = {"id": request["id"], "ok": True}
    if operation == "health":
        result = {
            "ready": True, "protocol_version": 1, "model": "trustmark_q",
            "message_bits": 32, "python_version": "3.12.test", "device": "cpu",
            "worker_pid": os.getpid(),
        }
        result.update(config.get("health", {}))
    elif operation == "encode":
        message = request["bits"]
        result = {
            "image_png": request["image_png"],
            "metadata": {"strength": request["strength"], "variant": "Q"},
        }
        result.update(config.get("encode", {}))
    elif operation == "decode":
        result = {"message": message, "detected": True, "confidence": 0.75, "metadata": {}}
        result.update(config.get("decode", {}))
    elif operation == "invalid":
        response.update(ok=False, error={"code": "invalid_request", "message": "invalid bits"})
        result = {}
    elif operation == "sleep":
        time.sleep(request["seconds"])
        result = {"value": request.get("value"), "pid": os.getpid()}
    elif operation == "exit":
        os._exit(23)
    elif operation == "wrong_id":
        response["id"] = "wrong-id"
        result = {}
    elif operation == "malformed":
        print("not-json", flush=True)
        continue
    elif operation == "bad_error":
        response.update(ok=False, error=[])
        result = {}
    elif operation == "bad_result":
        result = []
    elif operation == "diagnostics":
        print("x" * 100000, file=sys.stderr, flush=True)
        result = {"value": "diagnostics drained"}
    else:
        result = {"value": request.get("value"), "pid": os.getpid()}
    if response["ok"]:
        response["result"] = result
    print(json.dumps(response), flush=True)
    if operation == "health":
        time.sleep(config.get("after_health_sleep", 0))
'''


@pytest.fixture
def make_client(tmp_path: Path):
    clients: list[runtime.TrustMarkWorkerClient] = []

    def create(config: dict[str, Any] | None = None, **options: Any):
        folder = tmp_path / str(len(clients))
        folder.mkdir()
        script = folder / "fake_worker.py"
        script.write_text(textwrap.dedent(FAKE_WORKER), encoding="utf-8")
        log = folder / "requests.jsonl"
        settings = folder / "settings.json"
        settings.write_text(json.dumps(config or {}), encoding="utf-8")
        client = runtime.TrustMarkWorkerClient(
            Path(sys.executable),
            startup_timeout=5,
            request_timeout=options.pop("request_timeout", 2),
            retry_delay=0,
            command=[sys.executable, "-u", str(script), str(log), str(settings)],
            **options,
        )
        clients.append(client)
        return client, log

    yield create
    for client in clients:
        client.close()


def _requests(log: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _image() -> np.ndarray:
    return np.random.default_rng(65).integers(0, 256, size=(128, 160, 3), dtype=np.uint8)


def _process_alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(handle)


def test_client_frames_unique_ids_and_serializes_concurrent_requests(make_client) -> None:
    client, log = make_client()
    health = client.ensure_ready()
    assert health["device"] == "cpu"
    assert client.availability() == (True, None)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(client.request, "echo", value=f"中文\n{number}") for number in range(8)
        ]
        results = [future.result() for future in futures]
    assert [result["value"] for result in results] == [f"中文\n{number}" for number in range(8)]
    assert {result["pid"] for result in results} == {health["worker_pid"]}
    requests = _requests(log)
    assert len(requests) == 9
    assert requests[0]["op"] == "health"
    assert len({request["id"] for request in requests}) == 9
    assert all(isinstance(request["id"], str) for request in requests)


@pytest.mark.parametrize(
    "health",
    [
        {"ready": False},
        {"protocol_version": 2},
        {"model": "wam"},
        {"message_bits": 64},
    ],
)
def test_client_rejects_wrong_health_and_disposes_process(make_client, health) -> None:
    client, _ = make_client({"health": health})
    with pytest.raises(RuntimeError, match="协议或模型信息不匹配"):
        client.ensure_ready()
    assert client.pid is None
    assert client.runtime_info["python_version"] is None


def test_isolated_adapter_roundtrip_uses_lossless_png_and_runtime_metadata(make_client) -> None:
    client, log = make_client()
    model = runtime.IsolatedTrustMarkModel(client, strength=0.85)
    original = _image()
    bits = np.asarray([1, 1, 0, 0] * 8, dtype=np.uint8)
    encoded = model.encode(original, bits)
    decoded = model.decode(encoded.image)
    assert np.array_equal(encoded.image, original)
    assert np.array_equal(decoded.message, bits)
    assert decoded.detected is True
    assert decoded.confidence == 0.75
    assert encoded.metadata["strength"] == 0.85
    worker_pid = client.ensure_ready()["worker_pid"]
    for metadata in (encoded.metadata, decoded.metadata):
        assert metadata["runtime"] == {
            "execution_backend": "isolated",
            "worker_pid": worker_pid,
            "python_version": "3.12.test",
            "device": "cpu",
        }
    requests = _requests(log)
    assert [request["op"] for request in requests] == ["health", "encode", "decode"]
    assert requests[1]["bits"] == bits.tolist()
    assert requests[1]["image_png"] == requests[2]["image_png"]
    assert requests[1]["strength"] == requests[2]["strength"] == 0.85


def test_invalid_request_preserves_live_worker_and_next_response(make_client) -> None:
    client, log = make_client()
    client.ensure_ready()
    pid = client.pid
    with pytest.raises(ValueError, match="invalid bits"):
        client.request("invalid")
    assert client.pid == pid
    assert client.request("echo", value="after invalid")["value"] == "after invalid"
    assert [request["op"] for request in _requests(log)] == ["health", "invalid", "echo"]


def test_timeout_kills_old_worker_and_recovers_without_stale_response(make_client) -> None:
    client, log = make_client(request_timeout=0.15)
    health = client.ensure_ready()
    old_process = client._process
    assert old_process is not None
    with pytest.raises(RuntimeError, match="响应超时"):
        client.request("sleep", seconds=1.0, value="old response")
    assert old_process.poll() is not None
    assert not _process_alive(health["worker_pid"])
    assert client.pid is None
    response = client.request("echo", value="new response")
    assert response["value"] == "new response"
    assert response["pid"] != old_process.pid
    assert [request["op"] for request in _requests(log)] == ["health", "sleep", "health", "echo"]


def test_child_exit_is_reported_and_subsequent_request_restarts(make_client) -> None:
    client, log = make_client()
    client.ensure_ready()
    old_process = client._process
    with pytest.raises(RuntimeError, match="退出"):
        client.request("exit")
    assert old_process is not None and old_process.poll() is not None
    assert client.pid is None
    assert client.request("echo", value="restarted")["value"] == "restarted"
    assert [request["op"] for request in _requests(log)] == ["health", "exit", "health", "echo"]


def test_blocked_pipe_write_times_out_and_cannot_contaminate_restarted_worker(make_client) -> None:
    client, log = make_client({"after_health_sleep": 4}, request_timeout=0.15)
    health = client.ensure_ready()
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="响应超时"):
        client.request("echo", value="x" * (4 * 1024 * 1024))
    assert time.monotonic() - started < 2.0
    assert not _process_alive(health["worker_pid"])
    log.with_name("settings.json").write_text("{}", encoding="utf-8")
    assert client.request("echo", value="recovered")["value"] == "recovered"
    assert [request["op"] for request in _requests(log)] == ["health", "health", "echo"]


def test_invalid_local_frame_does_not_recycle_healthy_worker(make_client, monkeypatch) -> None:
    client, log = make_client()
    client.ensure_ready()
    pid = client.pid
    monkeypatch.setattr(runtime, "MAX_FRAME_BYTES", 4096)
    with pytest.raises(ValueError, match="请求过大"):
        client.request("echo", value="x" * 8192)
    with pytest.raises(ValueError):
        client.request("echo", value=float("nan"))
    assert client.pid == pid
    assert client.request("echo", value="healthy")["value"] == "healthy"
    assert [request["op"] for request in _requests(log)] == ["health", "echo"]


@pytest.mark.parametrize("operation", ["wrong_id", "malformed", "bad_error", "bad_result"])
def test_invalid_protocol_is_runtime_error_and_next_request_uses_new_worker(
    make_client, operation: str
) -> None:
    client, _ = make_client()
    client.ensure_ready()
    old_process = client._process
    with pytest.raises(RuntimeError):
        client.request(operation)
    assert old_process is not None and old_process.poll() is not None
    assert client.pid is None
    assert client.request("echo", value="healthy")["value"] == "healthy"


def test_close_cleans_child_and_prevents_restart(make_client) -> None:
    client, _ = make_client()
    health = client.ensure_ready()
    process = client._process
    client.close()
    assert process is not None and process.poll() is not None
    assert not _process_alive(health["worker_pid"])
    assert all(
        stream is not None and stream.closed
        for stream in (process.stdin, process.stdout, process.stderr)
    )
    assert client.pid is None
    assert client.availability()[0] is False
    with pytest.raises(RuntimeError, match="已停止"):
        client.request("echo")
    client.close()


def test_catalog_stays_responsive_and_stderr_is_drained(make_client) -> None:
    client, log = make_client()
    client.ensure_ready()
    assert client.request("diagnostics")["value"] == "diagnostics drained"
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.request, "sleep", seconds=0.3)
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            if _requests(log)[-1]["op"] == "sleep":
                break
            time.sleep(0.005)
        assert not future.done()
        started = time.monotonic()
        assert client.availability() == (True, None)
        assert time.monotonic() - started < 0.15
        future.result()


@pytest.mark.parametrize(
    "decode_result",
    [
        {"message": [0, 1]},
        {"message": [0, 2] * 16},
        {"message": [0.0, 1.0] * 16},
        {"message": [False, True] * 16},
        {"confidence": -0.1},
        {"confidence": 1.1},
        {"detected": 1},
        {"metadata": None},
    ],
)
def test_adapter_rejects_invalid_decode_result(make_client, decode_result) -> None:
    client, _ = make_client({"decode": decode_result})
    model = runtime.IsolatedTrustMarkModel(client, strength=1.0)
    with pytest.raises(RuntimeError, match="提取结果无效"):
        model.decode(_image())


def test_adapter_rejects_malformed_embed_image_and_changed_dimensions(make_client) -> None:
    import base64

    buffer = io.BytesIO()
    Image.new("RGB", (128, 128)).save(buffer, format="PNG")
    wrong_dimensions = base64.b64encode(buffer.getvalue()).decode("ascii")
    for payload in ("not base64", wrong_dimensions):
        client, _ = make_client({"encode": {"image_png": payload}})
        with pytest.raises(RuntimeError, match="嵌入结果无效"):
            runtime.IsolatedTrustMarkModel(client, strength=1).encode(
                _image(), np.zeros(32, dtype=np.uint8)
            )


@pytest.mark.parametrize("mode", ["local", "disabled"])
def test_local_and_disabled_modes_do_not_create_worker(monkeypatch, mode: str) -> None:
    monkeypatch.setenv("WATERMARK_LAB_TRUSTMARK_MODE", mode)
    monkeypatch.setenv("WATERMARK_LAB_TRUSTMARK_PYTHON", "missing-python")
    assert runtime.create_trustmark_worker() is None


def test_auto_uses_local_import_when_no_separate_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("WATERMARK_LAB_TRUSTMARK_MODE", raising=False)
    monkeypatch.delenv("WATERMARK_LAB_TRUSTMARK_PYTHON", raising=False)
    monkeypatch.setattr(runtime, "_root", lambda: tmp_path)
    monkeypatch.setattr(runtime.importlib.util, "find_spec", lambda name: object())
    assert runtime.create_trustmark_worker() is None


@pytest.mark.parametrize("mode", ["auto", "isolated"])
def test_environment_mode_uses_explicit_interpreter(monkeypatch, tmp_path: Path, mode: str) -> None:
    executable = tmp_path / "custom-python.exe"
    monkeypatch.setenv("WATERMARK_LAB_TRUSTMARK_MODE", mode)
    monkeypatch.setenv("WATERMARK_LAB_TRUSTMARK_PYTHON", str(executable))
    monkeypatch.setattr(runtime.importlib.util, "find_spec", lambda name: object())
    paths: list[Path] = []
    monkeypatch.setattr(
        runtime, "TrustMarkWorkerClient", lambda path: paths.append(path) or "worker"
    )
    assert runtime.create_trustmark_worker() == "worker"
    assert paths == [executable.resolve()]


def test_auto_prefers_existing_separate_environment(monkeypatch, tmp_path: Path) -> None:
    executable = tmp_path / ".venv-trustmark" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setenv("WATERMARK_LAB_TRUSTMARK_MODE", "auto")
    monkeypatch.delenv("WATERMARK_LAB_TRUSTMARK_PYTHON", raising=False)
    monkeypatch.setattr(runtime, "_root", lambda: tmp_path)
    monkeypatch.setattr(runtime.importlib.util, "find_spec", lambda name: object())
    paths: list[Path] = []
    monkeypatch.setattr(
        runtime, "TrustMarkWorkerClient", lambda path: paths.append(path) or "worker"
    )
    assert runtime.create_trustmark_worker() == "worker"
    assert paths == [executable]


def test_invalid_environment_mode_has_actionable_error(monkeypatch) -> None:
    monkeypatch.setenv("WATERMARK_LAB_TRUSTMARK_MODE", "invalid")
    with pytest.raises(RuntimeError, match="auto/isolated/local/disabled"):
        runtime.create_trustmark_worker()
