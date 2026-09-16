"""197 — `to_congestion_table` 출력 클립 일관성 회귀 테스트.

배치가 재귀식 입력에는 0 클립을 적용하면서 출력 표의 `boarding_pred`·`alighting_pred`는 클립 전
원본을 그대로 실어 음수 인원이 새던 결함(`SERVING_CONTRACT.md` 5.1)의 재발을 막는다. 합성 예측
표로 (1) 출력 인원이 항상 0 이상인지, (2) `pred_clipped`가 클립된 행만 True인지, (3) `congestion_pct`가
클립된 입력으로 계산됐는지(클립 전 값과 다름), (4) `OUTPUT_COLS`와 실제 출력 컬럼이 일치하는지를 본다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.CROWD.pipeline.batch_predict import OUTPUT_COLS, to_congestion_table
from app.CROWD.pipeline.congestion import apply_calibration, recursive_congestion

CAPACITY = {"car_capacity": 160, "cars_per_train": {"1호선": 10}}
STATIONS = [150, 151, 158]  # 150: 승차 음수, 151: 하차 음수, 158: 둘 다 정상(클립 없음)


def _predicted() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Timestamp("2025-10-03"),
            "station_no": STATIONS,
            "station_name": ["서울역", "시청", "청량리"],
            "line": "1호선",
            "time_slot": "08-09",
            "day_type": "평일",
            "boarding": [300.0, 100.0, 80.0],
            "alighting": [0.0, 100.0, 30.0],
            "boarding_pred": [-50.0, 120.0, 80.0],  # 150만 음수
            "alighting_pred": [10.0, -5.0, 30.0],  # 151만 음수
            "boarding_lookup": [280.0, 110.0, 75.0],
            "alighting_lookup": [5.0, 90.0, 28.0],
        }
    )


def _calibration(stations: list[int]) -> pd.DataFrame:
    rows = []
    for s in stations:
        for d in ("하선", "상선"):
            for t in ("08:00", "08:30"):
                rows.append(
                    {
                        "station_no": s,
                        "direction": d,
                        "day_type": "평일",
                        "time_slot": t,
                        "ratio": 0.25,
                    }
                )
    return pd.DataFrame(rows)


def _segments() -> list[dict]:
    return [{"line": "1호선", "segment": "본선", "stations": STATIONS}]


def _recompute_congestion_pct(
    frame_with_boarding_alighting: pd.DataFrame, cal: pd.DataFrame
) -> pd.DataFrame:
    """`to_congestion_table`과 같은 방식(재귀식 → day_type 조인 → 배율)으로 독립 재계산한다."""
    raw = recursive_congestion(frame_with_boarding_alighting, _segments(), CAPACITY)
    day_type = frame_with_boarding_alighting[["date", "station_no", "day_type"]].drop_duplicates(
        ["date", "station_no"]
    )
    raw = raw.merge(day_type, on=["date", "station_no"], how="left")
    return apply_calibration(raw, cal)


@pytest.fixture
def table() -> pd.DataFrame:
    return to_congestion_table(
        _predicted(), _segments(), CAPACITY, _calibration(STATIONS), [50.0, 100.0]
    )


def test_negative_predictions_are_clipped_in_output(table):
    assert (table["boarding_pred"] >= 0).all()
    assert (table["alighting_pred"] >= 0).all()


def test_clipped_rows_are_flagged_true(table):
    for station in (150, 151):
        rows = table[table["station_no"] == station]
        assert rows["pred_clipped"].all(), station


def test_rows_without_negative_predictions_are_not_flagged(table):
    rows = table[table["station_no"] == 158]
    assert not rows["pred_clipped"].any()


def test_congestion_pct_matches_clipped_input_not_raw(table):
    predicted = _predicted()
    cal = _calibration(STATIONS)

    # 클립된 입력으로 재계산 — to_congestion_table의 congestion_pct와 같아야 한다.
    clipped = predicted.copy()
    for t in ("boarding", "alighting"):
        clipped[t] = np.clip(clipped[f"{t}_pred"].to_numpy(dtype=float), 0.0, None)
    cal_clipped = _recompute_congestion_pct(clipped, cal)

    merged = table.merge(
        cal_clipped[["station_no", "direction", "time_slot_30min", "congestion_pct_calibrated"]],
        on=["station_no", "direction", "time_slot_30min"],
        how="left",
    )
    assert merged["congestion_pct"].to_numpy() == pytest.approx(
        merged["congestion_pct_calibrated"].to_numpy()
    )

    # 클립 전(원본) 입력으로 계산하면 다른 값이 나온다 — 클립이 실제로 결과를 바꾼다는 근거.
    # 기존 actual boarding/alighting 컬럼은 버리고 예측값을 그 자리에 넣는다(중복 컬럼 방지).
    unclipped = predicted.drop(columns=["boarding", "alighting"]).rename(
        columns={"boarding_pred": "boarding", "alighting_pred": "alighting"}
    )
    cal_unclipped = _recompute_congestion_pct(unclipped, cal)
    merged_unclipped = table.merge(
        cal_unclipped[["station_no", "direction", "time_slot_30min", "congestion_pct_calibrated"]],
        on=["station_no", "direction", "time_slot_30min"],
        how="left",
    )
    assert not np.allclose(
        merged_unclipped["congestion_pct"].to_numpy(),
        merged_unclipped["congestion_pct_calibrated"].to_numpy(),
    )


def test_output_columns_match_output_cols(table):
    assert list(table.columns) == OUTPUT_COLS
