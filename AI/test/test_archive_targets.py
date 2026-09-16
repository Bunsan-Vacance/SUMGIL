import os
import time
from pathlib import Path

import pytest

from DATA_ENGINE.archive.targets import (
    ArchiveDataset,
    build_archive_datasets,
    discover_archive_targets,
    filter_datasets,
    parse_partition_dir,
)


@pytest.fixture(autouse=True)
def _stable_archive_clock(monkeypatch):
    """이 파일의 테스트 다수가 `older_than_hours=0`으로 방금 쓴 파일의 mtime과
    now_ts를 여유 없이 비교한다 — 파일시스템 mtime 해상도·clock skew로 아주
    드물게 mtime이 now_ts를 앞질러 파티션이 통째로 걸러지는 레이스가 있었다
    (test_archive_upload.py와 동일한 원인, S15P21A104-195 병합 중 발견).
    now_ts가 호출 시점마다 실제 현재 시각보다 5초 미래로 이동해 그 레이스를 없앤다.
    now_ts를 직접 넘기는 테스트(test_discover_archive_targets_respects_older_than_hours)는
    이 패치와 무관하게 그 값을 그대로 쓴다. 패치 전에 원본 time.time을 real_time으로
    캡처해둔다 — targets.py의 time과 이 파일의 time은 같은 모듈 객체라, 패치 후 lambda
    안에서 time.time()을 다시 부르면 패치된 자기 자신을 호출하는 무한 재귀가 된다."""
    real_time = time.time
    monkeypatch.setattr(
        "DATA_ENGINE.archive.targets.time.time",
        lambda: real_time() + 5,
    )


def write_snapshot(path: Path, *, size: int = 10) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_build_archive_datasets_uses_ai_data_paths(tmp_path):
    datasets = build_archive_datasets(tmp_path)

    assert datasets[0].name == "bike"
    assert datasets[0].base_path == tmp_path / "data/BIKE/raw/realtime"
    assert datasets[0].archive_prefix.as_posix() == "BIKE/raw/realtime"
    assert datasets[1].name == "weather"
    assert datasets[1].base_path == tmp_path / "data/EXTERNAL/weather/raw/nowcast"
    assert datasets[1].archive_prefix.as_posix() == "EXTERNAL/weather/raw/nowcast"
    assert datasets[2].name == "subway"
    assert datasets[2].base_path == tmp_path / "data/SUBWAY/raw/arrival"
    assert datasets[2].archive_prefix.as_posix() == "SUBWAY/raw/arrival"


def test_filter_datasets_returns_all_or_named_dataset(tmp_path):
    datasets = build_archive_datasets(tmp_path)

    assert filter_datasets(datasets, "all") == datasets
    assert [item.name for item in filter_datasets(datasets, "bike")] == ["bike"]
    assert [item.name for item in filter_datasets(datasets, "subway")] == ["subway"]


def test_filter_datasets_rejects_unknown_dataset(tmp_path):
    with pytest.raises(ValueError, match="dataset must be one of"):
        filter_datasets(build_archive_datasets(tmp_path), "crowd")


def test_parse_partition_dir_accepts_dt_hh_path():
    parsed = parse_partition_dir(Path("data/BIKE/raw/realtime/dt=2026-09-13/hh=04"))

    assert parsed == ("2026-09-13", "04")


def test_parse_partition_dir_rejects_non_partition_path():
    assert parse_partition_dir(Path("data/BIKE/raw/realtime/latest.parquet")) is None


def test_discover_archive_targets_includes_completed_snapshot_partition(tmp_path):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet", size=7)
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_2.parquet", size=9)

    targets = discover_archive_targets(
        [ArchiveDataset("bike", base_path, Path("BIKE/raw/realtime"))],
        older_than_hours=0,
        current_slot=("2026-09-13", "05"),
    )

    assert len(targets) == 1
    assert targets[0].dataset == "bike"
    assert targets[0].dt == "2026-09-13"
    assert targets[0].hh == "04"
    assert targets[0].file_count == 2
    assert targets[0].total_bytes == 16
    assert targets[0].archive_path == "BIKE/raw/realtime/dt=2026-09-13/hh=04"


def test_discover_archive_targets_excludes_current_kst_hour(tmp_path):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet")

    targets = discover_archive_targets(
        [ArchiveDataset("bike", base_path, Path("BIKE/raw/realtime"))],
        older_than_hours=0,
        current_slot=("2026-09-13", "04"),
    )

    assert targets == []


def test_discover_archive_targets_ignores_latest_and_non_snapshot_files(tmp_path):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "latest.parquet")
    write_snapshot(base_path / "dt=2026-09-13/hh=04/other.parquet")

    targets = discover_archive_targets(
        [ArchiveDataset("bike", base_path, Path("BIKE/raw/realtime"))],
        older_than_hours=0,
        current_slot=("2026-09-13", "05"),
    )

    assert targets == []


def test_discover_archive_targets_respects_older_than_hours(tmp_path):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    snapshot = write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet")
    old_ts = 1_000_000.0
    os.utime(snapshot, (old_ts, old_ts))

    targets = discover_archive_targets(
        [ArchiveDataset("bike", base_path, Path("BIKE/raw/realtime"))],
        older_than_hours=2,
        current_slot=("2026-09-13", "05"),
        now_ts=old_ts + 3600,
    )

    assert targets == []


def test_discover_archive_targets_rejects_negative_older_than_hours(tmp_path):
    with pytest.raises(ValueError, match="older_than_hours must be non-negative"):
        discover_archive_targets([], older_than_hours=-1)
