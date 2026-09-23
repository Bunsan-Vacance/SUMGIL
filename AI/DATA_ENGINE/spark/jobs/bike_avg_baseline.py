"""BIKE avg baseline — Spark 대조용 재구현 (274-A).

`app/BIKE/pipeline/lookup.py`의 `StockProfileBaseline.fit_streaming()`(`train.py`가 모델
재학습 시 호출, `validation/BYC/full-coverage-check/outputs/full-run/
train_netflow_q3_mapped_full_202401~202411.parquet` 11개 파일·250.7M행을 스트리밍 부분합으로
처리)을 Spark로 재현한다.

**`train.py`는 건드리지 않는다.** 실제 서빙에 쓰이는 `stock_profile_avg.parquet`은 여전히
pandas(`train.py`)가 만든다 — 이 잡의 출력은 검증용 별도 경로에만 쓰고, pandas 결과와 값이
같은지 대조하는 데만 쓴다(274 범위 A안). `train.py`가 Spark를 실제로 골라 쓰게 하려면
`app/`이 `DATA_ENGINE/`을 import하지 않는다는 계층 규칙(`AI/CLAUDE.md`)과 부딪히므로 별도
논의가 필요하다 — 이 잡은 그 논의 전에 "같은 값이 나오는가"만 먼저 확인한다.

로직은 `app/BIKE/pipeline/lookup.py`(`StockProfileBaseline`)·`calendar.py`
(`attach_dow_type`, `slot_5m_to_time_slot`)를 그대로 옮긴 것이다 — 새로 설계하지 않았다.
dow_type 우선순위(토요일(1) → 일요일 또는 공휴일(2) → 평일(0))는 `calendar.attach_dow_type`의
주석과 동일한 이유로 이 순서를 지킨다(토요일이면서 공휴일인 날 오판 방지).

실행:
    cd AI
    python -m DATA_ENGINE.spark.jobs.bike_avg_baseline --train-months 202401 202402 ... 202411
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

import pandas as pd

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

AI_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(AI_ROOT))

from app.BIKE.pipeline.calendar import DEFAULT_HOLIDAY_PATH, load_holidays  # noqa: E402
from app.BIKE.pipeline.dataset import monthly_paths  # noqa: E402
from app.BIKE.pipeline.lookup import STOCK_KEYS, StockProfileBaseline  # noqa: E402
from DATA_ENGINE.spark.metrics import compare_frames  # noqa: E402
from DATA_ENGINE.spark.session import build_spark_session  # noqa: E402

STOCK_NEEDED_COLS = [
    "od_station_id",
    "date",
    "slot_5m",
    "stock_anchor_hour",
    "is_empty_anchor",
    "is_full_anchor",
    "rack_count",
    "horizon_min",
]
VALUE_COLS = ["exp_bikes", "p_empty", "p_full"]


def fit_pandas(paths: list[Path]) -> pd.DataFrame:
    """production 함수를 그대로 호출한다 — 대조 신뢰도를 위해 재구현하지 않는다."""
    holidays = load_holidays()
    return (
        StockProfileBaseline()
        .fit_streaming(paths, holidays)
        .predict()
        .rename(columns={"rental_id": "od_station_id"})
    )


def fit_spark(spark, paths: list[Path]):
    """`StockProfileBaseline.fit_streaming()`과 같은 계산을 Spark로 한다.

    pandas는 파일마다 부분합을 누적하는 스트리밍 방식이지만, Spark는 lazy evaluation +
    분산 셔플로 같은 효과(전체를 한 번에 안 올리고 그룹별 합계를 냄)를 낸다 — 굳이
    파일 단위 루프로 흉내 낼 필요가 없다.
    """
    from pyspark.sql import functions as F

    raw = spark.read.parquet(*[str(p) for p in paths]).select(*STOCK_NEEDED_COLS)
    raw = raw.where((F.col("horizon_min") == 5) & F.col("stock_anchor_hour").isNotNull())

    holidays_pdf = load_holidays(DEFAULT_HOLIDAY_PATH)
    holidays_sdf = spark.createDataFrame(holidays_pdf).withColumnRenamed("date", "holiday_date")

    joined = raw.join(holidays_sdf, raw["date"] == holidays_sdf["holiday_date"], how="left").drop(
        "holiday_date"
    )
    is_holiday = F.coalesce(F.col("is_holiday"), F.lit(False))

    # Spark dayofweek: 일=1..토=7. 토요일(1) → 일요일 또는 공휴일(2) → 평일(0) 순서를
    # calendar.attach_dow_type과 동일하게 지킨다(토요일+공휴일 오판 방지).
    spark_dow = F.dayofweek(F.col("date"))
    is_saturday = spark_dow == 7
    is_sunday = spark_dow == 1
    dow_type = F.when(is_saturday, 1).when(is_sunday | is_holiday, 2).otherwise(0)

    df = joined.withColumn("dow_type", dow_type).withColumn(
        "time_slot", (F.col("slot_5m") / 6).cast("int")
    )

    agg = df.groupBy("od_station_id", "dow_type", "time_slot").agg(
        F.sum("stock_anchor_hour").alias("exp_bikes_sum"),
        F.count("stock_anchor_hour").alias("n"),
        F.sum(F.col("is_empty_anchor").cast("int")).alias("empty_sum"),
        F.sum(F.col("is_full_anchor").cast("int")).alias("full_sum"),
    )
    return agg.select(
        "od_station_id",
        "dow_type",
        "time_slot",
        (F.col("exp_bikes_sum") / F.col("n")).alias("exp_bikes"),
        (F.col("empty_sum") / F.col("n")).alias("p_empty"),
        (F.col("full_sum") / F.col("n")).alias("p_full"),
    )


def run(train_months: list[str]) -> dict:
    paths = monthly_paths("train", train_months)
    print(f"[bike_avg_baseline] 입력 {len(paths)}개 파일: {[p.name for p in paths]}")

    t0 = time.perf_counter()
    pandas_result = fit_pandas(paths)
    pandas_wall = time.perf_counter() - t0
    print(f"[bike_avg_baseline] pandas {pandas_wall:.1f}초, {len(pandas_result)}행")

    spark = build_spark_session("bike-avg-baseline")
    try:
        t0 = time.perf_counter()
        spark_df = fit_spark(spark, paths)
        spark_result = spark_df.toPandas()
        spark_wall = time.perf_counter() - t0
    finally:
        spark.stop()
    print(f"[bike_avg_baseline] spark {spark_wall:.1f}초, {len(spark_result)}행")

    accuracy = compare_frames(
        pandas_result, spark_result, key_cols=STOCK_KEYS, value_cols=VALUE_COLS
    )
    result = {
        "train_months": train_months,
        "files": len(paths),
        "pandas_wall_sec": round(pandas_wall, 2),
        "spark_wall_sec": round(spark_wall, 2),
        "ratio_spark_over_pandas": round(spark_wall / pandas_wall, 3) if pandas_wall else None,
        **accuracy,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--train-months", nargs="+", required=True)
    ap.add_argument("--out", type=Path, default=None, help="결과 json 저장 경로(선택)")
    args = ap.parse_args(argv)

    result = run(args.train_months)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[bike_avg_baseline] 완료 — {args.out}")


if __name__ == "__main__":
    main()
