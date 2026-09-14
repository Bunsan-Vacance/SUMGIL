"""Kafka event envelope parsing.

BE Kafka producer emits a common envelope and keeps source API rows inside
``payload``. The stream sink stores the envelope columns plus the payload JSON
without assuming each topic's final flattened schema yet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from DATA_ENGINE.collect.common import KST

REQUIRED_FIELDS = {
    "event_id",
    "source",
    "entity_id",
    "source_generated_at",
    "ingested_at",
    "poll_run_at",
    "payload",
}


@dataclass(frozen=True)
class KafkaEvent:
    event_id: str
    source: str
    entity_id: str
    source_generated_at: datetime | None
    ingested_at: datetime
    poll_run_at: datetime | None
    payload: dict[str, Any] | list[Any] | str | int | float | bool | None
    kafka_topic: str | None = None
    kafka_partition: int | None = None
    kafka_offset: int | None = None

    @property
    def partition_time(self) -> datetime:
        return self.poll_run_at or self.ingested_at

    def to_record(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "source": self.source,
            "entity_id": self.entity_id,
            "source_generated_at": self.source_generated_at,
            "ingested_at": self.ingested_at,
            "poll_run_at": self.poll_run_at,
            "payload_json": json.dumps(self.payload, ensure_ascii=False, sort_keys=True),
            "kafka_topic": self.kafka_topic,
            "kafka_partition": self.kafka_partition,
            "kafka_offset": self.kafka_offset,
        }


def _parse_datetime(value: Any, field: str, *, required: bool) -> datetime | None:
    if value in (None, ""):
        if required:
            raise ValueError(f"{field} is required")
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        dt = datetime.fromisoformat(value)
    else:
        raise TypeError(f"{field} must be ISO datetime string: {value!r}")
    if dt.tzinfo is None:
        return dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def decode_event_value(value: bytes | str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        decoded = json.loads(value)
    else:
        decoded = value
    if not isinstance(decoded, dict):
        raise TypeError("Kafka event must be a JSON object")
    return decoded


def parse_kafka_event(
    value: bytes | str | dict[str, Any],
    *,
    topic: str | None = None,
    partition: int | None = None,
    offset: int | None = None,
) -> KafkaEvent:
    raw = decode_event_value(value)
    missing = sorted(REQUIRED_FIELDS - set(raw))
    if missing:
        raise ValueError(f"Kafka event missing required fields: {missing}")

    event_id = str(raw["event_id"])
    source = str(raw["source"])
    entity_id = str(raw["entity_id"])
    if not event_id:
        raise ValueError("event_id is required")
    if not source:
        raise ValueError("source is required")
    if not entity_id:
        raise ValueError("entity_id is required")

    return KafkaEvent(
        event_id=event_id,
        source=source,
        entity_id=entity_id,
        source_generated_at=_parse_datetime(
            raw["source_generated_at"], "source_generated_at", required=False
        ),
        ingested_at=_parse_datetime(raw["ingested_at"], "ingested_at", required=True),
        poll_run_at=_parse_datetime(raw["poll_run_at"], "poll_run_at", required=False),
        payload=raw["payload"],
        kafka_topic=topic,
        kafka_partition=partition,
        kafka_offset=offset,
    )
