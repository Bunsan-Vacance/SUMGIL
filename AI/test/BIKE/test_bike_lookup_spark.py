from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pyspark = pytest.importorskip("pyspark")

from app.BIKE.pipeline.lookup import (  # noqa: E402
    STOCK_KEYS,
    STOCK_NEEDED_COLS,
    StockProfileBaseline,
)


def _make_synthetic_file(path) -> None:
    """평일(화)·토요일·일요일 세 조합 + horizon 필터·NaN 제외 대상을 섞는다.

    DATA_ENGINE/spark/jobs/bike_avg_baseline.py의 합성 데이터와 같은 케이스다 —
    `fit_streaming_spark()`가 그 로직을 그대로 옮긴 것이므로 같은 방식으로 검증한다.
    """
    rows = [
        {
            "od_station_id": "ST-A",
            "date": "2024-01-02",  # 화요일(평일)
            "slot_5m": 10,
            "stock_anchor_hour": 3.0,
            "is_empty_anchor": False,
            "is_full_anchor": False,
            "rack_count": 20.0,
            "horizon_min": 5,
        },
        {
            "od_station_id": "ST-A",
            "date": "2024-01-02",
            "slot_5m": 10,
            "stock_anchor_hour": 999.0,  # horizon=10 — fit_streaming은 5만 쓰므로 제외돼야 함
            "is_empty_anchor": True,
            "is_full_anchor": True,
            "rack_count": 20.0,
            "horizon_min": 10,
        },
        {
            "od_station_id": "ST-A",
            "date": "2024-01-06",  # 토요일
            "slot_5m": 20,
            "stock_anchor_hour": 0.0,
            "is_empty_anchor": True,
            "is_full_anchor": False,
            "rack_count": 15.0,
            "horizon_min": 5,
        },
        {
            "od_station_id": "ST-B",
            "date": "2024-01-07",  # 일요일, stock_anchor_hour NaN — dropna 대상
            "slot_5m": 30,
            "stock_anchor_hour": np.nan,
            "is_empty_anchor": False,
            "is_full_anchor": False,
            "rack_count": 10.0,
            "horizon_min": 5,
        },
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
    df = pd.DataFrame(rows, columns=[*STOCK_NEEDED_COLS, "horizon_min"])
    df["date"] = pd.to_datetime(df["date"])
    df.to_parquet(path)


def test_fit_streaming_spark_matches_fit_streaming(tmp_path):
    """274 B안 — train.py --engine spark가 실제로 pandas와 같은 값을 내는지 확인한다."""
    path = tmp_path / "synthetic.parquet"
    _make_synthetic_file(path)

    pandas_result = StockProfileBaseline().fit_streaming([path]).table_
    spark_result = StockProfileBaseline().fit_streaming_spark([path]).table_

    left = pandas_result.set_index(STOCK_KEYS).sort_index()
    right = spark_result.set_index(STOCK_KEYS).sort_index()
    assert len(left) == len(right) == len(left.index.intersection(right.index))

    for col in ["exp_bikes", "p_empty", "p_full"]:
        a = left[col].to_numpy(dtype=float)
        b = right.loc[left.index, col].to_numpy(dtype=float)
        assert np.allclose(a, b), f"{col} 불일치: pandas={a} spark={b}"
