from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pyspark = pytest.importorskip("pyspark")

from DATA_ENGINE.spark.jobs.bike_avg_baseline import (
    STOCK_NEEDED_COLS,
    fit_pandas,
    fit_spark,
)
from DATA_ENGINE.spark.metrics import compare_frames
from DATA_ENGINE.spark.session import build_spark_session


@pytest.fixture(scope="module")
def spark():
    session = build_spark_session("test-bike-avg-baseline", cores="1", driver_memory="1g")
    yield session
    session.stop()


def _make_synthetic_file(path) -> None:
    """2024-01-02(화, 평일)·01-06(토)·01-07(일) 세 날짜 조합으로 dow_type 분기를 커버한다.

    horizon_min이 다른 행(중복 제거 대상)과 stock_anchor_hour가 NaN인 행(제외 대상)도
    섞어서 `fit_streaming()`의 필터 규칙이 Spark에서도 똑같이 적용되는지 확인한다.
    """
    rows = [
        # station A, 평일(화), horizon=5 — 정상 집계 대상
        {
            "od_station_id": "ST-A",
            "date": "2024-01-02",
            "slot_5m": 10,
            "stock_anchor_hour": 3.0,
            "is_empty_anchor": False,
            "is_full_anchor": False,
            "rack_count": 20.0,
            "horizon_min": 5,
        },
        # station A, 같은 슬롯이지만 horizon=10 — fit_streaming은 horizon=5만 쓰므로 제외돼야 함
        {
            "od_station_id": "ST-A",
            "date": "2024-01-02",
            "slot_5m": 10,
            "stock_anchor_hour": 999.0,
            "is_empty_anchor": True,
            "is_full_anchor": True,
            "rack_count": 20.0,
            "horizon_min": 10,
        },
        # station A, 토요일 — dow_type=1
        {
            "od_station_id": "ST-A",
            "date": "2024-01-06",
            "slot_5m": 20,
            "stock_anchor_hour": 0.0,
            "is_empty_anchor": True,
            "is_full_anchor": False,
            "rack_count": 15.0,
            "horizon_min": 5,
        },
        # station B, 일요일, stock_anchor_hour NaN — dropna 대상, 결과에 없어야 함
        {
            "od_station_id": "ST-B",
            "date": "2024-01-07",
            "slot_5m": 30,
            "stock_anchor_hour": np.nan,
            "is_empty_anchor": False,
            "is_full_anchor": False,
            "rack_count": 10.0,
            "horizon_min": 5,
        },
        # station B, 일요일 — dow_type=2, 정상 집계 대상
        {
            "od_station_id": "ST-B",
            "date": "2024-01-07",
            "slot_5m": 30,
            "stock_anchor_hour": 10.0,
            "is_empty_anchor": False,
            "is_full_anchor": True,
            "rack_count": 10.0,
            "horizon_min": 5,
        },
    ]
    df = pd.DataFrame(rows, columns=STOCK_NEEDED_COLS)
    df["date"] = pd.to_datetime(df["date"])
    df.to_parquet(path)


def test_fit_spark_matches_fit_pandas_on_synthetic_data(spark, tmp_path):
    path = tmp_path / "synthetic.parquet"
    _make_synthetic_file(path)

    pandas_result = fit_pandas([path])
    spark_result = fit_spark(spark, [path]).toPandas()

    result = compare_frames(
        pandas_result,
        spark_result,
        key_cols=["od_station_id", "dow_type", "time_slot"],
        value_cols=["exp_bikes", "p_empty", "p_full"],
    )
    assert result["rows_match"] is True
    assert result["max_abs_err"] == 0.0


def test_fit_spark_excludes_other_horizons_and_nan_stock(spark, tmp_path):
    path = tmp_path / "synthetic.parquet"
    _make_synthetic_file(path)

    result = fit_spark(spark, [path]).toPandas()

    # station A 화요일 슬롯은 horizon=5 값(3.0)만 반영돼야 한다 — horizon=10의 999.0이
    # 섞이면 exp_bikes가 크게 벗어난다.
    row = result[(result["od_station_id"] == "ST-A") & (result["dow_type"] == 0)]
    assert len(row) == 1
    assert row.iloc[0]["exp_bikes"] == 3.0

    # station B는 NaN 행 하나·정상 행 하나였다 — NaN은 빠지고 정상 값만 반영돼야 한다.
    row_b = result[result["od_station_id"] == "ST-B"]
    assert len(row_b) == 1
    assert row_b.iloc[0]["exp_bikes"] == 10.0
    assert row_b.iloc[0]["p_full"] == 1.0


def test_fit_spark_dow_type_saturday_and_sunday(spark, tmp_path):
    path = tmp_path / "synthetic.parquet"
    _make_synthetic_file(path)

    result = fit_spark(spark, [path]).toPandas()
    # ST-A는 평일(dow_type=0, time_slot=1)과 토요일(dow_type=1, time_slot=3) 둘 다 있다 —
    # station만으로 묶으면 한쪽이 가려지므로 (station, time_slot)으로 정확히 짚는다.
    saturday_row = result[(result["od_station_id"] == "ST-A") & (result["time_slot"] == 3)]
    weekday_row = result[(result["od_station_id"] == "ST-A") & (result["time_slot"] == 1)]
    sunday_row = result[result["od_station_id"] == "ST-B"]

    assert saturday_row.iloc[0]["dow_type"] == 1  # 2024-01-06은 토요일
    assert weekday_row.iloc[0]["dow_type"] == 0  # 2024-01-02는 화요일(평일)
    assert sunday_row.iloc[0]["dow_type"] == 2  # 2024-01-07은 일요일
