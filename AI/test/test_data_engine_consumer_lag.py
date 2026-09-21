from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from DATA_ENGINE.monitor import check_consumer_lag
from DATA_ENGINE.monitor.check_consumer_lag import (
    Sample,
    evaluate,
    evaluate_consumer_status,
    run_check,
)
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


# ---- consumer 상태 파일 기반 검사 (파싱·저장 실패) ----


def iso(offset_min: float) -> str:
    return datetime.fromtimestamp(NOON + offset_min * MIN, tz=KST).isoformat()


def status_with(**topic_fields):
    return {"topics": {"bike.stock": topic_fields}}


def test_recent_parse_failure_fails_even_when_lag_is_zero():
    status = status_with(
        parse_failed=3,
        recent_parse_failures=[
            {"partition": 0, "offset": 41, "at": iso(-3)},
            {"partition": 0, "offset": 42, "at": iso(-2)},
        ],
    )

    [result] = evaluate_consumer_status(status, now=NOON)

    assert not result.ok
    for text in ("parse_failed", "topic=bike.stock", "last_offset=42", "recent=2", "total=3"):
        assert text in result.message


def test_old_parse_failure_does_not_alert_forever():
    status = status_with(
        parse_failed=1, recent_parse_failures=[{"partition": 0, "offset": 1, "at": iso(-60)}]
    )
    assert evaluate_consumer_status(status, now=NOON) == []


def test_retry_pending_save_failure_fails_until_a_save_succeeds():
    status = status_with(
        retry_pending=True, last_error="OSError: disk full", last_error_at=iso(-30)
    )

    [result] = evaluate_consumer_status(status, now=NOON)

    assert not result.ok and "save_failed" in result.message and "disk full" in result.message
    assert evaluate_consumer_status(status_with(retry_pending=False), now=NOON) == []


def test_missing_or_malformed_status_is_ignored():
    assert evaluate_consumer_status(None, now=NOON) == []
    bad = status_with(recent_parse_failures=[{"at": "not-a-date"}, {"partition": 1}])
    assert evaluate_consumer_status(bad, now=NOON) == []


def test_run_check_reports_status_failures_with_lag_and_when_kafka_is_down(tmp_path):
    status_path = tmp_path / "status.json"
    status_path.write_text(json.dumps(status_with(retry_pending=True, last_error="boom")))
    common = {
        "topics": ["bike.stock"],
        "warn_min": 5,
        "fail_min": 15,
        "subway_window": WINDOW,
        "now": NOON,
        "status_path": status_path,
    }

    healthy = run_check(
        fetcher({("bike.stock", 0): 10}, {("bike.stock", 0): 10}), tmp_path / "h.json", **common
    )
    assert any("save_failed" in r.message for r in healthy)
    assert any(r.message.startswith("OK consumer lag") for r in healthy)

    def down():
        raise ConnectionError("no broker")

    unreachable = run_check(down, tmp_path / "h2.json", **common)
    assert any("save_failed" in r.message for r in unreachable)
    assert any("unavailable" in r.message for r in unreachable)


def test_main_uses_topics_from_env_not_hardcoded_defaults(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    monkeypatch.setenv("KAFKA_TOPIC_BIKE_STOCK", "bike.stock.v2")
    monkeypatch.setenv("KAFKA_TOPIC_WEATHER_NOWCAST", "weather.v2")
    monkeypatch.setenv("KAFKA_TOPIC_SUBWAY_ARRIVAL", "subway.v2")
    monkeypatch.setenv("KAFKA_CONSUMER_STATUS_PATH", str(tmp_path / "none.json"))
    requested = []

    def fake_fetch(bootstrap, group_id, topics):
        requested.append((bootstrap, group_id, list(topics)))
        return {(t, 0): 5 for t in topics}, {(t, 0): 5 for t in topics}

    monkeypatch.setattr(check_consumer_lag, "fetch_offsets", fake_fetch)

    code = check_consumer_lag.main(["--history-path", str(tmp_path / "h.json")])

    assert code == 0
    assert requested[0][2] == ["bike.stock.v2", "weather.v2", "subway.v2"]
    assert "topic=weather.v2" in capsys.readouterr().out
