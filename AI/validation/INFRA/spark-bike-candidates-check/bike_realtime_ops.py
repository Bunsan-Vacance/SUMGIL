"""후보 2 — 따릉이 재고 raw snapshot 누적 재집계.

실제 프로덕션 pandas 잡(`DATA_ENGINE/batch/build_bike_stock_5min.py`)은 **하루치**만 처리한다.
"누적 재집계"는 그 5분 테이블을 여러 날 누적해서 (역, 요일, 시간대)별 평균·표준편차까지
내는 것 — 결정문서(2-6)가 말하는 실제 작업 형태다. pandas 쪽은 프로덕션 함수를 그대로
재사용해 대조 신뢰도를 높인다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(AI_ROOT))

from DATA_ENGINE.batch.build_bike_stock_5min import (  # noqa: E402
    normalize_bike_stock,
    read_raw_snapshots,
)


def snapshot_files(root: Path) -> list[Path]:
    return sorted(root.glob("dt=*/hh=*/snapshot_*.parquet"))


# ── pandas — 프로덕션 함수 그대로 재사용 ──
def op_pandas(files: list[Path]) -> pd.DataFrame:
    raw = read_raw_snapshots(files)
    five_min = normalize_bike_stock(raw)
    agg = (
        five_min.groupby(["station_id", five_min["collected_at"].dt.dayofweek, "collected_hour"])
        .agg(
            avg_bike_count=("current_bike_count", "mean"),
            std_bike_count=("current_bike_count", "std"),
            avg_stock_ratio=("stock_ratio", "mean"),
            n_obs=("current_bike_count", "count"),
        )
        .reset_index()
        .rename(columns={"collected_at": "dow"})
    )
    return agg.sort_values(["station_id", "dow", "collected_hour"]).reset_index(drop=True)


def _split_by_schema(files: list[Path]) -> tuple[list[str], list[str]]:
    """실측: 10일치 축적분(5,154개) 중 425개는 옛 직결 스키마(payload_json 없음),
    4,729개는 지금 Kafka 봉투 스키마다 — 컨슈머가 도중에 한 번 바뀐 흔적. pandas는
    파일마다 `if "payload_json" in frame.columns`로 분기해서 문제없이 섞어 읽지만,
    Spark `read.parquet(*paths)`는 여러 파일에 스키마가 섞이면 그중 하나만 골라
    적용하고 나머지에서 컬럼을 못 찾아 죽는다(실측으로 확인). 파일을 미리 두 그룹으로
    나눠 각각 읽고 공통 스키마로 맞춘 뒤 합친다 — "혼합 스키마 리더"가 실제로 필요했던 지점."""
    import pyarrow.parquet as pq

    envelope, flat = [], []
    for f in files:
        names = pq.read_schema(f).names
        (envelope if "payload_json" in names else flat).append(str(f))
    return envelope, flat


# ── spark — 같은 로직을 직접 구현(파일 I/O·JSON 파싱·dedup·집계) ──
def op_spark(spark, files: list[Path]):
    from pyspark.sql import Window
    from pyspark.sql import functions as F
    from pyspark.sql.types import StringType, StructField, StructType

    envelope_paths, flat_paths = _split_by_schema(files)

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
        # pandas `flatten_kafka_bike`와 동일 검증: entity_id가 있는데 payload.stationId와
        # 다르면 그 행은 버린다(불일치 = 손상된 이벤트로 취급). 빠뜨리면 표본이 갈린다(실측으로 확인).
        part = (
            parsed.withColumn(
                "station_id",
                F.when((entity_id.isNull()) | (entity_id == ""), payload_id).otherwise(entity_id),
            )
            .where(entity_id.isNull() | (entity_id == "") | (entity_id == payload_id))
            .select(
                "station_id",
                F.col("payload.rackTotCnt").cast("double").alias("rack_total_count"),
                F.col("payload.parkingBikeTotCnt").cast("double").alias("current_bike_count"),
                # ingested_at은 parquet에 이미 Asia/Seoul tz-aware로 저장돼 있다(pyarrow 스키마로
                # 확인함). 세션 타임존을 Asia/Seoul로 맞췄으면 그대로 쓰면 되고, 여기서 다시
                # from_utc_timestamp로 +9시간을 또 더하면 이중 변환이 된다(실측으로 확인한 버그).
                F.col("ingested_at").alias("collected_at"),
            )
        )
        parts.append(part)

    if flat_paths:
        # 옛 직결 스키마는 collected_at이 이미 KST naive로 저장돼 있다(pandas
        # `read_raw_snapshots`도 이 그룹은 변환 없이 그대로 쓴다 — 대조 기준을 맞춘다).
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
    df = df.where(F.col("station_id").isNotNull() & F.col("current_bike_count").isNotNull())

    df = df.withColumn(
        "stock_ratio",
        F.when(
            F.col("rack_total_count") > 0, F.col("current_bike_count") / F.col("rack_total_count")
        ),
    )
    df = df.withColumn(
        "slot_5m", F.date_trunc("minute", F.col("collected_at"))
    )  # 근사(분 단위 truncate 후 5분 버킷은 아래)
    df = df.withColumn(
        "slot_5m",
        F.from_unixtime(F.floor(F.unix_timestamp(F.col("collected_at")) / 300) * 300),
    )

    # 같은 (station, slot_5m) 안에서 가장 최근 값만 남긴다 (pandas의 drop_duplicates(keep="last")와 동일).
    window = Window.partitionBy("station_id", "slot_5m").orderBy(F.col("collected_at").desc())
    deduped = df.withColumn("rn", F.row_number().over(window)).where(F.col("rn") == 1).drop("rn")

    # Spark dayofweek: 일=1..토=7. pandas dt.dayofweek: 월=0..일=6로 통일한다((spark+5)%7).
    spark_dow = F.dayofweek(F.col("collected_at"))
    agg = deduped.groupBy(
        "station_id",
        ((spark_dow + 5) % 7).alias("dow"),
        F.hour(F.col("collected_at")).alias("collected_hour"),
    ).agg(
        F.mean("current_bike_count").alias("avg_bike_count"),
        F.stddev("current_bike_count").alias("std_bike_count"),
        F.mean("stock_ratio").alias("avg_stock_ratio"),
        F.count("current_bike_count").alias("n_obs"),
    )
    return agg.orderBy("station_id", "dow", "collected_hour")
