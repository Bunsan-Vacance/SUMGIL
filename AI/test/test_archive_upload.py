from pathlib import Path

import pytest

from DATA_ENGINE.archive.manifest import append_manifest_record, has_successful_archive
from DATA_ENGINE.archive.targets import ArchiveDataset
from DATA_ENGINE.archive.upload_raw_partitions import (
    build_manifest_record,
    main,
    snapshot_files,
)


def write_snapshot(path: Path, *, size: int = 10) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_snapshot_files_returns_only_snapshot_parquet(tmp_path):
    partition = tmp_path / "dt=2026-09-13/hh=04"
    first = write_snapshot(partition / "snapshot_1.parquet")
    write_snapshot(partition / "other.parquet")

    class Target:
        local_path = partition

    assert snapshot_files(Target()) == [first]


def test_build_manifest_record_uses_ai_relative_local_path(tmp_path):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet", size=7)
    target = ArchiveDataset("bike", base_path, Path("BIKE/raw/realtime"))
    discovered = __import__(
        "DATA_ENGINE.archive.targets",
        fromlist=["discover_archive_targets"],
    ).discover_archive_targets([target], older_than_hours=0, current_slot=("2026-09-13", "05"),)[0]

    record = build_manifest_record(discovered, ai_root=tmp_path, backend="drive", status="success")

    assert record.local_path == "data/BIKE/raw/realtime/dt=2026-09-13/hh=04"
    assert record.archive_backend == "drive"
    assert record.status == "success"


def test_main_dry_run_does_not_require_drive_env_or_manifest_write(tmp_path, monkeypatch, capsys):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet")
    manifest_path = tmp_path / "data/manifest/archive_uploads.jsonl"
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.delenv("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID", raising=False)

    result = main(
        [
            "--ai-root",
            str(tmp_path),
            "--dataset",
            "bike",
            "--older-than-hours",
            "0",
            "--manifest-path",
            str(manifest_path),
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "dry_run=true" in output
    assert "DRY_RUN bike" in output
    assert not manifest_path.exists()


def test_main_skips_manifest_success_partition_in_dry_run(tmp_path, capsys):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet")
    manifest_path = tmp_path / "archive_uploads.jsonl"
    target = __import__(
        "DATA_ENGINE.archive.targets",
        fromlist=["discover_archive_targets"],
    ).discover_archive_targets(
        [ArchiveDataset("bike", base_path, Path("BIKE/raw/realtime"))],
        older_than_hours=0,
        current_slot=("2026-09-13", "05"),
    )[
        0
    ]
    append_manifest_record(
        manifest_path,
        build_manifest_record(target, ai_root=tmp_path, backend="drive", status="success"),
    )

    result = main(
        [
            "--ai-root",
            str(tmp_path),
            "--dataset",
            "bike",
            "--older-than-hours",
            "0",
            "--manifest-path",
            str(manifest_path),
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "targets=0" in output
    assert "skipped_success=1" in output


def test_main_upload_records_success_manifest(tmp_path, monkeypatch):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet")
    manifest_path = tmp_path / "archive_uploads.jsonl"
    uploaded = []

    def fake_upload_targets(
        targets, *, ai_root, manifest_path, service_account_file, drive_root_folder_id, backend
    ):
        uploaded.extend(targets)
        for target in targets:
            append_manifest_record(
                manifest_path,
                build_manifest_record(target, ai_root=ai_root, backend=backend, status="success"),
            )
        return 0

    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(tmp_path / "service-account.json"))
    monkeypatch.setenv("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID", "root")
    monkeypatch.setattr(
        "DATA_ENGINE.archive.upload_raw_partitions.upload_targets", fake_upload_targets
    )

    result = main(
        [
            "--ai-root",
            str(tmp_path),
            "--dataset",
            "bike",
            "--older-than-hours",
            "0",
            "--manifest-path",
            str(manifest_path),
            "--yes",
        ]
    )

    assert result == 0
    assert len(uploaded) == 1
    assert has_successful_archive(manifest_path, "bike", "2026-09-13", "04")


def test_main_upload_returns_failure_when_upload_fails(tmp_path, monkeypatch):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet")
    manifest_path = tmp_path / "archive_uploads.jsonl"

    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(tmp_path / "service-account.json"))
    monkeypatch.setenv("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID", "root")
    monkeypatch.setattr(
        "DATA_ENGINE.archive.upload_raw_partitions.upload_targets", lambda *args, **kwargs: 1
    )

    result = main(
        [
            "--ai-root",
            str(tmp_path),
            "--dataset",
            "bike",
            "--older-than-hours",
            "0",
            "--manifest-path",
            str(manifest_path),
            "--yes",
        ]
    )

    assert result == 1


def test_main_requires_drive_env_only_for_yes(tmp_path, monkeypatch):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet")
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.setenv("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID", "root")

    with pytest.raises(RuntimeError, match="GOOGLE_SERVICE_ACCOUNT_FILE is empty"):
        main(
            [
                "--ai-root",
                str(tmp_path),
                "--dataset",
                "bike",
                "--older-than-hours",
                "0",
                "--yes",
            ]
        )
