"""JSONL manifest for DATA_ENGINE archive uploads."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

VALID_ARCHIVE_STATUSES = frozenset({"success", "failed"})
DEFAULT_ARCHIVE_BACKEND = "drive"
DEFAULT_MANIFEST_PATH = Path("data/manifest/archive_uploads.jsonl")


@dataclass(frozen=True)
class ArchiveManifestRecord:
    dataset: str
    dt: str
    hh: str
    local_path: str
    archive_backend: str
    archive_path: str
    file_count: int
    total_bytes: int
    status: str
    uploaded_at: str
    error: str | None = None


def validate_manifest_record(record: ArchiveManifestRecord) -> None:
    if record.status not in VALID_ARCHIVE_STATUSES:
        raise ValueError(f"status must be one of {sorted(VALID_ARCHIVE_STATUSES)}")
    if record.file_count < 0:
        raise ValueError("file_count must be non-negative")
    if record.total_bytes < 0:
        raise ValueError("total_bytes must be non-negative")


def record_from_dict(payload: dict[str, object]) -> ArchiveManifestRecord:
    required_fields = {
        "dataset",
        "dt",
        "hh",
        "local_path",
        "archive_backend",
        "archive_path",
        "file_count",
        "total_bytes",
        "status",
        "uploaded_at",
    }
    missing = required_fields - payload.keys()
    if missing:
        raise ValueError(f"manifest record missing fields: {sorted(missing)}")

    record = ArchiveManifestRecord(
        dataset=str(payload["dataset"]),
        dt=str(payload["dt"]),
        hh=str(payload["hh"]),
        local_path=str(payload["local_path"]),
        archive_backend=str(payload["archive_backend"]),
        archive_path=str(payload["archive_path"]),
        file_count=int(payload["file_count"]),
        total_bytes=int(payload["total_bytes"]),
        status=str(payload["status"]),
        uploaded_at=str(payload["uploaded_at"]),
        error=None if payload.get("error") is None else str(payload["error"]),
    )
    validate_manifest_record(record)
    return record


def append_manifest_record(manifest_path: Path, record: ArchiveManifestRecord) -> None:
    validate_manifest_record(record)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def load_manifest_records(manifest_path: Path) -> list[ArchiveManifestRecord]:
    if not manifest_path.exists():
        return []

    records: list[ArchiveManifestRecord] = []
    with manifest_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid manifest JSON at {manifest_path}:{line_number}") from exc
            if not isinstance(payload, dict):
                raise TypeError(f"manifest line must be an object at {manifest_path}:{line_number}")
            records.append(record_from_dict(payload))
    return records


def latest_partition_status(
    manifest_path: Path,
    dataset: str,
    dt: str,
    hh: str,
    *,
    backend: str = DEFAULT_ARCHIVE_BACKEND,
) -> ArchiveManifestRecord | None:
    matches = [
        record
        for record in load_manifest_records(manifest_path)
        if record.dataset == dataset
        and record.dt == dt
        and record.hh == hh
        and record.archive_backend == backend
    ]
    if not matches:
        return None
    return matches[-1]


def has_successful_archive(
    manifest_path: Path,
    dataset: str,
    dt: str,
    hh: str,
    *,
    backend: str = DEFAULT_ARCHIVE_BACKEND,
) -> bool:
    record = latest_partition_status(manifest_path, dataset, dt, hh, backend=backend)
    return record is not None and record.status == "success"
