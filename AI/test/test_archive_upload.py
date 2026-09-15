import time
from pathlib import Path

import pytest

from DATA_ENGINE.archive.manifest import append_manifest_record, has_successful_archive
from DATA_ENGINE.archive.targets import ArchiveDataset
from DATA_ENGINE.archive.upload_raw_partitions import (
    build_manifest_record,
    drive_destination_for_target,
    main,
    snapshot_files,
)


@pytest.fixture(autouse=True)
def _stable_archive_clock(monkeypatch):
    """이 파일의 테스트는 전부 `older_than_hours=0`으로 방금 쓴 파일의 mtime과
    now_ts를 여유 없이 비교한다 — 파일시스템 mtime 해상도·clock skew로 아주
    드물게 mtime이 now_ts를 앞질러 파티션이 통째로 걸러지는 레이스가 있었다
    (S15P21A104-132 도입 당시 플레이키, S15P21A104-195 병합 중 발견).
    now_ts가 호출 시점마다 실제 현재 시각보다 5초 미래로 이동해 그 레이스를 없앤다.
    패치 전에 원본 time.time을 real_time으로 캡처해둔다 — targets.py의 time과
    이 파일의 time은 같은 모듈 객체라, 패치 후 lambda 안에서 time.time()을 다시
    부르면 패치된 자기 자신을 호출하는 무한 재귀가 된다."""
    real_time = time.time
    monkeypatch.setattr(
        "DATA_ENGINE.archive.targets.time.time",
        lambda: real_time() + 5,
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


def test_drive_destination_uses_dataset_root_and_strips_bike_prefix(tmp_path):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet", size=7)
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

    root_id, archive_path = drive_destination_for_target(
        target,
        {"default": "data-root", "bike": "bike-root"},
    )

    assert root_id == "bike-root"
    assert archive_path == "raw/realtime/dt=2026-09-13/hh=04"


def test_drive_destination_supports_bike_raw_root_level(tmp_path, monkeypatch):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet", size=7)
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
    monkeypatch.setenv("GOOGLE_DRIVE_BIKE_ARCHIVE_ROOT_LEVEL", "raw")

    root_id, archive_path = drive_destination_for_target(
        target,
        {"default": "data-root", "bike": "bike-raw-root"},
    )

    assert root_id == "bike-raw-root"
    assert archive_path == "realtime/dt=2026-09-13/hh=04"


def test_drive_destination_supports_bike_realtime_root_level(tmp_path, monkeypatch):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet", size=7)
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
    monkeypatch.setenv("GOOGLE_DRIVE_BIKE_ARCHIVE_ROOT_LEVEL", "realtime")

    root_id, archive_path = drive_destination_for_target(
        target,
        {"default": "data-root", "bike": "bike-realtime-root"},
    )

    assert root_id == "bike-realtime-root"
    assert archive_path == "dt=2026-09-13/hh=04"


def test_drive_destination_falls_back_to_default_root(tmp_path):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet", size=7)
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

    root_id, archive_path = drive_destination_for_target(target, {"default": "data-root"})

    assert root_id == "data-root"
    assert archive_path == "BIKE/raw/realtime/dt=2026-09-13/hh=04"


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
        targets,
        *,
        ai_root,
        manifest_path,
        drive_auth_mode,
        service_account_file,
        oauth_token_file,
        drive_root_folder_ids,
        backend,
    ):
        assert drive_auth_mode == "service_account"
        assert service_account_file == tmp_path / "service-account.json"
        assert oauth_token_file is None
        assert drive_root_folder_ids == {"default": "root"}
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


def test_main_supports_oauth_token_file_for_yes(tmp_path, monkeypatch):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet")
    manifest_path = tmp_path / "archive_uploads.jsonl"
    seen = {}

    def fake_upload_targets(
        targets,
        *,
        ai_root,
        manifest_path,
        drive_auth_mode,
        service_account_file,
        oauth_token_file,
        drive_root_folder_ids,
        backend,
    ):
        seen["target_count"] = len(targets)
        seen["drive_auth_mode"] = drive_auth_mode
        seen["service_account_file"] = service_account_file
        seen["oauth_token_file"] = oauth_token_file
        seen["drive_root_folder_ids"] = drive_root_folder_ids
        return 0

    monkeypatch.setenv("DATA_ENGINE_DRIVE_AUTH_MODE", "oauth")
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_FILE", str(tmp_path / "token.json"))
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
    assert seen["target_count"] == 1
    assert seen["drive_auth_mode"] == "oauth"
    assert seen["service_account_file"] is None
    assert seen["oauth_token_file"] == tmp_path / "token.json"
    assert seen["drive_root_folder_ids"] == {"default": "root"}


def test_main_passes_bike_dataset_root_folder_id(tmp_path, monkeypatch, capsys):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet")

    monkeypatch.setenv("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID", "data-root")
    monkeypatch.setenv("GOOGLE_DRIVE_BIKE_ARCHIVE_ROOT_FOLDER_ID", "bike-root")

    result = main(
        [
            "--ai-root",
            str(tmp_path),
            "--dataset",
            "bike",
            "--older-than-hours",
            "0",
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "archive=raw/realtime/dt=2026-09-13/hh=04" in output
