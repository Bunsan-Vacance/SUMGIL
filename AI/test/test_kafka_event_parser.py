from __future__ import annotations

import json

import pytest

from DATA_ENGINE.stream.kafka_events import parse_kafka_event

BE_SAMPLE_EVENTS = {
    "subway.arrival": {
        "event_id": "784932211c0479567199d73ba722caba3b534de1c345579e08433b94c7548dc1",
        "source": "subway.arrival",
        "entity_id": "1009000937",
        "source_generated_at": "2026-09-14T11:46:06+09:00",
        "ingested_at": "2026-09-14T11:50:21.461+09:00",
        "poll_run_at": "2026-09-14T11:50:21+09:00",
        "payload": {
            "subwayId": "1009",
            "statnId": "1009000937",
            "statnNm": "둔촌오륜",
            "updnLine": "하행",
            "trainLineNm": "개화행 - 올림픽공원방면",
            "barvlDt": "20",
            "recptnDt": "2026-09-14 11:46:06",
            "arvlMsg2": "둔촌오륜 출발",
            "arvlCd": "2",
            "subwayNm": None,
        },
    },
    "weather.nowcast": {
        "event_id": "1cbb96d627ba0cb5a1436593cf4805cef9aac5ac8d5e3410676166325e7a9a0f",
        "source": "weather.nowcast",
        "entity_id": "60:127:PTY",
        "source_generated_at": "2026-09-14T11:00:00+09:00",
        "ingested_at": "2026-09-14T12:28:26.625+09:00",
        "poll_run_at": "2026-09-14T12:28:26+09:00",
        "payload": {
            "baseDate": "20260914",
            "baseTime": "1100",
            "category": "PTY",
            "nx": 60,
            "ny": 127,
            "obsrValue": "0",
        },
    },
    "bike.stock": {
        "event_id": "bike-stock-source-entity-payload-hash",
        "source": "bike.stock",
        "entity_id": "ST-4",
        "source_generated_at": None,
        "ingested_at": "2026-09-14T09:00:03+09:00",
        "poll_run_at": "2026-09-14T09:00:00+09:00",
        "payload": {
            "stationId": "ST-4",
            "stationName": "102. 망원역 1번출구 앞",
            "rackTotCnt": "15",
            "parkingBikeTotCnt": "5",
            "shared": "33",
            "stationLatitude": "37.55564880",
            "stationLongitude": "126.91062927",
        },
    },
}


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


@pytest.mark.parametrize("topic", ["subway.arrival", "weather.nowcast", "bike.stock"])
def test_parse_be_sample_events(topic):
    event = parse_kafka_event(BE_SAMPLE_EVENTS[topic], topic=topic, partition=0, offset=1)

    assert event.source == topic
    assert event.kafka_topic == topic
    assert event.kafka_partition == 0
    assert event.kafka_offset == 1
    assert event.partition_time.isoformat() == BE_SAMPLE_EVENTS[topic]["poll_run_at"]
    assert json.loads(event.to_record()["payload_json"]) == BE_SAMPLE_EVENTS[topic]["payload"]


def test_parse_be_bike_sample_uses_ingested_at_for_freshness():
    event = parse_kafka_event(BE_SAMPLE_EVENTS["bike.stock"])

    assert event.source_generated_at is None
    assert event.freshness_time.isoformat() == "2026-09-14T09:00:03+09:00"


def test_parse_be_weather_sample_uses_source_generated_at_for_freshness():
    event = parse_kafka_event(BE_SAMPLE_EVENTS["weather.nowcast"])

    assert event.freshness_time.isoformat() == "2026-09-14T11:00:00+09:00"
