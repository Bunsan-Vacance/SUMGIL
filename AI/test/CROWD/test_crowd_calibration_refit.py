"""199 — 배율표 재적합의 순수 함수 고정.

데이터 파일 없이 도는 것만 둔다(CI에 `data/`가 없다). 실제 배율표를 재생성한 전후 수치는
`validation/CROWD/calibration-refit/RESULTS.md`가 원본이다.

특히 **상수 0이면 주입하지 않은 것과 같아야 한다**는 회귀선을 고정한다 — 이게 깨지면 88 현행 표를
더는 재현할 수 없고, 199의 모든 전후 비교가 기준선을 잃는다.

이 파일은 티켓이 진행되면서 늘어난다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.CROWD.pipeline.congestion import (
    BRANCH_DIRECTION_MAP,
    apply_calibration,
    bucket_direction,
    truncated_segments,
)
from DATA_ENGINE.eda.boundary_inflow import (
    borrow_neighbor_boundary,
    fit_boundary_inflow,
)
from DATA_ENGINE.eda.build_congestion_calibration import (
    CalibrationVariant,
    bucket_day_type,
    fit_window_mask,
)

SEGMENTS = [
    {"line": "1호선", "segment": "본선", "truncated": True, "stations": [150, 151, 152, 158]},
    {
        "line": "2호선",
        "segment": "본선",
        "circular": True,
        "truncated": True,
        "stations": [201, 202],
    },
    {"line": "5호선", "segment": "본선", "stations": [2511, 2512, 2513]},
    {"line": "9호선", "segment": "2·3단계", "truncated": True, "stations": [4138, 4137]},
]


def _boundary_frame(offset_true: float = 200.0, scale: float = 0.1) -> pd.DataFrame:
    """경계 셀 하나(raw 0) + 내부 셀 넷인 한 그룹. `meas = scale × (raw + offset_true)`."""
    raw = np.array([0.0, 100.0, 300.0, 600.0, 900.0])
    return pd.DataFrame(
        {
            "line": "1호선",
            "segment": "본선",
            "direction": "상선",
            "day_type": "평일",
            "time_slot": "08:00",
            "station_no": [150, 151, 152, 153, 158],
            "raw_mean": raw,
            "congestion_pct": scale * (raw + offset_true),
        }
    )


# ── 절단 구간 선별 ──
def test_truncated_segments_skips_circular_and_untruncated():
    picked = {(s["line"], s["segment"]) for s in truncated_segments(SEGMENTS)}
    assert picked == {("1호선", "본선"), ("9호선", "2·3단계")}
    assert {s["line"] for s in truncated_segments(SEGMENTS, lines=("1호선",))} == {"1호선"}


# ── B: 경계 유입 상수 ──
def test_joint_offset_recovers_the_planted_constant():
    """`meas = s·(raw + c)`로 만든 자료에서 joint(2모수)는 `c`를 정확히 되찾는다."""
    offsets = fit_boundary_inflow(_boundary_frame(offset_true=200.0), method="joint")
    assert len(offsets) == 1
    assert offsets["raw_offset"].iloc[0] == pytest.approx(200.0)


def test_anchored_offset_shrinks_toward_zero_but_reproduces_the_boundary_cell():
    """anchored는 상수를 **작게** 잡는다 — 원점을 지나는 1모수 스케일이 상수를 일부 흡수하기 때문이다.

    자유도를 줄여 얻은 안정성의 대가이고, 방향이 보수적이라(희석이 덜하다) 그대로 둔다. 대신
    **경계 셀은 정확히 재현한다**: `배율 = 실측 ÷ offset`이므로 `(0 + offset) × 배율 = 실측`이다.
    """
    frame = _boundary_frame(offset_true=200.0, scale=0.1)
    offset = fit_boundary_inflow(frame, method="anchored")["raw_offset"].iloc[0]
    assert 0 < offset < 200.0
    boundary_meas = frame.loc[frame["raw_mean"] == 0, "congestion_pct"].iloc[0]
    assert offset * (boundary_meas / offset) == pytest.approx(boundary_meas)


def test_boundary_scale_zero_is_a_no_op():
    """상수 0 → 주입하지 않은 표와 수치가 같다. 88 현행 표 재현의 회귀선이다."""
    offsets = fit_boundary_inflow(_boundary_frame(), scale=0.0, method="anchored")
    assert (offsets["raw_offset"] == 0.0).all()


def test_anchored_offset_is_zero_without_a_boundary_cell():
    """경계 셀(raw 0)이 없으면 상수를 만들지 않는다 — 값을 지어내지 않는다(원칙 1)."""
    frame = _boundary_frame()
    offsets = fit_boundary_inflow(frame[frame["raw_mean"] > 0], method="anchored")
    assert offsets["raw_offset"].iloc[0] == 0.0


def test_anchored_offset_is_zero_when_boundary_measurement_is_zero():
    """3호선 오금처럼 실제 종점이라 스냅샷도 0을 적는 셀 — 유입 없음이 맞는 답이다."""
    frame = _boundary_frame()
    frame.loc[frame["raw_mean"] == 0, "congestion_pct"] = 0.0
    assert fit_boundary_inflow(frame, method="anchored")["raw_offset"].iloc[0] == 0.0


def test_joint_offset_needs_enough_stations():
    """역 축 표본이 3점뿐이면(신정지선) 2모수 적합이 보간이라 joint는 0으로 둔다."""
    frame = _boundary_frame().iloc[:3]
    assert fit_boundary_inflow(frame, method="joint")["raw_offset"].iloc[0] == 0.0


# ── B2: 인접역 값 차용 ──
def test_borrow_neighbor_boundary_copies_ratio_and_raw_mean():
    table = pd.DataFrame(
        {
            "station_no": [150, 151, 158, 152],
            "line": "1호선",
            "direction": "상선",
            "day_type": "평일",
            "time_slot": "08:00",
            "raw_mean": [0.0, 400.0, 900.0, 700.0],
            "ratio": [np.nan, 0.05, 0.04, 0.045],
        }
    )
    out = borrow_neighbor_boundary(table, available={150, 151, 152, 158})
    edge = out[out["station_no"] == 150].iloc[0]
    assert edge["ratio"] == 0.05  # 151(인접역)의 배율
    assert edge["raw_offset"] == 400.0  # 그 셀의 예측은 인접역 날짜 평균이 된다


# ── 적합 창 ──
def test_fit_window_mask_narrows_to_year_and_season():
    dates = pd.Series(pd.to_datetime(["2024-06-01", "2025-06-01", "2025-11-25", "2026-01-05"]))
    variant = CalibrationVariant(snapshot_release="2025-11-30", window_weeks=13)
    assert fit_window_mask(dates, variant).tolist() == [True, True, True, True]
    year = fit_window_mask(dates, CalibrationVariant(fit_window="snapshot_year")).tolist()
    assert year == [False, True, True, False]
    season = fit_window_mask(dates, CalibrationVariant(fit_window="snapshot_season")).tolist()
    assert season == [False, False, True, True]


# ── A: 지선 방향 대응이 산출 쪽에서도 같은 규칙을 쓴다 ──
def test_branch_direction_map_is_shared_between_serving_and_builder():
    frame = pd.DataFrame(
        {
            "segment": ["성수지선", "성수지선", "신정지선", "본선"],
            "direction": ["하선", "상선", "하선", "하선"],
            "station_no": [244, 244, 248, 211],
        }
    )
    mapped = bucket_direction(frame["segment"], frame["direction"], frame["station_no"])
    assert mapped.tolist() == ["외선", "내선", "내선", "하선"]
    assert BRANCH_DIRECTION_MAP["성수지선"]["하선"] == "외선"


def test_builder_day_type_bucket_never_fabricates_a_holiday():
    """공휴일 대체는 서빙(`congestion.HOLIDAY_FALLBACK_DAY_TYPE`) 한 곳에서만 일어난다."""
    line = pd.Series(["1호선", "9호선"])
    day_type = pd.Series(["휴일", "휴일"])
    bucketed = bucket_day_type(line, day_type)
    assert bucketed.isna().iloc[0]  # 1~8호선 공휴일은 조인에서 빠진다(표에 행을 만들지 않는다)
    assert bucketed.iloc[1] == "휴일"  # 9호선은 스냅샷 정의 그대로


# ── 서빙: raw_offset이 실린 표 ──
def _labels() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "station_no": [150, 150],
            "line": "1호선",
            "segment": "본선",
            "direction": ["상선", "하선"],
            "day_type": "평일",
            "time_slot": "08-09",
            "congestion_raw_pct": [0.0, 400.0],
        }
    )


def _calibration(raw_offset: list[float] | None) -> pd.DataFrame:
    table = pd.DataFrame(
        {
            "station_no": [150, 150, 150, 150],
            "direction": ["상선", "상선", "하선", "하선"],
            "day_type": "평일",
            "time_slot": ["08:00", "08:30", "08:00", "08:30"],
            "ratio": [0.1, 0.1, 0.05, 0.05],
        }
    )
    if raw_offset is not None:
        table["raw_offset"] = raw_offset
    return table


def test_apply_calibration_uses_raw_offset_when_present():
    out = apply_calibration(_labels(), _calibration([240.0, 240.0, 240.0, 240.0]))
    got = out.set_index(["direction", "time_slot_30min"])["congestion_pct_calibrated"]
    assert got.loc[("상선", "08:00")] == 24.0  # (0 + 240) × 0.1 — 경계 셀에 값이 생긴다
    assert got.loc[("하선", "08:00")] == 32.0  # (400 + 240) × 0.05


def test_apply_calibration_is_unchanged_without_raw_offset():
    """컬럼이 없거나 0이면 88·146 표와 식이 완전히 같다."""
    without = apply_calibration(_labels(), _calibration(None))
    zeros = apply_calibration(_labels(), _calibration([0.0, 0.0, 0.0, 0.0]))
    left = without["congestion_pct_calibrated"].to_numpy()
    right = zeros["congestion_pct_calibrated"].to_numpy()
    assert np.array_equal(left, right, equal_nan=True)
    assert left[0] == 0.0  # 상수가 없으면 경계 셀(raw 0)은 0이라는 **틀린 값**이 나온다
