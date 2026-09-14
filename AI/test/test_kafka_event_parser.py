from __future__ import annotations

import json

import pytest

from DATA_ENGINE.stream.kafka_events import parse_kafka_event


def event_payload(**overrides):
    payload = {
        "event_id": "bike.stock+ST-1234+hash",
        "source": "bike.stock",
        "entity_id": "ST-1234",
        "source_generated_at": None,
        "ingested_at": "2026-09-14T09:00:03+09:00",
        "poll_run_at": "2026-09-14T09:00:00+09:00",
        "payload": {"stationId": "ST-1234", "parkingBikeTotCnt": "7"},
    }
    payload.update(overrides)
    return payload


def test_parse_kafka_event_from_bytes():
    raw = json.dumps(event_payload(), ensure_ascii=False).encode("utf-8")

    event = parse_kafka_event(raw, topic="bike.stock", partition=0, offset=42)

    assert event.event_id == "bike.stock+ST-1234+hash"
    assert event.entity_id == "ST-1234"
    assert event.source_generated_at is None
    assert event.partition_time.isoformat() == "2026-09-14T09:00:00+09:00"
    assert event.kafka_topic == "bike.stock"
    assert event.kafka_partition == 0
    assert event.kafka_offset == 42
    assert json.loads(event.to_record()["payload_json"])["stationId"] == "ST-1234"


def test_parse_kafka_event_falls_back_to_ingested_at():
    event = parse_kafka_event(event_payload(poll_run_at=None))

    assert event.partition_time.isoformat() == "2026-09-14T09:00:03+09:00"


def test_parse_kafka_event_freshness_prefers_source_generated_at():
    event = parse_kafka_event(
        event_payload(
            source_generated_at="2026-09-14T08:59:00+09:00",
            ingested_at="2026-09-14T09:00:03+09:00",
        )
    )

    assert event.freshness_time.isoformat() == "2026-09-14T08:59:00+09:00"
    assert event.to_record()["freshness_at"].isoformat() == "2026-09-14T08:59:00+09:00"


def test_parse_kafka_event_freshness_falls_back_to_ingested_at():
    event = parse_kafka_event(event_payload(source_generated_at=None))

    assert event.freshness_time.isoformat() == "2026-09-14T09:00:03+09:00"


def test_parse_kafka_event_requires_envelope_fields():
    payload = event_payload()
    del payload["event_id"]

    with pytest.raises(ValueError, match="missing required fields"):
        parse_kafka_event(payload)
