"""Check ai-spark consumer lag per topic/partition and classify stalls.

lag = Kafka end offset - committed offset of the consumer group.

A single lag sample is never a failure: the consumer flushes every ~30s so a short
backlog is normal. Samples are appended to a history file and a partition is
"unresolved" only when lag stays above zero for the whole window without draining.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from DATA_ENGINE.collect.common import KST
from DATA_ENGINE.monitor.operating_window import (
    OperatingWindow,
    parse_hhmm,
    subway_window_from_env,
)
from DATA_ENGINE.stream.consumer_status import read_status
from DATA_ENGINE.stream.kafka_consumer import DEFAULT_TOPICS, config_from_env

AI_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HISTORY_PATH = AI_ROOT / "logs" / "kafka_lag_history.json"
HISTORY_PATH_ENV = "KAFKA_LAG_HISTORY_PATH"
DEFAULT_WARN_MIN = 5.0
DEFAULT_FAIL_MIN = 15.0
SUBWAY_TOPIC = "subway.arrival"
# 샘플 간격이 성기더라도 창(window)의 이 비율 이상을 덮어야 판정한다.
COVERAGE_RATIO = 0.8

Offsets = dict[tuple[str, int], int]


@dataclass(frozen=True)
class Sample:
    ts: float
    topic: str
    partition: int
    end: int
    committed: int

    @property
    def lag(self) -> int:
        return max(0, self.end - self.committed)


@dataclass(frozen=True)
class LagResult:
    topic: str
    partition: int
    ok: bool
    level: str  # ok | warn | fail | error
    lag: int
    message: str


def fetch_offsets(bootstrap: str, group_id: str, topics: list[str]) -> tuple[Offsets, Offsets]:
    """Return (end offsets, committed offsets) keyed by (topic, partition)."""
    from kafka import KafkaAdminClient, KafkaConsumer, TopicPartition

    consumer = KafkaConsumer(bootstrap_servers=bootstrap, enable_auto_commit=False)
    admin = KafkaAdminClient(bootstrap_servers=bootstrap)
    try:
        partitions = []
        for topic in topics:
            for partition in consumer.partitions_for_topic(topic) or ():
                partitions.append(TopicPartition(topic, partition))
        end = {
            (tp.topic, tp.partition): off for tp, off in consumer.end_offsets(partitions).items()
        }
        raw = admin.list_consumer_group_offsets(group_id)
        committed = {
            (tp.topic, tp.partition): meta.offset for tp, meta in raw.items() if tp.topic in topics
        }
        return end, committed
    finally:
        consumer.close()
        admin.close()


def load_history(path: Path) -> list[Sample]:
    try:
        return [Sample(**row) for row in json.loads(path.read_text("utf-8"))]
    except (OSError, ValueError, TypeError):
        return []


def save_history(path: Path, samples: list[Sample]) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps([asdict(sample) for sample in samples]), "utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _window(series: list[Sample], now: float, window_min: float) -> list[Sample]:
    """Samples inside the window plus the newest older one as the starting anchor."""
    start = now - window_min * 60
    inside = [sample for sample in series if sample.ts >= start]
    older = [sample for sample in series if sample.ts < start]
    return [older[-1], *inside] if older else inside


def _unresolved(series: list[Sample], now: float, window_min: float) -> bool:
    """Lag stayed above zero through the window and did not drain."""
    window = _window(series, now, window_min)
    if len(window) < 2 or now - window[0].ts < window_min * 60 * COVERAGE_RATIO:
        return False
    if any(sample.lag == 0 for sample in window):
        return False
    first, last = window[0], window[-1]
    return last.committed == first.committed or last.lag >= first.lag


def _end_advanced(series: list[Sample], now: float, window_min: float) -> bool:
    window = _window(series, now, window_min)
    return len(window) >= 2 and window[-1].end > window[0].end


def _describe(topic: str, partition: int, series: list[Sample], last_saved: str | None) -> str:
    latest = series[-1]
    saved = f" last_saved_at={last_saved}" if last_saved else ""
    return (
        f"topic={topic} partition={partition} lag={latest.lag} "
        f"end={latest.end} committed={latest.committed}{saved}"
    )


def evaluate(
    history: list[Sample],
    latest: list[Sample],
    *,
    now: float,
    warn_min: float,
    fail_min: float,
    subway_window: OperatingWindow,
    last_saved: dict[str, str | None] | None = None,
) -> list[LagResult]:
    last_saved = last_saved or {}
    now_kst = datetime.fromtimestamp(now, tz=KST)
    results: list[LagResult] = []
    for sample in latest:
        series = [
            item
            for item in history
            if (item.topic, item.partition) == (sample.topic, sample.partition)
        ]
        series.append(sample)
        head = _describe(sample.topic, sample.partition, series, last_saved.get(sample.topic))

        level, cause = "ok", ""
        for name, minutes in (("fail", fail_min), ("warn", warn_min)):
            if _unresolved(series, now, minutes):
                level = name
                if _end_advanced(series, now, minutes):
                    cause = "cause=consumer_stalled(end offset 증가, committed 정지·미감소)"
                else:
                    cause = (
                        "cause=consumer_stalled(end offset도 정지 — producer 중단 가능성 함께 확인)"
                    )
                head += f" unresolved>={minutes:g}m"
                break

        if level == "ok":
            in_window = sample.topic != SUBWAY_TOPIC or subway_window.contains(now_kst)
            if in_window and len(series) >= 2 and not _end_advanced(series, now, fail_min):
                span = now - series[0].ts
                if span >= fail_min * 60 * COVERAGE_RATIO:
                    cause = "note=end offset 미증가(producer 측 가능성, freshness 검사 확인)"

        prefix = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}[level]
        results.append(
            LagResult(
                topic=sample.topic,
                partition=sample.partition,
                ok=level != "fail",
                level=level,
                lag=sample.lag,
                message=f"{prefix} consumer lag {head}" + (f" {cause}" if cause else ""),
            )
        )
    return results


def run_check(
    fetch: Callable[[], tuple[Offsets, Offsets]],
    history_path: Path,
    *,
    topics: list[str],
    warn_min: float,
    fail_min: float,
    subway_window: OperatingWindow,
    now: float | None = None,
    status_path: Path | None = None,
) -> list[LagResult]:
    now = time.time() if now is None else now
    if warn_min <= 0 or fail_min < warn_min:
        raise ValueError("require 0 < warn_min <= fail_min")

    try:
        end, committed = fetch()
    except Exception as exc:  # noqa: BLE001 - 브로커 접속 불가도 운영자가 알아야 하는 실패다.
        return [
            LagResult(
                topic=",".join(topics),
                partition=-1,
                ok=False,
                level="error",
                lag=-1,
                message=f"FAIL consumer lag unavailable: error={type(exc).__name__}: {exc}",
            )
        ]

    latest = [
        Sample(now, topic, partition, end_offset, committed.get((topic, partition), 0))
        for (topic, partition), end_offset in sorted(end.items())
    ]
    keep_after = now - (fail_min + 5) * 60
    history = [sample for sample in load_history(history_path) if sample.ts >= keep_after]

    status = read_status(status_path)
    last_saved = {
        topic: info.get("last_saved_at") for topic, info in (status or {}).get("topics", {}).items()
    }
    results = evaluate(
        history,
        latest,
        now=now,
        warn_min=warn_min,
        fail_min=fail_min,
        subway_window=subway_window,
        last_saved=last_saved,
    )
    try:
        save_history(history_path, [*history, *latest])
    except OSError:
        pass  # 이력 저장 실패가 이번 판정을 막지 않는다.

    missing = sorted(set(topics) - {sample.topic for sample in latest})
    for topic in missing:
        results.append(
            LagResult(topic, -1, False, "fail", -1, f"FAIL consumer lag topic not found: {topic}")
        )
    return results


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check ai-spark Kafka consumer lag.")
    parser.add_argument("--topics", nargs="*", default=None)
    parser.add_argument("--warn-min", type=float, default=DEFAULT_WARN_MIN)
    parser.add_argument("--fail-min", type=float, default=DEFAULT_FAIL_MIN)
    parser.add_argument("--history-path", type=Path, default=None)
    parser.add_argument("--subway-window-start", default=None)
    parser.add_argument("--subway-window-end", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv()
    default_window = subway_window_from_env()
    window = OperatingWindow(
        (
            parse_hhmm(args.subway_window_start)
            if args.subway_window_start
            else default_window.start_min
        ),
        parse_hhmm(args.subway_window_end) if args.subway_window_end else default_window.end_min,
    )
    config = config_from_env(topics=args.topics or list(DEFAULT_TOPICS))
    history_path = args.history_path or Path(
        os.environ.get(HISTORY_PATH_ENV) or DEFAULT_HISTORY_PATH
    )
    results = run_check(
        lambda: fetch_offsets(config.bootstrap_servers, config.group_id, config.topics),
        history_path,
        topics=config.topics,
        warn_min=args.warn_min,
        fail_min=args.fail_min,
        subway_window=window,
    )
    for result in results:
        print(result.message)
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
