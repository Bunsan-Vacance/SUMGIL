"""BIKE 재고 raw snapshot 혼합 스키마 리더 (274) — 273에서 실측으로 필요성을 확인했다.

`DATA_ENGINE/stream/kafka_consumer.py`가 도중에 옛 직결 스키마(bikeList 필드를 그대로 저장,
`payload_json` 없음)에서 지금의 Kafka 봉투 스키마(`payload_json`에 JSON으로 담음)로 바뀌었다.
누적 기간이 그 전환 시점을 걸치면 한 디렉터리 안에 파일마다 스키마가 섞인다.

Spark `spark.read.parquet(*paths)`는 여러 파일에 스키마가 섞이면 그중 하나만 골라 적용하고
나머지 파일에서 컬럼을 못 찾아 죽는다 — 273에서 5,154개 파일 중 425개(옛 스키마)가 섞인
실제 데이터로 재현·확인했다(`validation/INFRA/spark-bike-candidates-check/RESULTS.md` 4번).
pandas 쪽(`DATA_ENGINE/batch/build_bike_stock_5min.py`)은 파일마다
`if "payload_json" in frame.columns`로 분기해서 문제가 없었다 — 이 모듈이 Spark에서 같은
분기를 재현한다.

**entity_id 검증**: 봉투 스키마의 `entity_id`가 있는데 `payload.stationId`와 다르면 그 행은
버린다. pandas `flatten_kafka_bike()`와 동일한 규칙이다 — 273에서 이 검증을 빠뜨렸다가
정확도 대조가 두 번 실패했다(행수 156,209 vs 180,889, 최대 오차 215). 새 잡을 짤 때 이 규칙을
다시 빠뜨리지 않으려고 여기 한 곳에 모아둔다.
"""

from __future__ import annotations

from pathlib import Path

# 공통 산출 스키마 — 이후 어떤 잡(누적 재집계·품질 리포트 등)에서도 이 4컬럼만 보면 된다.
COMMON_COLUMNS = ["station_id", "rack_total_count", "current_bike_count", "collected_at"]


def split_by_schema(files: list[Path]) -> tuple[list[str], list[str]]:
    """파일을 (봉투 스키마 경로들, 직결 스키마 경로들)로 나눈다. 메타데이터만 읽어 가볍다."""
    import pyarrow.parquet as pq

    envelope, flat = [], []
    for f in files:
        names = pq.read_schema(f).names
        (envelope if "payload_json" in names else flat).append(str(f))
    return envelope, flat


def read_bike_stock_raw(spark, files: list[Path]):
    """envelope·flat 두 스키마를 `COMMON_COLUMNS`로 맞춰 합친 DataFrame을 반환한다.

    `collected_at`은 그대로 반환한다(세션 타임존이 Asia/Seoul로 맞춰져 있다는 전제 —
    `spark.session.build_spark_session()`이 이미 설정한다). 결측(`station_id`·
    `current_bike_count` 없음)인 행은 걸러서 반환한다.
    """
    from pyspark.sql import functions as F
    from pyspark.sql.types import StringType, StructField, StructType

    envelope_paths, flat_paths = split_by_schema(files)
    if not envelope_paths and not flat_paths:
        raise ValueError("no snapshot files given")

    parts = []

    if envelope_paths:
        payload_schema = StructType(
            [
                StructField("stationId", StringType()),
                StructField("rackTotCnt", StringType()),
                StructField("parkingBikeTotCnt", StringType()),
            ]
        )
        raw = spark.read.parquet(*envelope_paths)
        parsed = raw.withColumn("payload", F.from_json(F.col("payload_json"), payload_schema))
        entity_id = F.trim(F.col("entity_id"))
        payload_id = F.trim(F.col("payload.stationId"))
        part = (
            parsed.withColumn(
                "station_id",
                F.when((entity_id.isNull()) | (entity_id == ""), payload_id).otherwise(entity_id),
            )
            # entity_id가 payload.stationId와 다르면 손상된 이벤트로 보고 버린다(pandas와 동일 규칙).
            .where(entity_id.isNull() | (entity_id == "") | (entity_id == payload_id)).select(
                "station_id",
                F.col("payload.rackTotCnt").cast("double").alias("rack_total_count"),
                F.col("payload.parkingBikeTotCnt").cast("double").alias("current_bike_count"),
                F.col("ingested_at").alias("collected_at"),
            )
        )
        parts.append(part)

    if flat_paths:
        raw = spark.read.parquet(*flat_paths)
        part = raw.select(
            F.col("stationId").alias("station_id"),
            F.col("rackTotCnt").cast("double").alias("rack_total_count"),
            F.col("parkingBikeTotCnt").cast("double").alias("current_bike_count"),
            F.col("collected_at").cast("timestamp").alias("collected_at"),
        )
        parts.append(part)

    df = parts[0]
    for p in parts[1:]:
        df = df.unionByName(p)
    return df.where(F.col("station_id").isNotNull() & F.col("current_bike_count").isNotNull())
