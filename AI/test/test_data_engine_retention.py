import os
import time
from pathlib import Path

import pytest

from DATA_ENGINE.archive.manifest import ArchiveManifestRecord, append_manifest_record
from DATA_ENGINE.monitor.cleanup_retention import (
    CleanupCandidate,
    RetentionTarget,
    build_retention_targets,
    cleanup_candidates,
    find_cleanup_candidates,
    format_bytes,
    is_safe_snapshot_path,
    main,
    parse_snapshot_partition,
    run_cleanup,
)


def touch_snapshot(path: Path, *, age_hours: float, now_ts: float, size: int = 4) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    timestamp = now_ts - age_hours * 3600
    os.utime(path, (timestamp, timestamp))


def snapshot_path(base_path: Path, dt: str = "2026-09-11", hh: str = "03") -> Path:
    return base_path / f"dt={dt}" / f"hh={hh}" / "snapshot_20260911T030000.parquet"


def append_archive_record(
    manifest_path: Path,
    *,
    dataset: str = "bike",
    dt: str = "2026-09-11",
    hh: str = "03",
    status: str = "success",
    uploaded_at: str = "2026-09-13T04:05:00+09:00",
    backend: str = "drive",
) -> None:
    append_manifest_record(
        manifest_path,
        ArchiveManifestRecord(
            dataset=dataset,
            dt=dt,
            hh=hh,
            local_path=f"data/{dataset}/raw/realtime/dt={dt}/hh={hh}",
            archive_backend=backend,
            archive_path=f"{dataset}/raw/realtime/dt={dt}/hh={hh}",
            file_count=1,
            total_bytes=4,
            status=status,
            uploaded_at=uploaded_at,
        ),
    )


def test_build_retention_targets_uses_whitelisted_raw_snapshot_bases(tmp_path):
    targets = build_retention_targets(tmp_path)

    assert targets == [
        RetentionTarget("bike", tmp_path / "data/BIKE/raw/realtime"),
        RetentionTarget("weather", tmp_path / "data/EXTERNAL/weather/raw/nowcast"),
        RetentionTarget("subway", tmp_path / "data/SUBWAY/raw/arrival"),
    ]


def test_find_cleanup_candidates_includes_only_old_snapshots(tmp_path):
    now_ts = time.time()
    bike_base = tmp_path / "data/BIKE/raw/realtime"
    old_path = snapshot_path(bike_base)
    recent_path = bike_base / "dt=2026-09-13" / "hh=03" / "snapshot_20260913T030000.parquet"
    touch_snapshot(old_path, age_hours=49, now_ts=now_ts)
    touch_snapshot(recent_path, age_hours=10, now_ts=now_ts)

    candidates, skips = find_cleanup_candidates(
        [RetentionTarget("bike", bike_base)],
        retention_hours=48,
        now_ts=now_ts,
        current_slot=("2026-09-13", "04"),
    )

    assert skips == []
    assert [candidate.path for candidate in candidates] == [old_path]
    assert candidates[0].dataset == "bike"
    assert candidates[0].dt == "2026-09-11"
    assert candidates[0].hh == "03"


def test_latest_parquet_is_not_a_cleanup_candidate(tmp_path):
    now_ts = time.time()
    bike_base = tmp_path / "data/BIKE/raw/realtime"
    latest_path = bike_base / "latest.parquet"
    touch_snapshot(latest_path, age_hours=100, now_ts=now_ts)

    candidates, skips = find_cleanup_candidates(
        [RetentionTarget("bike", bike_base)],
        retention_hours=48,
        now_ts=now_ts,
        current_slot=("2026-09-13", "04"),
    )

    assert candidates == []
    assert skips == []


def test_non_snapshot_parquet_is_not_a_cleanup_candidate(tmp_path):
    now_ts = time.time()
    bike_base = tmp_path / "data/BIKE/raw/realtime"
    other_path = bike_base / "dt=2026-09-11" / "hh=03" / "part-000.parquet"
    touch_snapshot(other_path, age_hours=100, now_ts=now_ts)

    candidates, skips = find_cleanup_candidates(
        [RetentionTarget("bike", bike_base)],
        retention_hours=48,
        now_ts=now_ts,
        current_slot=("2026-09-13", "04"),
    )

    assert candidates == []
    assert skips == []


def test_current_kst_partition_is_not_a_cleanup_candidate(tmp_path):
    now_ts = time.time()
    bike_base = tmp_path / "data/BIKE/raw/realtime"
    current_path = snapshot_path(bike_base, dt="2026-09-13", hh="04")
    touch_snapshot(current_path, age_hours=100, now_ts=now_ts)

    candidates, skips = find_cleanup_candidates(
        [RetentionTarget("bike", bike_base)],
        retention_hours=48,
        now_ts=now_ts,
        current_slot=("2026-09-13", "04"),
    )

    assert candidates == []
    assert skips == []


def test_safe_snapshot_path_rejects_files_outside_whitelist(tmp_path):
    target = RetentionTarget("bike", tmp_path / "data/BIKE/raw/realtime")
    outside = tmp_path / "data/BIKE/processed/dt=2026-09-11/hh=03/snapshot_a.parquet"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"x")

    assert is_safe_snapshot_path(target, outside, current_slot=("2026-09-13", "04")) is False


def test_safe_snapshot_path_requires_dt_hh_layout(tmp_path):
    target = RetentionTarget("bike", tmp_path / "data/BIKE/raw/realtime")
    wrong_layout = target.base_path / "dt=2026-09-11" / "snapshot_a.parquet"
    wrong_layout.parent.mkdir(parents=True)
    wrong_layout.write_bytes(b"x")

    assert is_safe_snapshot_path(target, wrong_layout, current_slot=("2026-09-13", "04")) is False


def test_parse_snapshot_partition_extracts_dt_hh(tmp_path):
    target = RetentionTarget("bike", tmp_path / "data/BIKE/raw/realtime")
    path = snapshot_path(target.base_path, dt="2026-09-11", hh="03")

    assert parse_snapshot_partition(target, path) == ("2026-09-11", "03")


def test_parse_snapshot_partition_rejects_outside_path(tmp_path):
    target = RetentionTarget("bike", tmp_path / "data/BIKE/raw/realtime")
    outside = tmp_path / "data/BIKE/processed/dt=2026-09-11/hh=03/snapshot_a.parquet"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"x")

    assert parse_snapshot_partition(target, outside) is None


def test_cleanup_candidates_dry_run_keeps_files(tmp_path):
    path = tmp_path / "snapshot.parquet"
    path.write_bytes(b"abcd")
    candidate = CleanupCandidate(
        dataset="bike",
        dt="2026-09-11",
        hh="03",
        path=path,
        size_bytes=4,
        age_hours=49,
    )

    deleted_count, deleted_bytes = cleanup_candidates([candidate], yes=False)

    assert deleted_count == 0
    assert deleted_bytes == 0
    assert path.exists()


def test_cleanup_candidates_yes_deletes_only_candidates(tmp_path):
    candidate_path = tmp_path / "snapshot.parquet"
    keep_path = tmp_path / "keep.parquet"
    candidate_path.write_bytes(b"abcd")
    keep_path.write_bytes(b"keep")
    candidate = CleanupCandidate(
        dataset="bike",
        dt="2026-09-11",
        hh="03",
        path=candidate_path,
        size_bytes=4,
        age_hours=49,
    )

    deleted_count, deleted_bytes = cleanup_candidates([candidate], yes=True)

    assert deleted_count == 1
    assert deleted_bytes == 4
    assert not candidate_path.exists()
    assert keep_path.exists()


def test_run_cleanup_reports_candidates_and_deleted_bytes(tmp_path):
    now_ts = time.time()
    bike_base = tmp_path / "data/BIKE/raw/realtime"
    old_path = snapshot_path(bike_base)
    touch_snapshot(old_path, age_hours=49, now_ts=now_ts, size=7)

    result = run_cleanup(
        [RetentionTarget("bike", bike_base)],
        retention_hours=48,
        yes=True,
        now_ts=now_ts,
        current_slot=("2026-09-13", "04"),
    )

    assert result.dry_run is False
    assert len(result.candidates) == 1
    assert result.candidate_bytes == 7
    assert result.deleted_count == 1
    assert result.deleted_bytes == 7
    assert not old_path.exists()


def test_find_cleanup_candidates_requires_manifest_path_when_archive_success_required(tmp_path):
    with pytest.raises(ValueError, match="manifest_path is required"):
        find_cleanup_candidates(
            [RetentionTarget("bike", tmp_path)],
            retention_hours=48,
            require_archive_success=True,
            current_slot=("2026-09-13", "04"),
        )


def test_find_cleanup_candidates_includes_archived_success_partition(tmp_path):
    now_ts = time.time()
    bike_base = tmp_path / "data/BIKE/raw/realtime"
    old_path = snapshot_path(bike_base)
    manifest_path = tmp_path / "data/manifest/archive_uploads.jsonl"
    touch_snapshot(old_path, age_hours=49, now_ts=now_ts)
    append_archive_record(manifest_path)

    candidates, skips = find_cleanup_candidates(
        [RetentionTarget("bike", bike_base)],
        retention_hours=48,
        require_archive_success=True,
        manifest_path=manifest_path,
        now_ts=now_ts,
        current_slot=("2026-09-13", "04"),
    )

    assert [candidate.path for candidate in candidates] == [old_path]
    assert skips == []


def test_find_cleanup_candidates_skips_partition_without_manifest_success(tmp_path):
    now_ts = time.time()
    bike_base = tmp_path / "data/BIKE/raw/realtime"
    old_path = snapshot_path(bike_base)
    manifest_path = tmp_path / "data/manifest/archive_uploads.jsonl"
    touch_snapshot(old_path, age_hours=49, now_ts=now_ts)

    candidates, skips = find_cleanup_candidates(
        [RetentionTarget("bike", bike_base)],
        retention_hours=48,
        require_archive_success=True,
        manifest_path=manifest_path,
        now_ts=now_ts,
        current_slot=("2026-09-13", "04"),
    )

    assert candidates == []
    assert len(skips) == 1
    assert skips[0].path == old_path
    assert skips[0].reason == "archive_not_success"


def test_find_cleanup_candidates_skips_partition_when_latest_manifest_failed(tmp_path):
    now_ts = time.time()
    bike_base = tmp_path / "data/BIKE/raw/realtime"
    old_path = snapshot_path(bike_base)
    manifest_path = tmp_path / "data/manifest/archive_uploads.jsonl"
    touch_snapshot(old_path, age_hours=49, now_ts=now_ts)
    append_archive_record(manifest_path, status="success")
    append_archive_record(
        manifest_path,
        status="failed",
        uploaded_at="2026-09-13T04:10:00+09:00",
    )

    candidates, skips = find_cleanup_candidates(
        [RetentionTarget("bike", bike_base)],
        retention_hours=48,
        require_archive_success=True,
        manifest_path=manifest_path,
        now_ts=now_ts,
        current_slot=("2026-09-13", "04"),
    )

    assert candidates == []
    assert len(skips) == 1
    assert skips[0].reason == "archive_not_success"


def test_find_cleanup_candidates_includes_partition_when_latest_manifest_success(tmp_path):
    now_ts = time.time()
    bike_base = tmp_path / "data/BIKE/raw/realtime"
    old_path = snapshot_path(bike_base)
    manifest_path = tmp_path / "data/manifest/archive_uploads.jsonl"
    touch_snapshot(old_path, age_hours=49, now_ts=now_ts)
    append_archive_record(manifest_path, status="failed")
    append_archive_record(
        manifest_path,
        status="success",
        uploaded_at="2026-09-13T04:10:00+09:00",
    )

    candidates, skips = find_cleanup_candidates(
        [RetentionTarget("bike", bike_base)],
        retention_hours=48,
        require_archive_success=True,
        manifest_path=manifest_path,
        now_ts=now_ts,
        current_slot=("2026-09-13", "04"),
    )

    assert [candidate.path for candidate in candidates] == [old_path]
    assert skips == []


def test_find_cleanup_candidates_ignores_other_manifest_partition(tmp_path):
    now_ts = time.time()
    bike_base = tmp_path / "data/BIKE/raw/realtime"
    old_path = snapshot_path(bike_base)
    manifest_path = tmp_path / "data/manifest/archive_uploads.jsonl"
    touch_snapshot(old_path, age_hours=49, now_ts=now_ts)
    append_archive_record(manifest_path, dataset="weather")

    candidates, skips = find_cleanup_candidates(
        [RetentionTarget("bike", bike_base)],
        retention_hours=48,
        require_archive_success=True,
        manifest_path=manifest_path,
        now_ts=now_ts,
        current_slot=("2026-09-13", "04"),
    )

    assert candidates == []
    assert len(skips) == 1


def test_find_cleanup_candidates_rejects_non_positive_retention_hours(tmp_path):
    with pytest.raises(ValueError, match="retention_hours must be positive"):
        find_cleanup_candidates(
            [RetentionTarget("bike", tmp_path)],
            retention_hours=0,
            current_slot=("2026-09-13", "04"),
        )


def test_format_bytes_uses_readable_units():
    assert format_bytes(999) == "999B"
    assert format_bytes(1024) == "1.0KB"
    assert format_bytes(1024 * 1024) == "1.0MB"


def test_main_dry_run_outputs_summary_and_keeps_candidate(tmp_path, capsys):
    now_ts = time.time()
    bike_base = tmp_path / "data/BIKE/raw/realtime"
    old_path = snapshot_path(bike_base)
    touch_snapshot(old_path, age_hours=49, now_ts=now_ts)

    exit_code = main(["--ai-root", str(tmp_path), "--retention-hours", "48"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "dry_run=true" in captured.out
    assert "candidates=1" in captured.out
    assert "DRY_RUN bike" in captured.out
    assert old_path.exists()


def test_main_require_archive_success_outputs_skips(tmp_path, capsys):
    now_ts = time.time()
    bike_base = tmp_path / "data/BIKE/raw/realtime"
    old_path = snapshot_path(bike_base)
    touch_snapshot(old_path, age_hours=49, now_ts=now_ts)

    exit_code = main(
        [
            "--ai-root",
            str(tmp_path),
            "--retention-hours",
            "48",
            "--require-archive-success",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "require_archive_success=true" in captured.out
    assert "candidates=0" in captured.out
    assert "skipped=1" in captured.out
    assert "SKIP bike dt=2026-09-11 hh=03 reason=archive_not_success" in captured.out
    assert old_path.exists()
