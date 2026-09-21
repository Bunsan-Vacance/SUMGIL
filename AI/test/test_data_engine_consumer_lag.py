from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from DATA_ENGINE.monitor.check_consumer_lag import Sample, evaluate, run_check
from DATA_ENGINE.monitor.operating_window import OperatingWindow

KST = ZoneInfo("Asia/Seoul")
WINDOW = OperatingWindow.from_text("05:30", "01:00")
NOON = datetime(2026, 9, 21, 12, 0, tzinfo=KST).timestamp()
NIGHT = datetime(2026, 9, 21, 3, 0, tzinfo=KST).timestamp()
MIN = 60


def sample(ts, end, committed, topic="bike.stock", partition=0):
    return Sample(ts, topic, partition, end, committed)


def run(history, latest, now, **kwargs):
    return evaluate(
        history, [latest], now=now, warn_min=5, fail_min=15, subway_window=WINDOW, **kwargs
    )[0]


def test_zero_lag_is_ok():
    result = run([], sample(NOON, 100, 100), NOON)
    assert result.level == "ok" and result.lag == 0


def test_single_sample_with_lag_is_not_a_failure():
    result = run([], sample(NOON, 500, 100), NOON)
    assert result.level == "ok" and result.lag == 400


def test_transient_lag_that_drains_is_ok():
    # committed keeps advancing and lag shrinks over the window
    history = [
        sample(NOON - 6 * MIN, 1000, 100),
        sample(NOON - 3 * MIN, 1000, 500),
    ]
    assert run(history, sample(NOON, 1000, 900), NOON).level == "ok"


def test_lag_that_returns_to_zero_inside_window_is_ok():
    history = [
        sample(NOON - 10 * MIN, 500, 100),
        sample(NOON - 6 * MIN, 500, 500),
        sample(NOON - 3 * MIN, 600, 200),
    ]
    assert run(history, sample(NOON, 700, 300), NOON).level == "ok"


def test_warn_when_committed_frozen_for_five_minutes():
    history = [sample(NOON - m * MIN, 1000 + (6 - m) * 50, 800) for m in (6, 4, 2)]
    result = run(history, sample(NOON, 1300, 800), NOON)
    assert result.level == "warn" and result.ok
    assert result.message.startswith("WARN")
    assert "consumer_stalled" in result.message


def test_fail_when_stalled_for_fifteen_minutes():
    history = [sample(NOON - m * MIN, 1000 + (16 - m) * 10, 800) for m in range(16, 0, -3)]
    result = run(history, sample(NOON, 1160, 800), NOON)
    assert result.level == "fail" and not result.ok
    assert "end offset 증가" in result.message


def test_growing_lag_with_moving_committed_still_unresolved():
    # committed는 조금씩 움직이지만 lag이 줄지 않고 커진다 → 소비가 생산을 못 따라감
    history = [sample(NOON - m * MIN, 1000 + (16 - m) * 100, 900 + (16 - m)) for m in (16, 10, 5)]
    assert run(history, sample(NOON, 2600, 916), NOON).level == "fail"


def test_stalled_with_end_offset_also_frozen_flags_producer_possibility():
    history = [sample(NOON - m * MIN, 1000, 800) for m in (16, 10, 5)]
    result = run(history, sample(NOON, 1000, 800), NOON)
    assert result.level == "fail"
    assert "producer" in result.message


def test_insufficient_history_does_not_alert():
    history = [sample(NOON - 2 * MIN, 1000, 800)]
    assert run(history, sample(NOON, 1000, 800), NOON).level == "ok"


def test_zero_lag_with_frozen_end_offset_is_a_note_not_a_failure():
    history = [sample(NOON - m * MIN, 1000, 1000) for m in (16, 10, 5)]
    result = run(history, sample(NOON, 1000, 1000), NOON)
    assert result.ok and "producer" in result.message


def test_subway_outside_window_no_producer_note():
    history = [sample(NIGHT - m * MIN, 1000, 1000, "subway.arrival") for m in (16, 10, 5)]
    result = run(history, sample(NIGHT, 1000, 1000, "subway.arrival"), NIGHT)
    assert result.ok and "producer" not in result.message


def test_subway_inside_window_gets_producer_note():
    history = [sample(NOON - m * MIN, 1000, 1000, "subway.arrival") for m in (16, 10, 5)]
    result = run(history, sample(NOON, 1000, 1000, "subway.arrival"), NOON)
    assert "producer" in result.message


def test_message_includes_topic_partition_lag_and_last_saved():
    result = run(
        [], sample(NOON, 500, 100), NOON, last_saved={"bike.stock": "2026-09-21T11:59:30+09:00"}
    )
    for text in ("topic=bike.stock", "partition=0", "lag=400", "last_saved_at=2026-09-21T11:59"):
        assert text in result.message


def test_partitions_are_judged_independently():
    history = [sample(NOON - m * MIN, 1000, 800, partition=1) for m in (16, 10, 5)]
    healthy = sample(NOON, 500, 500, partition=0)
    stuck = sample(NOON, 1000, 800, partition=1)
    results = evaluate(
        history, [healthy, stuck], now=NOON, warn_min=5, fail_min=15, subway_window=WINDOW
    )
    assert [r.level for r in results] == ["ok", "fail"]


def fetcher(end, committed):
    return lambda: (end, committed)


def test_run_check_persists_history_and_detects_stall_across_runs(tmp_path):
    history_path = tmp_path / "lag.json"
    topics = ["bike.stock"]
    levels = []
    for minutes in (0, 5, 10, 15, 20):
        now = NOON + minutes * MIN
        results = run_check(
            fetcher({("bike.stock", 0): 1000 + minutes}, {("bike.stock", 0): 800}),
            history_path,
            topics=topics,
            warn_min=5,
            fail_min=15,
            subway_window=WINDOW,
            now=now,
            status_path=tmp_path / "none.json",
        )
        levels.append(results[0].level)
    assert levels[0] == "ok"
    assert "warn" in levels and levels[-1] == "fail"


def test_run_check_reports_missing_topic(tmp_path):
    results = run_check(
        fetcher({("bike.stock", 0): 10}, {("bike.stock", 0): 10}),
        tmp_path / "lag.json",
        topics=["bike.stock", "subway.arrival"],
        warn_min=5,
        fail_min=15,
        subway_window=WINDOW,
        now=NOON,
        status_path=tmp_path / "none.json",
    )
    assert any(not r.ok and "subway.arrival" in r.message for r in results)


def test_run_check_fails_when_kafka_unreachable(tmp_path):
    def down():
        raise ConnectionError("no broker")

    results = run_check(
        down,
        tmp_path / "lag.json",
        topics=["bike.stock"],
        warn_min=5,
        fail_min=15,
        subway_window=WINDOW,
        now=NOON,
        status_path=tmp_path / "none.json",
    )
    assert not results[0].ok and "unavailable" in results[0].message


def test_run_check_treats_missing_committed_as_zero(tmp_path):
    results = run_check(
        fetcher({("bike.stock", 0): 50}, {}),
        tmp_path / "lag.json",
        topics=["bike.stock"],
        warn_min=5,
        fail_min=15,
        subway_window=WINDOW,
        now=NOON,
        status_path=tmp_path / "none.json",
    )
    assert results[0].lag == 50


def test_run_check_rejects_bad_thresholds(tmp_path):
    with pytest.raises(ValueError):
        run_check(
            fetcher({}, {}),
            tmp_path / "lag.json",
            topics=[],
            warn_min=10,
            fail_min=5,
            subway_window=WINDOW,
        )
