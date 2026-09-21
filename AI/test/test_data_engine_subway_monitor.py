from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from DATA_ENGINE.monitor.check_collection_freshness import check_subway_freshness
from DATA_ENGINE.monitor.check_collection_freshness import main as freshness_main
from DATA_ENGINE.monitor.check_partition_counts import (
    HourSlot,
    PartitionCheck,
    check_partition,
    count_partition_snapshots,
    partition_path,
)
from DATA_ENGINE.monitor.check_partition_counts import main as partition_main
from DATA_ENGINE.monitor.operating_window import OperatingWindow, parse_hhmm

KST = ZoneInfo("Asia/Seoul")
WINDOW = OperatingWindow.from_text("05:30", "01:00")
TOPIC = "subway.arrival"


def write_snapshot(base: Path, poll_times: list[datetime], topic: str = TOPIC, name: str = "a"):
    """Write one snapshot file whose rows carry the given poll_run_at values."""
    first = poll_times[0]
    out = base / f"dt={first:%Y-%m-%d}" / f"hh={first:%H}"
    out.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "kafka_topic": [topic] * len(poll_times),
            "poll_run_at": poll_times,
            "ingested_at": [t + timedelta(seconds=2) for t in poll_times],
            "source_generated_at": [t - timedelta(seconds=30) for t in poll_times],
            "payload_json": ["{}"] * len(poll_times),
        }
    )
    frame.to_parquet(out / f"snapshot_{first:%Y%m%dT%H%M%S}_{name}.parquet", index=False)


def at(hour: int, minute: int = 0, day: int = 20) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=KST)


# ---- operating window ----


def test_parse_hhmm_accepts_end_of_day_and_rejects_garbage():
    assert parse_hhmm("24:00") == 1440
    with pytest.raises(ValueError):
        parse_hhmm("25:00")
    with pytest.raises(ValueError):
        parse_hhmm("0530")


def test_window_wraps_past_midnight():
    assert WINDOW.contains(at(23, 59))
    assert WINDOW.contains(at(0, 30))
    assert not WINDOW.contains(at(1, 0))
    assert not WINDOW.contains(at(3))
    assert WINDOW.contains(at(5, 30))


def test_window_covers_hour_only_when_whole_hour_is_inside():
    assert not WINDOW.covers_hour(at(5))
    assert WINDOW.covers_hour(at(6))
    assert WINDOW.covers_hour(at(0))
    assert not WINDOW.covers_hour(at(1))


def test_window_last_open_is_previous_day_before_start():
    assert WINDOW.last_open(at(3)) == at(5, 30, day=19)
    assert WINDOW.last_open(at(12)) == at(5, 30)


def test_window_rejects_empty_window():
    with pytest.raises(ValueError):
        OperatingWindow.from_text("06:00", "06:00")


# ---- partition counts ----


def test_subway_counts_distinct_poll_runs_not_files(tmp_path):
    base = tmp_path / "subway"
    slot = HourSlot("2026-09-20", "10")
    runs = [at(10, m) for m in range(20)]
    # 한 회차가 두 파일로 쪼개져도 회차 수로 센다.
    write_snapshot(base, runs[:10], name="a")
    write_snapshot(base, runs[5:], name="b")

    assert count_partition_snapshots(base, slot, TOPIC, count_poll_runs=True) == 20
    assert count_partition_snapshots(base, slot, TOPIC) == 2


def test_subway_ignores_other_topic_files(tmp_path):
    base = tmp_path / "subway"
    slot = HourSlot("2026-09-20", "10")
    write_snapshot(base, [at(10, 1), at(10, 2)], topic="bike.stock")

    assert count_partition_snapshots(base, slot, TOPIC, count_poll_runs=True) == 0


def test_subway_partition_low_and_ok(tmp_path):
    base = tmp_path / "subway"
    slot = HourSlot("2026-09-20", "10")
    check = PartitionCheck(
        "subway", base, 30, required_topic=TOPIC, count_poll_runs=True, window=WINDOW
    )
    write_snapshot(base, [at(10, m) for m in range(10)])
    assert check_partition(check, slot).status == "low"

    write_snapshot(base, [at(10, m, day=20) for m in range(10, 50)], name="b")
    assert check_partition(check, slot).ok


def test_subway_partition_outside_window_is_skipped(tmp_path):
    check = PartitionCheck(
        "subway",
        tmp_path / "subway",
        30,
        required_topic=TOPIC,
        count_poll_runs=True,
        window=WINDOW,
    )
    for hh in ("03", "05"):  # 03시는 운영 밖, 05시는 05:30 개장 전 부분 시간대
        result = check_partition(check, HourSlot("2026-09-20", hh))
        assert result.ok
        assert result.status == "outside_window"
        assert result.message.startswith("SKIP")


def test_partition_main_reports_subway_missing_inside_window(tmp_path, capsys):
    exit_code = partition_main(
        [
            "--ai-root",
            str(tmp_path),
            "--subway-window-start",
            "00:00",
            "--subway-window-end",
            "24:00",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "FAIL subway partition missing" in out


def test_partition_main_no_subway_flag_skips_subway(tmp_path, capsys):
    partition_main(["--ai-root", str(tmp_path), "--no-subway"])
    assert " subway partition" not in capsys.readouterr().out


def test_subway_partition_path_uses_dt_hh(tmp_path):
    assert partition_path(tmp_path, HourSlot("2026-09-20", "10")) == (
        tmp_path / "dt=2026-09-20" / "hh=10"
    )


# ---- freshness ----


def test_subway_freshness_ok_reports_envelope_times(tmp_path):
    now = at(12, 5)
    write_snapshot(tmp_path, [at(12, 3)])

    result = check_subway_freshness(tmp_path, 10, WINDOW, now_ts=now.timestamp())

    assert result.ok and result.status == "fresh"
    for key in ("source_generated_at", "ingested_at", "poll_run_at"):
        assert key in result.message


def test_subway_freshness_fails_when_collection_stops_inside_window(tmp_path):
    write_snapshot(tmp_path, [at(12, 0)])

    result = check_subway_freshness(tmp_path, 10, WINDOW, now_ts=at(12, 30).timestamp())

    assert not result.ok and result.status == "stale"
    assert "topic=subway.arrival" in result.message


def test_subway_freshness_never_alerts_outside_window(tmp_path):
    write_snapshot(tmp_path, [at(0, 50)])

    result = check_subway_freshness(tmp_path, 10, WINDOW, now_ts=at(3).timestamp())

    assert result.ok and result.status == "outside_window"


def test_subway_freshness_grace_right_after_opening(tmp_path):
    # 전날 마지막 수집분(00:50)만 있고 05:35 — 개장 후 5분이라 아직 정상.
    write_snapshot(tmp_path, [at(0, 50, day=20)])

    result = check_subway_freshness(tmp_path, 10, WINDOW, now_ts=at(5, 35, day=20).timestamp())
    assert result.ok

    late = check_subway_freshness(tmp_path, 10, WINDOW, now_ts=at(5, 50, day=20).timestamp())
    assert not late.ok


def test_subway_freshness_missing_inside_window(tmp_path):
    result = check_subway_freshness(tmp_path, 10, WINDOW, now_ts=at(12).timestamp())
    assert not result.ok and result.status == "missing"


def test_subway_freshness_skips_other_topic_snapshots(tmp_path):
    write_snapshot(tmp_path, [at(12, 4)], topic="bike.stock")

    result = check_subway_freshness(tmp_path, 10, WINDOW, now_ts=at(12, 5).timestamp())

    assert result.status == "missing"


def test_subway_freshness_uses_newest_snapshot(tmp_path):
    write_snapshot(tmp_path, [at(11, 0)], name="old")
    write_snapshot(tmp_path, [at(12, 4)], name="new")

    result = check_subway_freshness(tmp_path, 10, WINDOW, now_ts=at(12, 5).timestamp())

    assert result.ok


def test_subway_freshness_rejects_non_positive_threshold(tmp_path):
    with pytest.raises(ValueError):
        check_subway_freshness(tmp_path, 0, WINDOW)


def test_freshness_main_no_subway_flag(tmp_path, capsys):
    freshness_main(["--ai-root", str(tmp_path), "--no-subway"])
    assert " subway latest" not in capsys.readouterr().out
