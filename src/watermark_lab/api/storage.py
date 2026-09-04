from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

from PIL import Image

from watermark_lab.core.types import ImageArray

_SAFE_ID = re.compile(r"^[A-Z0-9-]{8,64}$")
ARTIFACT_KINDS = ("original", "embedded", "attacked")


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_storage_dir() -> Path:
    configured = os.environ.get("WATERMARK_LAB_STORAGE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return project_root() / "artifacts" / "web"


def image_to_png(image: ImageArray) -> bytes:
    stream = io.BytesIO()
    Image.fromarray(image).save(stream, format="PNG")
    return stream.getvalue()


class ExperimentStore:
    """Small local SQLite store plus PNG artifacts for the single-machine showcase."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_storage_dir()).resolve()
        self.database_path = self.root / "watermark_lab.sqlite3"
        self.experiments_dir = self.root / "experiments"
        self.operations_dir = self.root / "operations"
        self._write_lock = threading.Lock()
        self.root.mkdir(parents=True, exist_ok=True)
        self.experiments_dir.mkdir(parents=True, exist_ok=True)
        self.operations_dir.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    image_name TEXT NOT NULL,
                    model TEXT NOT NULL,
                    attack TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_experiments_created_at "
                "ON experiments(created_at DESC)"
            )

    def save_experiment(self, payload: dict[str, Any], images: dict[str, ImageArray]) -> None:
        experiment_id = str(payload["id"])
        self._validate_id(experiment_id)
        missing = set(ARTIFACT_KINDS) - set(images)
        if missing:
            raise ValueError(f"missing experiment artifacts: {', '.join(sorted(missing))}")

        destination = self.experiments_dir / experiment_id
        destination.mkdir(parents=True, exist_ok=False)
        for kind in ARTIFACT_KINDS:
            target = destination / f"{kind}.png"
            temporary = destination / f".{kind}.tmp"
            temporary.write_bytes(image_to_png(images[kind]))
            temporary.replace(target)

        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO experiments(id, created_at, image_name, model, attack, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    payload["created_at"],
                    payload["image_name"],
                    payload["model"],
                    payload["attack"],
                    serialized,
                ),
            )

    def list_experiments(
        self, *, limit: int = 100, model: str | None = None
    ) -> list[dict[str, Any]]:
        query = "SELECT payload_json FROM experiments"
        parameters: list[Any] = []
        if model:
            query += " WHERE model = ?"
            parameters.append(model)
        query += " ORDER BY created_at DESC LIMIT ?"
        parameters.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def get_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        self._validate_id(experiment_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM experiments WHERE id = ?", (experiment_id,)
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM experiments").fetchone()
        return int(row["count"])

    def artifact_path(self, experiment_id: str, kind: str) -> Path | None:
        self._validate_id(experiment_id)
        if kind not in ARTIFACT_KINDS:
            return None
        if self.get_experiment(experiment_id) is None:
            return None
        candidate = (self.experiments_dir / experiment_id / f"{kind}.png").resolve()
        if self.experiments_dir not in candidate.parents or not candidate.is_file():
            return None
        return candidate

    def save_operation_image(self, operation_id: str, kind: str, image: ImageArray) -> Path:
        self._validate_id(operation_id)
        if kind not in {"embedded"}:
            raise ValueError("unsupported operation artifact")
        destination = self.operations_dir / operation_id
        destination.mkdir(parents=True, exist_ok=False)
        path = destination / f"{kind}.png"
        path.write_bytes(image_to_png(image))
        return path

    def operation_artifact_path(self, operation_id: str, kind: str) -> Path | None:
        self._validate_id(operation_id)
        if kind != "embedded":
            return None
        candidate = (self.operations_dir / operation_id / f"{kind}.png").resolve()
        if self.operations_dir not in candidate.parents or not candidate.is_file():
            return None
        return candidate

    def export_csv(self) -> str:
        rows = self.list_experiments(limit=100_000)
        stream = io.StringIO(newline="")
        fields = [
            "id",
            "created_at",
            "image_name",
            "model",
            "attack",
            "detected",
            "detection_confidence",
            "bit_accuracy",
            "ber",
            "complete_recovery",
            "embed_psnr_db",
            "embed_ssim",
            "post_attack_psnr_db",
            "post_attack_ssim",
            "encode_ms",
            "decode_ms",
            "expected_message",
            "decoded_message",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            safe_row = {
                key: (
                    f"'{value}"
                    if isinstance(value, str) and value.startswith(("=", "+", "-", "@"))
                    else value
                )
                for key, value in row.items()
            }
            writer.writerow(safe_row)
        return "\ufeff" + stream.getvalue()

    @staticmethod
    def _validate_id(value: str) -> None:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("invalid artifact identifier")
