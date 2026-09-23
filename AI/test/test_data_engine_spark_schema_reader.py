from __future__ import annotations

import json

import pandas as pd
import pytest

pyspark = pytest.importorskip("pyspark")

from DATA_ENGINE.spark.schema_reader import read_bike_stock_raw, split_by_schema
from DATA_ENGINE.spark.session import build_spark_session


@pytest.fixture(scope="module")
def spark():
    session = build_spark_session("test-schema-reader", cores="1", driver_memory="1g")
    yield session
    session.stop()


def _write_flat_file(path, ts) -> None:
    """273에서 실측한 옛 직결 스키마(payload_json 없음)."""
    df = pd.DataFrame(
        {
            "stationId": ["ST-1"],
            "stationName": ["역1"],
            "rackTotCnt": [10],
            "parkingBikeTotCnt": [3],
            "shared": [0],
            "stationLatitude": [37.5],
            "stationLongitude": [127.0],
            "collected_at": [pd.Timestamp(ts, tz="Asia/Seoul")],
            "source": ["bike.stock"],
        }
    )
    df.to_parquet(path)


def _write_envelope_file(path, rows: list[dict], ts) -> None:
    """지금의 Kafka 봉투 스키마. `rows`는 (entity_id, station_id_in_payload, bike_count) 튜플 목록."""
    records = []
    for i, (entity_id, payload_station, bike_count) in enumerate(rows):
        payload = {
            "stationId": payload_station,
            "rackTotCnt": "10",
            "parkingBikeTotCnt": str(bike_count),
        }
        records.append(
            {
                "event_id": f"evt-{i}",
                "source": "bike.stock",
                "entity_id": entity_id,
                "source_generated_at": None,
                "ingested_at": pd.Timestamp(ts, tz="Asia/Seoul"),
                "poll_run_at": pd.Timestamp(ts, tz="Asia/Seoul"),
                "freshness_at": pd.Timestamp(ts, tz="Asia/Seoul"),
                "payload_json": json.dumps(payload, ensure_ascii=False),
                "kafka_topic": "bike.stock",
                "kafka_partition": 0,
                "kafka_offset": i,
            }
        )
    pd.DataFrame(records).to_parquet(path)


def test_split_by_schema_separates_envelope_and_flat_files(tmp_path):
    flat_path = tmp_path / "flat.parquet"
    envelope_path = tmp_path / "envelope.parquet"
    _write_flat_file(flat_path, "2026-09-23 09:00:00")
    _write_envelope_file(envelope_path, [("ST-2", "ST-2", 5)], "2026-09-23 09:05:00")

    envelope, flat = split_by_schema([flat_path, envelope_path])
    assert flat == [str(flat_path)]
    assert envelope == [str(envelope_path)]


def test_read_bike_stock_raw_merges_both_schemas_and_drops_mismatched_entity_id(spark, tmp_path):
    flat_path = tmp_path / "flat.parquet"
    envelope_path = tmp_path / "envelope.parquet"
    _write_flat_file(flat_path, "2026-09-23 09:00:00")
    _write_envelope_file(
        envelope_path,
        [
            ("ST-2", "ST-2", 5),  # 정상 — entity_id == payload.stationId
            ("ST-3", "ST-9", 7),  # 손상 — entity_id != payload.stationId, 버려야 함
            (None, "ST-4", 9),  # entity_id 없음 — payload.stationId로 대체
        ],
        "2026-09-23 09:05:00",
    )

    df = read_bike_stock_raw(spark, [flat_path, envelope_path])
    result = df.toPandas().sort_values("station_id").reset_index(drop=True)

    # ST-9(entity_id 불일치로 버려진 행의 station_id)는 결과에 없어야 한다.
    assert set(result["station_id"]) == {"ST-1", "ST-2", "ST-4"}
    assert list(result.columns) == [
        "station_id",
        "rack_total_count",
        "current_bike_count",
        "collected_at",
    ]
