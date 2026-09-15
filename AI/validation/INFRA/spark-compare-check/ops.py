"""벤치마크 대상 세 가지 연산(OP-A/B/C)의 pandas·PySpark 구현.

각 OP은 실제 파이프라인에서 무거운 연산 패턴을 그대로 옮긴 것이다(README 참고: 저장소는
lookup 잔차·시차 피처를 날짜+슬롯 키 조인으로 만들고, 위치 shift는 쓰지 않는다 — 빠진 날이
있어도 이전 행을 끌어오지 않기 위함).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# OP-A: panel_join — (station_no, time_slot, day_type)별 평균 lookup -> 잔차 ->
#       날짜+슬롯 키 조인으로 lag1d/lag7d 잔차 컬럼 생성
# ---------------------------------------------------------------------------


def op_a_pandas(df: pd.DataFrame) -> pd.DataFrame:
    keys = ["station_no", "time_slot", "day_type"]
    lookup = df.groupby(keys, as_index=False)[["boarding", "alighting"]].mean()
    lookup = lookup.rename(columns={"boarding": "avg_boarding", "alighting": "avg_alighting"})

    joined = df.merge(lookup, on=keys, how="left")
    joined["boarding_resid"] = joined["boarding"] - joined["avg_boarding"]
    joined["alighting_resid"] = joined["alighting"] - joined["avg_alighting"]

    resid = joined[["station_no", "time_slot", "date", "boarding_resid", "alighting_resid"]]

    def lag_join(base: pd.DataFrame, lag_days: int, suffix: str) -> pd.DataFrame:
        shifted = resid.copy()
        # date_orig + lag_days = date_orig가 date 시점의 "lag_days일 전 잔차"로 붙을 날짜.
        shifted["date"] = shifted["date"] + pd.Timedelta(days=lag_days)
        shifted = shifted.rename(
            columns={
                "boarding_resid": f"boarding_resid_{suffix}",
                "alighting_resid": f"alighting_resid_{suffix}",
            }
        )
        return base.merge(shifted, on=["station_no", "time_slot", "date"], how="left")

    out = lag_join(joined, 1, "lag1d")
    out = lag_join(out, 7, "lag7d")
    return out


def op_a_spark(sdf):
    from pyspark.sql import functions as F

    # date_add()는 DateType을 반환한다. 원본 컬럼(TimestampType)과 타입이 섞이면 뒤의
    # lag 자기조인에서 타입 불일치로 매칭이 깨질 수 있어, 시작 시점에 DateType으로 통일한다.
    sdf = sdf.withColumn("date", F.to_date(F.col("date")))

    keys = ["station_no", "time_slot", "day_type"]
    lookup = sdf.groupBy(*keys).agg(
        F.avg("boarding").alias("avg_boarding"),
        F.avg("alighting").alias("avg_alighting"),
    )
    joined = sdf.join(lookup, on=keys, how="left")
    joined = joined.withColumn(
        "boarding_resid", F.col("boarding") - F.col("avg_boarding")
    ).withColumn("alighting_resid", F.col("alighting") - F.col("avg_alighting"))

    resid = joined.select("station_no", "time_slot", "date", "boarding_resid", "alighting_resid")

    def lag_join(base, lag_days: int, suffix: str):
        shifted = (
            resid.withColumn("date", F.date_add(F.col("date"), lag_days))
            .withColumnRenamed("boarding_resid", f"boarding_resid_{suffix}")
            .withColumnRenamed("alighting_resid", f"alighting_resid_{suffix}")
        )
        return base.join(shifted, on=["station_no", "time_slot", "date"], how="left")

    out = lag_join(joined, 1, "lag1d")
    out = lag_join(out, 7, "lag7d")
    return out


# ---------------------------------------------------------------------------
# OP-B: ratio_agg — (station_no, time_slot, day_type, direction)별
#       mean + count + 분위수(0.5, 0.9) 집계
#
# 원본 파일에는 day_type/dow 컬럼이 없어(집계 대상 컬럼만 최소로 들고 있는 산출물),
# date로부터 주중/주말을 직접 파생한다(토·일 = weekend). 요일유형 원본 정의(공휴일 포함
# day_type)와는 다른 근사치이지만, pandas·Spark 양쪽에 동일 규칙을 적용하므로 엔진 간
# 비교의 공정성에는 영향이 없다.
# ---------------------------------------------------------------------------


def _pandas_day_type(date_series: pd.Series) -> np.ndarray:
    dow = date_series.dt.dayofweek  # Mon=0 ... Sun=6
    return np.where(dow >= 5, "weekend", "weekday")


def op_b_pandas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["day_type"] = _pandas_day_type(df["date"])
    keys = ["station_no", "time_slot", "day_type", "direction"]
    grouped = df.groupby(keys)["congestion_raw_pct"]
    agg = grouped.agg(mean_pct="mean", cnt="count")
    q50 = grouped.quantile(0.5).rename("p50_pct")
    q90 = grouped.quantile(0.9).rename("p90_pct")
    out = agg.join(q50).join(q90).reset_index()
    return out


def op_b_spark(sdf):
    from pyspark.sql import functions as F

    # Spark dayofweek(): Sun=1 ... Sat=7 (pandas와 인코딩은 다르지만 토·일=weekend라는
    # 실제 판정 결과는 동일하다).
    sdf = sdf.withColumn("dow", F.dayofweek(F.col("date")))
    sdf = sdf.withColumn(
        "day_type", F.when(F.col("dow").isin(1, 7), "weekend").otherwise("weekday")
    )
    keys = ["station_no", "time_slot", "day_type", "direction"]
    out = sdf.groupBy(*keys).agg(
        F.mean("congestion_raw_pct").alias("mean_pct"),
        F.count("congestion_raw_pct").alias("cnt"),
        F.expr("percentile(congestion_raw_pct, array(0.5, 0.9))").alias("_pctl"),
    )
    out = out.withColumn("p50_pct", F.col("_pctl")[0]).withColumn("p90_pct", F.col("_pctl")[1])
    return out.drop("_pctl", "dow")


# ---------------------------------------------------------------------------
# OP-C: long_pivot — 롱포맷(direction=boarding/alighting) -> 와이드 pivot
# ---------------------------------------------------------------------------

PIVOT_INDEX = ["date", "line", "station_no", "time_slot"]


def op_c_pandas(df: pd.DataFrame) -> pd.DataFrame:
    out = df.pivot_table(
        index=PIVOT_INDEX, columns="direction", values="passengers", aggfunc="first"
    )
    out = out.reset_index()
    out.columns.name = None
    return out


def op_c_spark(sdf, pivot_values: list[str] | None = None):
    from pyspark.sql import functions as F

    grouped = sdf.groupBy(*PIVOT_INDEX)
    pivoted = (
        grouped.pivot("direction", pivot_values) if pivot_values else grouped.pivot("direction")
    )
    return pivoted.agg(F.first("passengers"))


OPS = {
    "A": (op_a_pandas, op_a_spark),
    "B": (op_b_pandas, op_b_spark),
    "C": (op_c_pandas, op_c_spark),
}
