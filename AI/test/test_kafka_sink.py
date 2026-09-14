from __future__ import annotations

import json

import pandas as pd

from DATA_ENGINE.stream.kafka_events import parse_kafka_event
from DATA_ENGINE.stream.kafka_sink import base_dir_for_topic, write_events


def _event(topic: str, entity_id: str = "ST-1234"):
    return parse_kafka_event(
        {
            "event_id": f"{topic}+{entity_id}+hash",
            "source": topic,
            "entity_id": entity_id,
            "source_generated_at": None,
            "ingested_at": "2026-09-14T09:00:03+09:00",
            "poll_run_at": "2026-09-14T09:00:00+09:00",
            "payload": {"id": entity_id, "value": "7"},
        },
        topic=topic,
        partition=1,
        offset=10,
    )


def test_base_dir_for_topic_maps_domain_paths(tmp_path):
    assert base_dir_for_topic("bike.stock", tmp_path) == tmp_path / "data/BIKE/raw/realtime"
    assert (
        base_dir_for_topic("weather.nowcast", tmp_path)
        == tmp_path / "data/EXTERNAL/weather/raw/nowcast"
    )
    assert base_dir_for_topic("subway.arrival", tmp_path) == tmp_path / "data/SUBWAY/raw/arrival"


def test_write_events_partitions_by_poll_run_at(tmp_path):
    paths = write_events([_event("bike.stock")], ai_root=tmp_path)

    assert len(paths) == 1
    assert paths[0].parent == tmp_path / "data/BIKE/raw/realtime/dt=2026-09-14/hh=09"
    assert paths[0].name.startswith("snapshot_20260914T090000_")

    df = pd.read_parquet(paths[0])
    assert df.loc[0, "event_id"] == "bike.stock+ST-1234+hash"
    assert df.loc[0, "kafka_topic"] == "bike.stock"
    assert df.loc[0, "kafka_partition"] == 1
    assert df.loc[0, "kafka_offset"] == 10
    assert json.loads(df.loc[0, "payload_json"]) == {"id": "ST-1234", "value": "7"}


def test_write_events_groups_by_topic(tmp_path):
    paths = write_events(
        [_event("bike.stock"), _event("weather.nowcast", "weather-seoul")], ai_root=tmp_path
    )

    assert len(paths) == 2
    assert {path.parent for path in paths} == {
        tmp_path / "data/BIKE/raw/realtime/dt=2026-09-14/hh=09",
        tmp_path / "data/EXTERNAL/weather/raw/nowcast/dt=2026-09-14/hh=09",
    }
