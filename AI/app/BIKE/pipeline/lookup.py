"""avg baseline — station × dow_type × time_slot 재고·확률 평균 조회.

CROWD의 `lookup.py`(요일유형×역×시간대 승하차 평균)와 같은 위상이다 — 모델 없이 실측값을
직접 평균 내는 "정직한 기준선"이고, `source=avg`로 그대로 서빙에 들어간다.
`validation/BYC/full-coverage-check/src/stock_probability.py`에서 검증된 계산을 승격했다.

    exp_bikes  = 그 그룹의 stock_anchor_hour 평균
    p_empty    = 그 그룹에서 재고==0(is_empty_anchor)인 비율
    p_full     = 그 그룹에서 재고>=rack_count(is_full_anchor)인 비율

**조회 실패 처리**: 표본이 없는 (station, dow_type, time_slot) 조합은 행을 만들지 않는다
(전체 평균으로 채우면 실제보다 좋아 보이고, 서빙에서는 "데이터 없음"으로 봐야 한다 —
데이터 검증 리포트 원칙 8).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.BIKE.pipeline.calendar import attach_dow_type, load_holidays, slot_5m_to_time_slot

STOCK_KEYS = ["od_station_id", "dow_type", "time_slot"]
STOCK_NEEDED_COLS = [
    "od_station_id",
    "date",
    "slot_5m",
    "stock_anchor_hour",
    "is_empty_anchor",
    "is_full_anchor",
    "rack_count",
]


class StockProfileBaseline:
    """station × dow_type × time_slot 재고 평균·empty/full 빈도. train 기간으로만 fit한다."""

    def __init__(self) -> None:
        self.table_: pd.DataFrame | None = None

    def fit_streaming(
        self, paths: list[Path], holidays: pd.DataFrame | None = None
    ) -> StockProfileBaseline:
        """여러 parquet을 순회하며 그룹별 부분합(sum·count)을 누적한다.

        전체를 한 번에 메모리에 안 올린다 — sum/count를 파일 단위로 합산하면 전체를
        한 번에 읽은 것과 수학적으로 동일한 평균이 나온다(MapReduce의 mean과 같은 원리).
        """
        if holidays is None:
            holidays = load_holidays()
        total = None
        for p in paths:
            df = pd.read_parquet(p, columns=[*STOCK_NEEDED_COLS, "horizon_min"])
            df = df[df["horizon_min"] == 5]  # base_time당 1행만(horizon 4종 중복 제거)
            df = df.dropna(subset=["stock_anchor_hour"])
            df = attach_dow_type(df, holidays)
            df["time_slot"] = slot_5m_to_time_slot(df["slot_5m"])

            g = df.groupby(STOCK_KEYS).agg(
                exp_bikes_sum=("stock_anchor_hour", "sum"),
                n=("stock_anchor_hour", "count"),
                empty_sum=("is_empty_anchor", "sum"),
                full_sum=("is_full_anchor", "sum"),
            )
            total = g if total is None else total.add(g, fill_value=0)
            del df

        total["exp_bikes"] = total["exp_bikes_sum"] / total["n"]
        total["p_empty"] = total["empty_sum"] / total["n"]
        total["p_full"] = total["full_sum"] / total["n"]
        self.table_ = total.reset_index()[[*STOCK_KEYS, "exp_bikes", "p_empty", "p_full"]]
        return self

    def fit_streaming_spark(
        self, paths: list[Path], holidays: pd.DataFrame | None = None
    ) -> StockProfileBaseline:
        """`fit_streaming()`과 같은 계산을 Spark로 한다(274 B안 — `train.py --engine spark`).

        `DATA_ENGINE/spark/jobs/bike_avg_baseline.py`에서 만들고 11개월 250.7M행 실측으로
        검증한 로직(pandas와 완전 일치, 오차 0.0)을 그대로 옮겼다 — 새로 설계하지 않았다.
        저장소 계층 규칙(`AI/CLAUDE.md`: `app/`은 `DATA_ENGINE/`을 import하지 않는다)을 지키려고
        `DATA_ENGINE.spark`를 가져다 쓰는 대신 `app/BIKE/pipeline/` 안에 직접 재구현했다 — 두
        구현이 갈라지지 않도록 로직을 바꿀 땐 두 곳(`DATA_ENGINE/spark/jobs/bike_avg_baseline.py`,
        여기)을 같이 바꿔야 한다.

        pyspark는 여기서만 지연 import한다 — `avg` 서빙 경로(`predictor.py`가 이 클래스를
        직접 쓴다)가 이 메서드를 안 부르므로 서빙에 무거운 의존성이 안 번진다.
        """
        from pyspark.sql import SparkSession
        from pyspark.sql import functions as F

        if holidays is None:
            holidays = load_holidays()

        spark = (
            SparkSession.builder.appName("bike-avg-baseline-train")
            .master("local[3]")
            .config("spark.driver.memory", "3g")
            .config("spark.sql.shuffle.partitions", "32")
            .config("spark.sql.session.timeZone", "Asia/Seoul")
            .config("spark.ui.showConsoleProgress", "false")
            .getOrCreate()
        )
        try:
            raw = spark.read.parquet(*[str(p) for p in paths]).select(
                *STOCK_NEEDED_COLS, "horizon_min"
            )
            raw = raw.where((F.col("horizon_min") == 5) & F.col("stock_anchor_hour").isNotNull())

            holidays_sdf = spark.createDataFrame(holidays).withColumnRenamed("date", "holiday_date")
            joined = raw.join(
                holidays_sdf, raw["date"] == holidays_sdf["holiday_date"], how="left"
            ).drop("holiday_date")
            is_holiday = F.coalesce(F.col("is_holiday"), F.lit(False))

            # Spark dayofweek: 일=1..토=7. calendar.attach_dow_type과 같은 우선순위
            # (토요일(1) → 일요일 또는 공휴일(2) → 평일(0))를 지킨다.
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
            result = agg.select(
                "od_station_id",
                "dow_type",
                "time_slot",
                (F.col("exp_bikes_sum") / F.col("n")).alias("exp_bikes"),
                (F.col("empty_sum") / F.col("n")).alias("p_empty"),
                (F.col("full_sum") / F.col("n")).alias("p_full"),
            )
            self.table_ = result.toPandas()[[*STOCK_KEYS, "exp_bikes", "p_empty", "p_full"]]
        finally:
            spark.stop()
        return self

    def predict(self) -> pd.DataFrame:
        """전체 (station, dow_type, time_slot) 조합의 표를 그대로 돌려준다(표본 있는 것만)."""
        if self.table_ is None:
            raise RuntimeError("fit_streaming()을 먼저 호출해야 한다.")
        return self.table_.rename(columns={"od_station_id": "rental_id"}).copy()

    # ── 아티팩트 ──
    def save(self, path: Path) -> Path:
        if self.table_ is None:
            raise RuntimeError("fit_streaming()을 먼저 호출해야 한다.")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.table_.to_parquet(path, index=False)
        return path

    @classmethod
    def load(cls, path: Path) -> StockProfileBaseline:
        model = cls()
        model.table_ = pd.read_parquet(path)
        return model
