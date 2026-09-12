import os
import time
from pathlib import Path

import pytest

from DATA_ENGINE.monitor.check_collection_freshness import (
    FreshnessCheck,
    build_checks,
    check_freshness,
    check_latest_file,
    main,
)


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
