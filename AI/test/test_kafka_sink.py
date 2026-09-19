from __future__ import annotations

import json

import pandas as pd
from test_kafka_event_parser import BE_SAMPLE_EVENTS

from DATA_ENGINE.stream.kafka_events import parse_kafka_event
from DATA_ENGINE.stream.kafka_sink import (
    base_dir_for_topic,
    dedupe_events,
    latest_stock_path,
    update_bike_latest_stock,
    write_events,
)
from DATA_ENGINE.stream.weather_latest import latest_weather_path


def _event(
    topic: str,
    entity_id: str = "ST-1234",
    *,
    event_id: str | None = None,
    ingested_at: str = "2026-09-14T09:00:03+09:00",
    payload: dict[str, object] | None = None,
    source_generated_at: str | None = None,
):
    return parse_kafka_event(
        {
            "event_id": event_id or f"{topic}+{entity_id}+hash",
            "source": topic,
            "entity_id": entity_id,
            "source_generated_at": source_generated_at,
            "ingested_at": ingested_at,
            "poll_run_at": "2026-09-14T09:00:00+09:00",
            "payload": payload or {"id": entity_id, "value": "7"},
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
    event = _event(
        "bike.stock",
        payload={"stationId": "ST-1234", "parkingBikeTotCnt": "7"},
    )
    paths = write_events([event], ai_root=tmp_path)

    assert len(paths) == 2
    assert paths[0].parent == tmp_path / "data/BIKE/raw/realtime/dt=2026-09-14/hh=09"
    assert paths[0].name.startswith("snapshot_20260914T090000_")

    df = pd.read_parquet(paths[0])
    assert df.loc[0, "event_id"] == "bike.stock+ST-1234+hash"
    assert df.loc[0, "kafka_topic"] == "bike.stock"
    assert df.loc[0, "kafka_partition"] == 1
    assert df.loc[0, "kafka_offset"] == 10
    assert json.loads(df.loc[0, "payload_json"]) == {
        "stationId": "ST-1234",
        "parkingBikeTotCnt": "7",
    }
    assert paths[1] == latest_stock_path(ai_root=tmp_path)


def test_write_events_groups_by_topic(tmp_path):
    paths = write_events(
        [
            _event(
                "bike.stock",
                payload={"stationId": "ST-1234", "parkingBikeTotCnt": "7"},
            ),
            _event("weather.nowcast", "weather-seoul"),
        ],
        ai_root=tmp_path,
    )

    assert len(paths) == 3
    assert {path.parent for path in paths} == {
        tmp_path / "data/BIKE/raw/realtime/dt=2026-09-14/hh=09",
        tmp_path / "data/EXTERNAL/weather/raw/nowcast/dt=2026-09-14/hh=09",
        tmp_path / "data/BIKE/raw/realtime",
    }


def test_write_be_sample_events_to_topic_partitions(tmp_path):
    events = [
        parse_kafka_event(sample, topic=topic, partition=0, offset=index)
        for index, (topic, sample) in enumerate(BE_SAMPLE_EVENTS.items())
    ]

    paths = write_events(events, ai_root=tmp_path)

    assert {path.parent for path in paths} == {
        tmp_path / "data/SUBWAY/raw/arrival/dt=2026-09-14/hh=11",
        tmp_path / "data/EXTERNAL/weather/raw/nowcast/dt=2026-09-14/hh=12",
        tmp_path / "data/BIKE/raw/realtime/dt=2026-09-14/hh=09",
        tmp_path / "data/BIKE/raw/realtime",
        tmp_path / "data/EXTERNAL/weather/raw/nowcast",
    }

    rows = []
    for path in paths:
        if path.name in {"latest_stock.parquet", "latest_by_grid.parquet"}:
            continue
        rows.extend(pd.read_parquet(path).to_dict("records"))

    by_source = {row["source"]: row for row in rows}
    assert by_source["bike.stock"]["entity_id"] == "ST-4"
    assert by_source["weather.nowcast"]["entity_id"] == "60:127:PTY"
    assert by_source["subway.arrival"]["entity_id"] == "1009000937"
    assert json.loads(by_source["subway.arrival"]["payload_json"])["statnNm"] == "둔촌오륜"
    weather = pd.read_parquet(latest_weather_path(ai_root=tmp_path))
    assert weather.loc[0, "weather_source"] == "observed"
    assert weather.loc[0, "category"] == "PTY"


def test_dedupe_events_keeps_first_event_id():
    first = _event("subway.arrival", "1009000937")
    duplicate = _event("subway.arrival", "1009000937")
    other = _event("subway.arrival", "1009000938")

    assert dedupe_events([first, duplicate, other]) == [first, other]


def test_write_events_dedupes_event_id_within_batch(tmp_path):
    first = _event("subway.arrival", "1009000937")
    duplicate = _event("subway.arrival", "1009000937")

    paths = write_events([first, duplicate], ai_root=tmp_path)

    assert len(paths) == 1
    df = pd.read_parquet(paths[0])
    assert len(df) == 1
    assert df.loc[0, "event_id"] == first.event_id


def test_write_events_keeps_distinct_flushes_in_same_partition(tmp_path):
    first = _event("subway.arrival", "1009000937")
    second = _event("subway.arrival", "1009000938")

    first_path = write_events([first], ai_root=tmp_path)[0]
    second_path = write_events([second], ai_root=tmp_path)[0]

    assert first_path != second_path
    assert first_path.name.startswith("snapshot_20260914T090000_")
    assert pd.read_parquet(first_path)["event_id"].tolist() == [first.event_id]
    assert pd.read_parquet(second_path)["event_id"].tolist() == [second.event_id]
    assert write_events([first], ai_root=tmp_path)[0] == first_path
    assert not list(first_path.parent.glob("*.tmp"))


def test_update_bike_latest_stock_writes_station_snapshot(tmp_path):
    event = _event(
        "bike.stock",
        "ST-4",
        payload={"stationId": "ST-4", "parkingBikeTotCnt": "5"},
    )

    path = update_bike_latest_stock([event], ai_root=tmp_path)

    assert path == latest_stock_path(ai_root=tmp_path)
    df = pd.read_parquet(path)
    assert df.to_dict("records") == [
        {
            "rental_id": "ST-4",
            "current_stock": 5,
            "updated_at": pd.Timestamp("2026-09-14T09:00:03"),
        }
    ]


def test_update_bike_latest_stock_upserts_newer_station_value(tmp_path):
    older = _event(
        "bike.stock",
        "ST-4",
        event_id="bike.stock+ST-4+older",
        ingested_at="2026-09-14T09:00:03+09:00",
        payload={"stationId": "ST-4", "parkingBikeTotCnt": "5"},
    )
    newer = _event(
        "bike.stock",
        "ST-4",
        event_id="bike.stock+ST-4+newer",
        ingested_at="2026-09-14T09:05:03+09:00",
        payload={"stationId": "ST-4", "parkingBikeTotCnt": "8"},
    )

    update_bike_latest_stock([older], ai_root=tmp_path)
    update_bike_latest_stock([newer], ai_root=tmp_path)

    df = pd.read_parquet(latest_stock_path(ai_root=tmp_path))
    assert df[["rental_id", "current_stock"]].to_dict("records") == [
        {"rental_id": "ST-4", "current_stock": 8}
    ]
    assert df.loc[0, "updated_at"] == pd.Timestamp("2026-09-14T09:05:03")


def test_update_bike_latest_stock_keeps_newer_value_when_old_event_arrives(tmp_path):
    newer = _event(
        "bike.stock",
        "ST-4",
        event_id="bike.stock+ST-4+newer",
        ingested_at="2026-09-14T09:05:03+09:00",
        payload={"stationId": "ST-4", "parkingBikeTotCnt": "8"},
    )
    older = _event(
        "bike.stock",
        "ST-4",
        event_id="bike.stock+ST-4+older",
        ingested_at="2026-09-14T09:00:03+09:00",
        payload={"stationId": "ST-4", "parkingBikeTotCnt": "5"},
    )

    update_bike_latest_stock([newer], ai_root=tmp_path)
    update_bike_latest_stock([older], ai_root=tmp_path)

    df = pd.read_parquet(latest_stock_path(ai_root=tmp_path))
    assert df.loc[0, "current_stock"] == 8
    assert df.loc[0, "updated_at"] == pd.Timestamp("2026-09-14T09:05:03")


def test_update_bike_latest_stock_ignores_non_bike_events(tmp_path):
    path = update_bike_latest_stock(
        [_event("weather.nowcast", "weather-seoul")],
        ai_root=tmp_path,
    )

    assert path is None
    assert not latest_stock_path(ai_root=tmp_path).exists()


def test_update_bike_latest_stock_skips_invalid_stock_payload(tmp_path):
    path = update_bike_latest_stock(
        [
            _event(
                "bike.stock",
                "ST-4",
                payload={"stationId": "ST-4", "parkingBikeTotCnt": ""},
            )
        ],
        ai_root=tmp_path,
    )

    assert path is None
    assert not latest_stock_path(ai_root=tmp_path).exists()
