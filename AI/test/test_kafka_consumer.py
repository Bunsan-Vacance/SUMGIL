from __future__ import annotations

from dataclasses import dataclass

from DATA_ENGINE.stream.kafka_consumer import config_from_env, parse_messages


@dataclass(frozen=True)
class _Message:
    value: dict[str, object]
    topic: str = "bike.stock"
    partition: int = 0
    offset: int = 1


def _event_value(event_id: str = "bike.stock+ST-4+hash") -> dict[str, object]:
    return {
        "event_id": event_id,
        "source": "bike.stock",
        "entity_id": "ST-4",
        "source_generated_at": None,
        "ingested_at": "2026-09-14T09:00:03+09:00",
        "poll_run_at": "2026-09-14T09:00:00+09:00",
        "payload": {"stationId": "ST-4"},
    }


def test_config_from_env_uses_be_contract_defaults(monkeypatch):
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    monkeypatch.delenv("KAFKA_CONSUMER_GROUP", raising=False)
    monkeypatch.delenv("KAFKA_AUTO_OFFSET_RESET", raising=False)

    config = config_from_env()

    assert config.bootstrap_servers == "kafka:9092"
    assert config.group_id == "ai-spark"
    assert config.auto_offset_reset == "earliest"
    assert config.topics == ["bike.stock", "weather.nowcast", "subway.arrival"]


def test_config_from_env_allows_topic_override(monkeypatch):
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")

    config = config_from_env(topics=["bike.stock"])

    assert config.topics == ["bike.stock"]


def test_parse_messages_keeps_kafka_metadata():
    events = parse_messages([_Message(_event_value())])

    assert len(events) == 1
    assert events[0].kafka_topic == "bike.stock"
    assert events[0].kafka_partition == 0
    assert events[0].kafka_offset == 1
