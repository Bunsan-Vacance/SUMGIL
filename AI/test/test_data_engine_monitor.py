import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
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
from DATA_ENGINE.monitor.notify_discord import (
    DISCORD_CONTENT_LIMIT,
    build_discord_message,
    resolve_server_name,
    send_discord_notification,
    truncate_message,
)
from DATA_ENGINE.monitor.notify_discord import main as discord_main


def write_latest_with_age(path: Path, column: str, age_min: float, now_ts: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.fromtimestamp(now_ts, tz=ZoneInfo("Asia/Seoul")) - timedelta(
        minutes=age_min
    )
    pd.DataFrame({column: [timestamp.replace(tzinfo=None)]}).to_parquet(path, index=False)


def test_check_latest_file_fresh(tmp_path):
    now_ts = time.time()
    latest_path = tmp_path / "latest.parquet"
    write_latest_with_age(latest_path, "updated_at", age_min=4, now_ts=now_ts)

    result = check_latest_file(
        "bike", latest_path, max_age_min=10, timestamp_column="updated_at", now_ts=now_ts
    )

    assert result.ok is True
    assert result.status == "fresh"
    assert "OK bike latest fresh" in result.message


def test_check_latest_file_missing(tmp_path):
    result = check_latest_file(
        "bike", tmp_path / "missing.parquet", max_age_min=10, timestamp_column="updated_at"
    )

    assert result.ok is False
    assert result.status == "missing"
    assert "FAIL bike latest missing" in result.message


def test_check_latest_file_stale(tmp_path):
    now_ts = time.time()
    latest_path = tmp_path / "latest.parquet"
    write_latest_with_age(latest_path, "ingested_at", age_min=31, now_ts=now_ts)

    result = check_latest_file(
        "weather",
        latest_path,
        max_age_min=20,
        timestamp_column="ingested_at",
        now_ts=now_ts,
    )

    assert result.ok is False
    assert result.status == "stale"
    assert result.age_min == pytest.approx(31)
    assert "FAIL weather latest stale" in result.message


def test_check_latest_file_rejects_non_positive_threshold(tmp_path):
    with pytest.raises(ValueError, match="max_age_min must be positive"):
        check_latest_file(
            "bike", tmp_path / "latest.parquet", max_age_min=0, timestamp_column="updated_at"
        )


def test_check_latest_file_rejects_missing_timestamp_column(tmp_path):
    path = tmp_path / "latest.parquet"
    pd.DataFrame({"other": ["value"]}).to_parquet(path, index=False)

    result = check_latest_file("bike", path, 10, "updated_at")

    assert result.ok is False
    assert result.status == "invalid"
    assert "column=updated_at" in result.message


def test_check_latest_file_rejects_stale_rows_when_latest_is_fresh(tmp_path):
    now_ts = time.time()
    now = datetime.fromtimestamp(now_ts, tz=ZoneInfo("Asia/Seoul"))
    path = tmp_path / "latest_stock.parquet"
    pd.DataFrame(
        {
            "updated_at": [
                (now - timedelta(minutes=2)).replace(tzinfo=None),
                (now - timedelta(minutes=31)).replace(tzinfo=None),
            ]
        }
    ).to_parquet(path, index=False)

    result = check_latest_file("bike", path, 10, "updated_at", row_max_age_min=30, now_ts=now_ts)

    assert result.ok is False
    assert result.status == "stale_rows"
    assert result.stale_rows == 1
    assert "count=1" in result.message


def test_build_checks_uses_ai_root_and_distinct_thresholds(tmp_path):
    checks = build_checks(tmp_path, bike_max_age_min=10, weather_max_age_min=20)

    assert checks == [
        FreshnessCheck(
            name="bike",
            path=tmp_path / "data/BIKE/raw/realtime/latest_stock.parquet",
            max_age_min=10,
            timestamp_column="updated_at",
            row_max_age_min=30,
        ),
        FreshnessCheck(
            name="weather",
            path=tmp_path / "data/EXTERNAL/weather/raw/nowcast/latest_by_grid.parquet",
            max_age_min=20,
            timestamp_column="ingested_at",
        ),
    ]


def test_freshness_checks_kafka_latest_not_poller(tmp_path, capsys):
    now_ts = time.time()
    write_latest_with_age(
        tmp_path / "data/BIKE/raw/realtime/latest.parquet", "collected_at", 4, now_ts
    )
    write_latest_with_age(
        tmp_path / "data/EXTERNAL/weather/raw/nowcast/latest.parquet",
        "collected_at",
        4,
        now_ts,
    )

    assert main(["--ai-root", str(tmp_path), "--no-subway"]) == 1
    output = capsys.readouterr().out
    assert "latest_stock.parquet" in output
    assert "latest_by_grid.parquet" in output

    write_latest_with_age(
        tmp_path / "data/BIKE/raw/realtime/latest_stock.parquet", "updated_at", 4, now_ts
    )
    write_latest_with_age(
        tmp_path / "data/EXTERNAL/weather/raw/nowcast/latest_by_grid.parquet",
        "ingested_at",
        60,
        now_ts,
    )
    assert main(["--ai-root", str(tmp_path), "--no-subway"]) == 0


def test_freshness_rejects_stale_kafka_latest(tmp_path):
    now_ts = time.time()
    write_latest_with_age(
        tmp_path / "data/BIKE/raw/realtime/latest_stock.parquet", "updated_at", 4, now_ts
    )
    write_latest_with_age(
        tmp_path / "data/EXTERNAL/weather/raw/nowcast/latest_by_grid.parquet",
        "ingested_at",
        95,
        now_ts,
    )

    assert main(["--ai-root", str(tmp_path), "--no-subway"]) == 1


def test_check_freshness_returns_all_results(tmp_path):
    now_ts = time.time()
    fresh_path = tmp_path / "fresh.parquet"
    stale_path = tmp_path / "stale.parquet"
    write_latest_with_age(fresh_path, "observed_at", age_min=3, now_ts=now_ts)
    write_latest_with_age(stale_path, "observed_at", age_min=30, now_ts=now_ts)

    results = check_freshness(
        [
            FreshnessCheck("bike", fresh_path, 10, "observed_at"),
            FreshnessCheck("weather", stale_path, 20, "observed_at"),
        ],
        now_ts=now_ts,
    )

    assert [result.status for result in results] == ["fresh", "stale"]


def test_main_returns_zero_when_all_latest_files_are_fresh(tmp_path, capsys):
    now_ts = time.time()
    write_latest_with_age(
        tmp_path / "data/BIKE/raw/realtime/latest_stock.parquet",
        "updated_at",
        age_min=4,
        now_ts=now_ts,
    )
    write_latest_with_age(
        tmp_path / "data/EXTERNAL/weather/raw/nowcast/latest_by_grid.parquet",
        "ingested_at",
        age_min=9,
        now_ts=now_ts,
    )

    exit_code = main(["--ai-root", str(tmp_path), "--no-subway"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "OK bike latest fresh" in captured.out
    assert "OK weather latest fresh" in captured.out


def test_main_returns_one_when_any_latest_file_fails(tmp_path, capsys):
    now_ts = time.time()
    write_latest_with_age(
        tmp_path / "data/BIKE/raw/realtime/latest_stock.parquet",
        "updated_at",
        age_min=4,
        now_ts=now_ts,
    )

    exit_code = main(["--ai-root", str(tmp_path), "--no-subway"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "OK bike latest fresh" in captured.out
    assert "FAIL weather latest missing" in captured.out


def create_snapshots(base_path: Path, slot: HourSlot, count: int) -> None:
    path = partition_path(base_path, slot)
    path.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        (path / f"snapshot_20260913T01{index:02d}00.parquet").write_bytes(b"snapshot")


def create_kafka_snapshots(base_path: Path, slot: HourSlot, count: int, topic: str) -> None:
    path = partition_path(base_path, slot)
    path.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        pd.DataFrame({"kafka_topic": [topic]}).to_parquet(
            path / f"snapshot_kafka_{index:03d}.parquet", index=False
        )


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


def test_count_partition_snapshots_counts_only_matching_kafka_topic(tmp_path):
    base_path = tmp_path / "data"
    slot = HourSlot(dt="2026-09-13", hh="02")
    create_kafka_snapshots(base_path, slot, 2, "bike.stock")
    path = partition_path(base_path, slot)
    pd.DataFrame({"kafka_topic": ["weather.nowcast"]}).to_parquet(
        path / "snapshot_wrong_topic.parquet", index=False
    )
    pd.DataFrame({"stationId": ["ST-1"]}).to_parquet(path / "snapshot_poller.parquet", index=False)

    assert count_partition_snapshots(base_path, slot, "bike.stock") == 2


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
            required_topic="bike.stock",
        ),
        PartitionCheck(
            name="weather",
            base_path=tmp_path / "data/EXTERNAL/weather/raw/nowcast",
            min_count=5,
            required_topic="weather.nowcast",
        ),
    ]


def test_partition_monitor_counts_only_kafka_snapshots(tmp_path):
    slot = completed_hour_slots(1)[0]
    bike = tmp_path / "data/BIKE/raw/realtime"
    weather = tmp_path / "data/EXTERNAL/weather/raw/nowcast"
    bike_slot = partition_path(bike, slot)
    bike_slot.mkdir(parents=True)
    pd.DataFrame({"stationId": ["ST-1"]}).to_parquet(
        bike_slot / "snapshot_poller.parquet", index=False
    )
    weather_slot = partition_path(weather, slot)
    weather_slot.mkdir(parents=True)
    pd.DataFrame({"category": ["T1H"]}).to_parquet(
        weather_slot / "snapshot_poller.parquet", index=False
    )

    assert partition_main(["--ai-root", str(tmp_path), "--no-subway"]) == 1

    create_kafka_snapshots(bike, slot, 10, "bike.stock")
    create_kafka_snapshots(weather, slot, 1, "weather.nowcast")
    assert partition_main(["--ai-root", str(tmp_path), "--no-subway"]) == 0


def test_partition_main_returns_zero_when_all_partitions_meet_minimum(tmp_path, capsys):
    slot = completed_hour_slots(1)[0]
    create_kafka_snapshots(tmp_path / "data/BIKE/raw/realtime", slot, 10, "bike.stock")
    create_kafka_snapshots(
        tmp_path / "data/EXTERNAL/weather/raw/nowcast", slot, 1, "weather.nowcast"
    )

    exit_code = partition_main(["--ai-root", str(tmp_path), "--no-subway"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "OK bike partition count" in captured.out
    assert "OK weather partition count" in captured.out


def test_partition_main_returns_one_when_any_partition_fails(tmp_path, capsys):
    slot = completed_hour_slots(1)[0]
    create_kafka_snapshots(tmp_path / "data/BIKE/raw/realtime", slot, 10, "bike.stock")

    exit_code = partition_main(["--ai-root", str(tmp_path), "--no-subway"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "OK bike partition count" in captured.out
    assert "FAIL weather partition missing" in captured.out


def test_truncate_message_keeps_discord_content_under_limit():
    message = "x" * (DISCORD_CONTENT_LIMIT + 100)

    truncated = truncate_message(message)

    assert len(truncated) == DISCORD_CONTENT_LIMIT
    assert truncated.endswith("... (truncated)")


def test_build_discord_message_includes_server_status_and_detail():
    message = build_discord_message("FAIL weather latest stale", server_name="J15A104A")

    assert "[DATA_ENGINE] 수집 상태 이상 감지" in message
    assert "server=J15A104A" in message
    assert "status=FAIL" in message
    assert "FAIL weather latest stale" in message


def test_resolve_server_name_prefers_argument(monkeypatch):
    monkeypatch.setenv("DATA_ENGINE_SERVER_NAME", "env-server")

    assert resolve_server_name("arg-server") == "arg-server"


def test_resolve_server_name_uses_environment(monkeypatch):
    monkeypatch.setenv("DATA_ENGINE_SERVER_NAME", "J15A104A")

    assert resolve_server_name() == "J15A104A"


def test_send_discord_notification_skips_when_webhook_url_is_missing(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

    result = send_discord_notification("message")

    assert result.ok is True
    assert result.status == "skipped"
    assert "DISCORD_WEBHOOK_URL is empty" in result.message


def test_send_discord_notification_dry_run_does_not_post(monkeypatch):
    def fail_post(*args, **kwargs):
        raise AssertionError("requests.post should not be called")

    monkeypatch.setattr("DATA_ENGINE.monitor.notify_discord.requests.post", fail_post)

    result = send_discord_notification(
        "message",
        webhook_url="https://discord.example/webhook",
        dry_run=True,
    )

    assert result.ok is True
    assert result.status == "dry_run"
    assert "DRY_RUN discord notification skipped" in result.message


def test_send_discord_notification_posts_payload(monkeypatch):
    calls = []

    class Response:
        status_code = 204
        text = ""

    def fake_post(url, json, timeout):
        calls.append((url, json, timeout))
        return Response()

    monkeypatch.setattr("DATA_ENGINE.monitor.notify_discord.requests.post", fake_post)

    result = send_discord_notification("message", webhook_url="https://discord.example/webhook")

    assert result.ok is True
    assert result.status == "sent"
    assert calls == [("https://discord.example/webhook", {"content": "message"}, 10.0)]


def test_send_discord_notification_fails_on_http_error(monkeypatch):
    class Response:
        status_code = 400
        text = "bad request"

    monkeypatch.setattr(
        "DATA_ENGINE.monitor.notify_discord.requests.post",
        lambda *args, **kwargs: Response(),
    )

    result = send_discord_notification("message", webhook_url="https://discord.example/webhook")

    assert result.ok is False
    assert result.status == "failed"
    assert "status_code=400" in result.message


def test_send_discord_notification_fails_on_request_exception(monkeypatch):
    import requests

    def raise_timeout(*args, **kwargs):
        raise requests.Timeout("timeout")

    monkeypatch.setattr("DATA_ENGINE.monitor.notify_discord.requests.post", raise_timeout)

    result = send_discord_notification("message", webhook_url="https://discord.example/webhook")

    assert result.ok is False
    assert result.status == "failed"
    assert "timeout" in result.message


def test_discord_main_dry_run_returns_zero(capsys):
    exit_code = discord_main(
        [
            "--message",
            "FAIL bike partition missing",
            "--server-name",
            "J15A104A",
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "DRY_RUN discord notification skipped" in captured.out
