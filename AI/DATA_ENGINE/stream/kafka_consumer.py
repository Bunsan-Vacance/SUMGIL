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
from collections.abc import Iterable
from dataclasses import dataclass

from dotenv import load_dotenv

from DATA_ENGINE.collect.common import env
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


def parse_messages(messages: Iterable[object]) -> list[KafkaEvent]:
    events: list[KafkaEvent] = []
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
            logger.exception(
                "Kafka message parse failed: topic=%s partition=%s offset=%s",
                getattr(msg, "topic", None),
                getattr(msg, "partition", None),
                getattr(msg, "offset", None),
            )
    return events


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

    buffer: list[object] = []
    last_flush = time.monotonic()
    while True:
        polled = consumer.poll(timeout_ms=1000)
        for messages in polled.values():
            buffer.extend(messages)

        elapsed = time.monotonic() - last_flush
        if not buffer or (len(buffer) < batch_size and elapsed < flush_interval_sec):
            continue

        events = parse_messages(buffer)
        buffer.clear()
        last_flush = time.monotonic()
        if not events:
            continue
        paths = write_events(events)
        consumer.commit()
        for path in paths:
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
