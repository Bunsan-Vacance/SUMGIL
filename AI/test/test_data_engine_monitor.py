import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from DATA_ENGINE.monitor.check_collection_freshness import (
    FreshnessCheck,
    build_checks,
    check_freshness,
    check_latest_file,
    main,
)
from DATA_ENGINE.monitor.check_partition_counts import (
    HourSlot,
    PartitionCheck,
    build_partition_checks,
    check_partition,
    check_partitions,
    completed_hour_slots,
    count_partition_snapshots,
    partition_path,
)
from DATA_ENGINE.monitor.check_partition_counts import main as partition_main


def touch_with_age(path: Path, age_min: float, now_ts: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"parquet placeholder")
    timestamp = now_ts - age_min * 60
    os.utime(path, (timestamp, timestamp))


def test_check_latest_file_fresh(tmp_path):
    now_ts = time.time()
    latest_path = tmp_path / "latest.parquet"
    touch_with_age(latest_path, age_min=4, now_ts=now_ts)

    result = check_latest_file("bike", latest_path, max_age_min=10, now_ts=now_ts)

    assert result.ok is True
    assert result.status == "fresh"
    assert "OK bike latest fresh" in result.message


def test_check_latest_file_missing(tmp_path):
    result = check_latest_file("bike", tmp_path / "missing.parquet", max_age_min=10)

    assert result.ok is False
    assert result.status == "missing"
    assert "FAIL bike latest missing" in result.message


def test_check_latest_file_stale(tmp_path):
    now_ts = time.time()
    latest_path = tmp_path / "latest.parquet"
    touch_with_age(latest_path, age_min=31, now_ts=now_ts)

    result = check_latest_file("weather", latest_path, max_age_min=20, now_ts=now_ts)

    assert result.ok is False
    assert result.status == "stale"
    assert result.age_min == pytest.approx(31)
    assert "FAIL weather latest stale" in result.message


def test_check_latest_file_rejects_non_positive_threshold(tmp_path):
    with pytest.raises(ValueError, match="max_age_min must be positive"):
        check_latest_file("bike", tmp_path / "latest.parquet", max_age_min=0)


def test_build_checks_uses_ai_root_and_distinct_thresholds(tmp_path):
    checks = build_checks(tmp_path, bike_max_age_min=10, weather_max_age_min=20)

    assert checks == [
        FreshnessCheck(
            name="bike",
            path=tmp_path / "data/BIKE/raw/realtime/latest.parquet",
            max_age_min=10,
        ),
        FreshnessCheck(
            name="weather",
            path=tmp_path / "data/EXTERNAL/weather/raw/nowcast/latest.parquet",
            max_age_min=20,
        ),
    ]


def test_check_freshness_returns_all_results(tmp_path):
    now_ts = time.time()
    fresh_path = tmp_path / "fresh.parquet"
    stale_path = tmp_path / "stale.parquet"
    touch_with_age(fresh_path, age_min=3, now_ts=now_ts)
    touch_with_age(stale_path, age_min=30, now_ts=now_ts)

    results = check_freshness(
        [
            FreshnessCheck("bike", fresh_path, 10),
            FreshnessCheck("weather", stale_path, 20),
        ],
        now_ts=now_ts,
    )

    assert [result.status for result in results] == ["fresh", "stale"]


def test_main_returns_zero_when_all_latest_files_are_fresh(tmp_path, capsys):
    now_ts = time.time()
    touch_with_age(tmp_path / "data/BIKE/raw/realtime/latest.parquet", age_min=4, now_ts=now_ts)
    touch_with_age(
        tmp_path / "data/EXTERNAL/weather/raw/nowcast/latest.parquet",
        age_min=9,
        now_ts=now_ts,
    )

    exit_code = main(["--ai-root", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "OK bike latest fresh" in captured.out
    assert "OK weather latest fresh" in captured.out


def test_main_returns_one_when_any_latest_file_fails(tmp_path, capsys):
    now_ts = time.time()
    touch_with_age(tmp_path / "data/BIKE/raw/realtime/latest.parquet", age_min=4, now_ts=now_ts)

    exit_code = main(["--ai-root", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "OK bike latest fresh" in captured.out
    assert "FAIL weather latest missing" in captured.out


def create_snapshots(base_path: Path, slot: HourSlot, count: int) -> None:
    path = partition_path(base_path, slot)
    path.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        (path / f"snapshot_20260913T01{index:02d}00.parquet").write_bytes(b"snapshot")


def test_completed_hour_slots_returns_previous_kst_hours_newest_first():
    now = datetime(2026, 9, 13, 3, 42, tzinfo=ZoneInfo("Asia/Seoul"))

    slots = completed_hour_slots(3, now=now)

    assert slots == [
        HourSlot(dt="2026-09-13", hh="02"),
        HourSlot(dt="2026-09-13", hh="01"),
        HourSlot(dt="2026-09-13", hh="00"),
    ]


def test_completed_hour_slots_excludes_current_hour_at_midnight():
    now = datetime(2026, 9, 13, 0, 5, tzinfo=ZoneInfo("Asia/Seoul"))

    slots = completed_hour_slots(1, now=now)

    assert slots == [HourSlot(dt="2026-09-12", hh="23")]


def test_completed_hour_slots_rejects_non_positive_hours():
    with pytest.raises(ValueError, match="hours must be positive"):
        completed_hour_slots(0)


def test_count_partition_snapshots_counts_only_snapshot_parquet(tmp_path):
    base_path = tmp_path / "data"
    slot = HourSlot(dt="2026-09-13", hh="02")
    path = partition_path(base_path, slot)
    path.mkdir(parents=True)
    (path / "snapshot_a.parquet").write_bytes(b"snapshot")
    (path / "snapshot_b.parquet").write_bytes(b"snapshot")
    (path / "latest.parquet").write_bytes(b"latest")
    (path / "snapshot_c.tmp").write_bytes(b"tmp")

    assert count_partition_snapshots(base_path, slot) == 2


def test_check_partition_ok_when_count_meets_minimum(tmp_path):
    base_path = tmp_path / "bike"
    slot = HourSlot(dt="2026-09-13", hh="02")
    create_snapshots(base_path, slot, count=10)

    result = check_partition(PartitionCheck("bike", base_path, min_count=10), slot)

    assert result.ok is True
    assert result.status == "ok"
    assert result.count == 10
    assert "OK bike partition count" in result.message


def test_check_partition_low_when_count_is_below_minimum(tmp_path):
    base_path = tmp_path / "bike"
    slot = HourSlot(dt="2026-09-13", hh="02")
    create_snapshots(base_path, slot, count=4)

    result = check_partition(PartitionCheck("bike", base_path, min_count=10), slot)

    assert result.ok is False
    assert result.status == "low"
    assert result.count == 4
    assert "FAIL bike partition count low" in result.message


def test_check_partition_missing_when_no_snapshots_exist(tmp_path):
    base_path = tmp_path / "weather"
    slot = HourSlot(dt="2026-09-13", hh="02")

    result = check_partition(PartitionCheck("weather", base_path, min_count=5), slot)

    assert result.ok is False
    assert result.status == "missing"
    assert result.count == 0
    assert "FAIL weather partition missing" in result.message


def test_check_partition_rejects_non_positive_min_count(tmp_path):
    with pytest.raises(ValueError, match="min_count must be positive"):
        check_partition(
            PartitionCheck("bike", tmp_path / "bike", min_count=0),
            HourSlot(dt="2026-09-13", hh="02"),
        )


def test_check_partitions_returns_dataset_and_slot_cross_product(tmp_path):
    slot_1 = HourSlot(dt="2026-09-13", hh="02")
    slot_2 = HourSlot(dt="2026-09-13", hh="01")
    bike_base = tmp_path / "bike"
    weather_base = tmp_path / "weather"
    create_snapshots(bike_base, slot_1, count=10)
    create_snapshots(bike_base, slot_2, count=10)
    create_snapshots(weather_base, slot_1, count=5)
    create_snapshots(weather_base, slot_2, count=5)

    results = check_partitions(
        [
            PartitionCheck("bike", bike_base, min_count=10),
            PartitionCheck("weather", weather_base, min_count=5),
        ],
        [slot_1, slot_2],
    )

    assert len(results) == 4
    assert all(result.ok for result in results)


def test_build_partition_checks_uses_ai_root_and_distinct_thresholds(tmp_path):
    checks = build_partition_checks(tmp_path, bike_min_count=10, weather_min_count=5)

    assert checks == [
        PartitionCheck(
            name="bike",
            base_path=tmp_path / "data/BIKE/raw/realtime",
            min_count=10,
        ),
        PartitionCheck(
            name="weather",
            base_path=tmp_path / "data/EXTERNAL/weather/raw/nowcast",
            min_count=5,
        ),
    ]


def test_partition_main_returns_zero_when_all_partitions_meet_minimum(tmp_path, capsys):
    slot = completed_hour_slots(1)[0]
    create_snapshots(tmp_path / "data/BIKE/raw/realtime", slot, count=10)
    create_snapshots(tmp_path / "data/EXTERNAL/weather/raw/nowcast", slot, count=5)

    exit_code = partition_main(["--ai-root", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "OK bike partition count" in captured.out
    assert "OK weather partition count" in captured.out


def test_partition_main_returns_one_when_any_partition_fails(tmp_path, capsys):
    slot = completed_hour_slots(1)[0]
    create_snapshots(tmp_path / "data/BIKE/raw/realtime", slot, count=10)

    exit_code = partition_main(["--ai-root", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "OK bike partition count" in captured.out
    assert "FAIL weather partition missing" in captured.out
