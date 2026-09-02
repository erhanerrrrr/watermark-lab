from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGES = (
    "watermark-lab",
    "numpy",
    "Pillow",
    "PyYAML",
    "torch",
    "torchvision",
    "trustmark",
    "opencv-python",
    "scikit-learn",
    "scipy",
    "pandas",
    "PyWavelets",
)


def _version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _run(*command: str) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {
        "command": list(command),
        "exit_code": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture an auditable experiment environment")
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    torch_details: dict[str, Any] = {"available": False}
    try:
        import torch

        torch_details = {
            "available": True,
            "version": torch.__version__,
            "cuda_build": torch.version.cuda,
            "cuda_available": torch.cuda.is_available(),
            "cuda_device": (
                torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
            ),
        }
    except ImportError:
        pass

    wam_source = PROJECT_ROOT / "third_party/wam-official"
    wam_commit = _run("git", "-C", str(wam_source), "rev-parse", "HEAD")
    payload = {
        "label": args.label,
        "created_at": datetime.now().astimezone().isoformat(),
        "python": {
            "executable": sys.executable,
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "platform": platform.platform(),
        "packages": {name: _version(name) for name in PACKAGES},
        "torch": torch_details,
        "nvidia_smi": _run(
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total",
            "--format=csv,noheader",
        ),
        "git_head": _run("git", "rev-parse", "HEAD"),
        "git_status": _run("git", "status", "--short"),
        "wam": {
            "source_commit": wam_commit["stdout"] if wam_commit["exit_code"] == 0 else None,
            "checkpoint": "checkpoints/wam/wam_mit.pth",
            "checkpoint_sha256": _sha256(
                PROJECT_ROOT / "checkpoints/wam/wam_mit.pth"
            ),
        },
        "pip_freeze": _run(sys.executable, "-m", "pip", "freeze"),
    }
    destination = args.output.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"environment captured: {destination}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
