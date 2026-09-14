"""146 — 혼잡도 산출 기준 정비(공휴일 배율 대체 · 2호선 지선 방향 대응 · 1호선 절단면 표시).

검증 근거 수치는 `validation/CROWD/congestion-criteria-check/RESULTS.md`에 있다. 여기서는 그 결론이
코드에 그대로 들어갔는지, 그리고 **대체가 값을 지어내지 않고 상태로 노출되는지**(원칙 8)를 본다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.CROWD.pipeline.batch_predict import to_congestion_table
from app.CROWD.pipeline.congestion import (
    BRANCH_DIRECTION_MAP,
    apply_calibration,
    bucket_day_type,
    truncated_boundary_cells,
)

CAPACITY = {"car_capacity": 160, "cars_per_train": {"1호선": 10, "2호선": 10}}


def _labels(rows: list[dict]) -> pd.DataFrame:
    """`recursive_congestion` 출력 모양의 최소 프레임."""
    base = {
        "date": pd.Timestamp("2025-10-03"),
        "time_slot": "08-09",
        "congestion_raw_pct": 200.0,
        "segment": "본선",
    }
    return pd.DataFrame([{**base, **r} for r in rows])


def _calibration(rows: list[dict]) -> pd.DataFrame:
    base = {"day_type": "일요일", "time_slot": "08:00", "ratio": 0.25}
    return pd.DataFrame([{**base, **r} for r in rows])


# ── 공휴일 배율 대체 ──
def test_bucket_day_type_holiday_fallback_is_opt_in():
    line = pd.Series(["2호선", "2호선", "9호선"])
    day_type = pd.Series(["휴일", "토요일", "휴일"])
    assert pd.isna(bucket_day_type(line, day_type)[0])  # 기본값은 대체하지 않는다
    filled = bucket_day_type(line, day_type, holiday_fallback="일요일")
    assert list(filled) == ["일요일", "토요일", "휴일"]


def test_holiday_row_borrows_sunday_ratio_and_is_flagged():
    labels = _labels(
        [
            {"station_no": 201, "line": "2호선", "direction": "내선", "day_type": "휴일"},
            {"station_no": 201, "line": "2호선", "direction": "내선", "day_type": "일요일"},
        ]
    )
    cal = _calibration([{"station_no": 201, "direction": "내선"}])
    out = apply_calibration(labels, cal)
    holiday = out[(out["day_type"] == "휴일") & (out["time_slot_30min"] == "08:00")].iloc[0]
    sunday = out[(out["day_type"] == "일요일") & (out["time_slot_30min"] == "08:00")].iloc[0]
    assert holiday["congestion_pct_calibrated"] == pytest.approx(
        sunday["congestion_pct_calibrated"]
    )
    assert bool(holiday["calibration_fallback"]) and not bool(sunday["calibration_fallback"])
    assert holiday["day_type"] == "휴일"  # 원본 라벨은 바꾸지 않는다


def test_holiday_fallback_off_reproduces_pre_146_behaviour():
    labels = _labels(
        [{"station_no": 201, "line": "2호선", "direction": "내선", "day_type": "휴일"}]
    )
    cal = _calibration([{"station_no": 201, "direction": "내선"}])
    out = apply_calibration(labels, cal, holiday_fallback=None)
    assert out["congestion_pct_calibrated"].isna().all()
    assert not out["calibration_fallback"].any()


def test_line9_unaffected_by_holiday_fallback():
    labels = _labels(
        [{"station_no": 4126, "line": "9호선", "direction": "하선", "day_type": "휴일"}]
    )
    cal = _calibration([{"station_no": 4126, "direction": "하선", "day_type": "휴일"}])
    out = apply_calibration(labels, cal)
    assert out["congestion_pct_calibrated"].iloc[0] == pytest.approx(50.0)
    assert not out["calibration_fallback"].any()  # 9호선은 원래 휴일 배율이 있다 — 대체가 아니다


def test_missing_station_stays_nan_even_with_fallback():
    """결번 역(배율표에 아예 없는 역)은 대체 요일유형으로도 값이 안 나온다 — 상태도 fallback이 아니다."""
    labels = _labels(
        [{"station_no": 999, "line": "3호선", "direction": "하선", "day_type": "휴일"}]
    )
    cal = _calibration([{"station_no": 201, "direction": "내선"}])
    out = apply_calibration(labels, cal)
    assert out["congestion_pct_calibrated"].isna().all()
    assert not out["calibration_fallback"].any()


# ── 2호선 지선 방향 대응 ──
def test_branch_direction_map_is_opposite_between_two_branches():
    """출퇴근 비대칭으로 확정한 대응 — 두 지선이 서로 반대다(RESULTS.md 3절)."""
    assert BRANCH_DIRECTION_MAP["성수지선"]["상선"] == "내선"
    assert BRANCH_DIRECTION_MAP["신정지선"]["상선"] == "외선"


def test_branch_rows_join_on_mapped_direction():
    labels = _labels(
        [
            {
                "station_no": 244,
                "line": "2호선",
                "direction": "상선",
                "day_type": "평일",
                "segment": "성수지선",
            },
            {
                "station_no": 247,
                "line": "2호선",
                "direction": "상선",
                "day_type": "평일",
                "segment": "신정지선",
            },
        ]
    )
    cal = _calibration(
        [
            {"station_no": 244, "direction": "내선", "day_type": "평일"},
            {"station_no": 247, "direction": "외선", "day_type": "평일"},
        ]
    )
    out = apply_calibration(labels, cal)
    got = out[out["time_slot_30min"] == "08:00"].set_index("station_no")
    assert got.loc[244, "congestion_pct_calibrated"] == pytest.approx(50.0)
    assert got.loc[247, "congestion_pct_calibrated"] == pytest.approx(50.0)
    assert list(got["direction"]) == ["상선", "상선"]  # 출력 라벨은 재귀식 것 그대로


def test_branch_junction_station_keeps_its_own_direction():
    """성수(211)·신도림(234)은 본선 세그먼트가 이미 내선/외선으로 값을 낸다 — 지선 행을 접으면 중복이다."""
    labels = _labels(
        [
            {
                "station_no": 211,
                "line": "2호선",
                "direction": "상선",
                "day_type": "평일",
                "segment": "성수지선",
            }
        ]
    )
    cal = _calibration([{"station_no": 211, "direction": "내선", "day_type": "평일"}])
    out = apply_calibration(labels, cal)
    assert out["congestion_pct_calibrated"].isna().all()


# ── 1호선 절단면 ──
def test_truncated_boundary_cells_are_the_two_terminal_links():
    segments = [
        {"line": "1호선", "segment": "본선", "truncated": True, "stations": [150, 151, 158]},
        {"line": "8호선", "segment": "본선", "stations": [2810, 2811]},  # 절단 아님
        {
            "line": "3호선",
            "segment": "본선",
            "truncated": True,
            "stations": [309, 310],
        },  # 스코프 밖
    ]
    # 146의 스코프는 1호선이었다. 199가 기본값을 전 절단 구간(`lines=None`)으로 넓혔으므로
    # 1호선만 보려면 명시해야 한다 — 두 동작을 다 고정해 둔다.
    assert truncated_boundary_cells(segments, lines=("1호선",)) == {(158, "하선"), (150, "상선")}
    assert truncated_boundary_cells(segments) == {
        (158, "하선"),
        (150, "상선"),
        (310, "하선"),
        (309, "상선"),
    }


def test_data_status_priority_marks_fallback_then_truncation():
    """같은 표에서 ok · calibration_fallback · segment_truncated · no_calibration이 우선순위대로 붙는다."""
    stations = [150, 151, 158]
    predicted = pd.DataFrame(
        {
            "date": pd.Timestamp("2025-10-03"),
            "station_no": stations,
            "station_name": ["서울역", "시청", "청량리"],
            "line": "1호선",
            "time_slot": "08-09",
            "day_type": "휴일",
            "boarding": [300.0, 100.0, 0.0],
            "alighting": [0.0, 100.0, 300.0],
            "boarding_pred": [300.0, 100.0, 0.0],
            "alighting_pred": [0.0, 100.0, 300.0],
            "boarding_lookup": [300.0, 100.0, np.nan],
            "alighting_lookup": [0.0, 100.0, np.nan],
        }
    )
    segments = [{"line": "1호선", "segment": "본선", "truncated": True, "stations": stations}]
    cal = _calibration(
        [
            {"station_no": s, "direction": d, "time_slot": t}
            for s in stations
            for d in ("하선", "상선")
            for t in ("08:00", "08:30")
        ]
    )
    # 실제 배율표에서 재차가 구조적으로 0인 셀은 배율이 산출되지 않는다(분모 0) — 서울역 상선이 그렇다.
    # 시청 상선은 절단과 무관한 결측이라 no_calibration으로 갈라져야 한다.
    cal.loc[(cal["station_no"].isin([150, 151])) & (cal["direction"] == "상선"), "ratio"] = np.nan

    table = to_congestion_table(predicted, segments, CAPACITY, cal, [50.0, 100.0])
    status = table.set_index(["station_no", "direction", "time_slot_30min"])["data_status"]
    assert status.loc[(158, "하선", "08:00")] == "no_lookup"  # lookup이 없으면 그게 먼저다
    assert status.loc[(150, "상선", "08:00")] == "segment_truncated"
    assert status.loc[(151, "상선", "08:00")] == "no_calibration"
    assert status.loc[(150, "하선", "08:00")] == "calibration_fallback"
    assert set(table["data_status"]) <= {
        "ok",
        "calibration_fallback",
        "no_lookup",
        "segment_truncated",
        "no_calibration",
    }


def test_data_status_without_fallback_collapses_to_no_calibration():
    """`holiday_fallback=None`이면 146 이전 동작 — 공휴일 셀이 전부 no_calibration으로 돌아간다."""
    stations = [150, 151, 158]
    predicted = pd.DataFrame(
        {
            "date": pd.Timestamp("2025-10-03"),
            "station_no": stations,
            "station_name": ["서울역", "시청", "청량리"],
            "line": "1호선",
            "time_slot": "08-09",
            "day_type": "휴일",
            "boarding": [300.0, 100.0, 0.0],
            "alighting": [0.0, 100.0, 300.0],
            "boarding_pred": [300.0, 100.0, 0.0],
            "alighting_pred": [0.0, 100.0, 300.0],
            "boarding_lookup": [300.0, 100.0, 0.0],
            "alighting_lookup": [0.0, 100.0, 300.0],
        }
    )
    segments = [{"line": "1호선", "segment": "본선", "truncated": True, "stations": stations}]
    cal = _calibration(
        [
            {"station_no": s, "direction": d, "time_slot": t}
            for s in stations
            for d in ("하선", "상선")
            for t in ("08:00", "08:30")
        ]
    )
    table = to_congestion_table(
        predicted, segments, CAPACITY, cal, [50.0, 100.0], holiday_fallback=None
    )
    assert set(table["data_status"]) == {"no_calibration", "segment_truncated"}
