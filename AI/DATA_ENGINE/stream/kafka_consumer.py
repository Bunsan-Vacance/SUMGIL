"""Kafka consumer runner for DATA_ENGINE raw parquet snapshots.

This module is safe to import without Kafka dependencies. The actual
``kafka-python`` import happens only when the runner starts, so parser/sink
tests can run before BE/Infra provides a reachable Kafka broker.
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from dotenv import load_dotenv

from DATA_ENGINE.collect.common import env
from DATA_ENGINE.stream.consumer_status import ConsumerStatus
from DATA_ENGINE.stream.kafka_events import KafkaEvent, parse_kafka_event
from DATA_ENGINE.stream.kafka_sink import write_events

logger = logging.getLogger("kafka_consumer")

DEFAULT_TOPICS = ("bike.stock", "weather.nowcast", "subway.arrival")


@dataclass(frozen=True)
class KafkaConsumerConfig:
    bootstrap_servers: str
    group_id: str
    auto_offset_reset: str
    topics: list[str]


def _topics_from_env() -> list[str]:
    return [
        os.environ.get("KAFKA_TOPIC_BIKE_STOCK", "bike.stock"),
        os.environ.get("KAFKA_TOPIC_WEATHER_NOWCAST", "weather.nowcast"),
        os.environ.get("KAFKA_TOPIC_SUBWAY_ARRIVAL", "subway.arrival"),
    ]


def config_from_env(*, topics: list[str] | None = None) -> KafkaConsumerConfig:
    load_dotenv()
    return KafkaConsumerConfig(
        bootstrap_servers=env("KAFKA_BOOTSTRAP_SERVERS"),
        group_id=os.environ.get("KAFKA_CONSUMER_GROUP", "ai-spark"),
        auto_offset_reset=os.environ.get("KAFKA_AUTO_OFFSET_RESET", "earliest"),
        topics=topics or _topics_from_env(),
    )


def parse_messages_with_failures(
    messages: Iterable[object],
) -> tuple[list[KafkaEvent], list[object]]:
    """Parse messages; failed ones are logged with topic/partition/offset and returned."""
    events: list[KafkaEvent] = []
    failed: list[object] = []
    for msg in messages:
        try:
            events.append(
                parse_kafka_event(
                    msg.value,
                    topic=getattr(msg, "topic", None),
                    partition=getattr(msg, "partition", None),
                    offset=getattr(msg, "offset", None),
                )
            )
        except Exception:
            failed.append(msg)
            logger.exception(
                "Kafka message parse failed (skipped): topic=%s partition=%s offset=%s",
                getattr(msg, "topic", None),
                getattr(msg, "partition", None),
                getattr(msg, "offset", None),
            )
    return events, failed


def parse_messages(messages: Iterable[object]) -> list[KafkaEvent]:
    return parse_messages_with_failures(messages)[0]


def next_offsets(messages: Iterable[object]) -> dict[tuple[str, int], int]:
    """(topic, partition) -> offset that will be committed after these messages."""
    offsets: dict[tuple[str, int], int] = {}
    for msg in messages:
        key = (getattr(msg, "topic", None) or "unknown", getattr(msg, "partition", None) or 0)
        offsets[key] = max(offsets.get(key, 0), (getattr(msg, "offset", None) or 0) + 1)
    return offsets


def process_batch(
    messages: list[object],
    *,
    commit: Callable[[], None],
    status: ConsumerStatus,
    write: Callable[[list[KafkaEvent]], list] = write_events,
) -> list:
    """Parse, save and commit one buffered batch, recording per-topic status.

    Unparseable messages are skipped (they can never succeed on retry) but are recorded
    with topic/partition/offset, and the rest of the batch is still saved. If saving
    fails nothing is committed, so the batch is re-read after the consumer restarts.
    """
    events, failed = parse_messages_with_failures(messages)
    for msg in failed:
        status.record_parse_failure(
            getattr(msg, "topic", None),
            getattr(msg, "partition", None),
            getattr(msg, "offset", None),
        )

    paths: list = []
    if events:
        try:
            paths = write(events)
        except Exception as exc:
            topics = sorted({event.kafka_topic or event.source for event in events})
            status.record_save_failure(topics, exc)
            status.write()
            logger.exception(
                "Kafka events save failed, not committed (will replay after restart): "
                "topics=%s events=%d",
                ",".join(topics),
                len(events),
            )
            raise
    commit()
    saved = Counter(event.kafka_topic or event.source for event in events)
    status.record_saved(dict(saved), next_offsets(messages))
    status.write()
    return paths


def run_consumer(
    *,
    topics: list[str] | None = None,
    batch_size: int = 1000,
    flush_interval_sec: int = 30,
) -> None:
    from kafka import KafkaConsumer

    config = config_from_env(topics=topics)

    consumer = KafkaConsumer(
        *config.topics,
        bootstrap_servers=config.bootstrap_servers,
        group_id=config.group_id,
        auto_offset_reset=config.auto_offset_reset,
        enable_auto_commit=False,
        value_deserializer=lambda value: value,
    )
    logger.info(
        "DATA_ENGINE Kafka consumer started topics=%s group_id=%s bootstrap=%s",
        ",".join(config.topics),
        config.group_id,
        config.bootstrap_servers,
    )

    status = ConsumerStatus(config.group_id, topics=config.topics)
    buffer: list[object] = []
    last_flush = time.monotonic()
    while True:
        polled = consumer.poll(timeout_ms=1000)
        for messages in polled.values():
            status.record_received(messages)
            buffer.extend(messages)

        elapsed = time.monotonic() - last_flush
        if not buffer or (len(buffer) < batch_size and elapsed < flush_interval_sec):
            continue

        batch = list(buffer)
        buffer.clear()
        last_flush = time.monotonic()
        for path in process_batch(batch, commit=consumer.commit, status=status):
            logger.info("Kafka events saved: %s", path)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Consume BE Kafka topics into DATA_ENGINE parquet.")
    ap.add_argument("--topics", nargs="*", default=None, help="Override Kafka topics.")
    ap.add_argument("--batch-size", type=int, default=1000)
    ap.add_argument("--flush-interval-sec", type=int, default=30)
    ap.add_argument(
        "--check-config",
        action="store_true",
        help="Validate .env Kafka settings without connecting to Kafka.",
    )
    args = ap.parse_args(argv)
    if args.check_config:
        config = config_from_env(topics=args.topics)
        print(
            "DATA_ENGINE Kafka consumer config OK "
            f"bootstrap={config.bootstrap_servers} "
            f"group_id={config.group_id} "
            f"auto_offset_reset={config.auto_offset_reset} "
            f"topics={','.join(config.topics)}"
        )
        return
    run_consumer(
        topics=args.topics,
        batch_size=args.batch_size,
        flush_interval_sec=args.flush_interval_sec,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    main()
