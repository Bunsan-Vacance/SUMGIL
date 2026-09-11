"""app/CROWD/pipeline/disaggregate.py — 1시간→30분→열차 분해의 질량 보존과 경계 처리."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.CROWD.pipeline.disaggregate import (
    allocate_to_trains,
    half_hour_shares,
    slot30_start_minutes,
    slots_in_order,
    split_hourly_to_30min,
)


def _calibration():
    # 강남(222) 평일 08시: 내선은 전반 60%, 외선은 전반 40% → 방향 평균 50/50
    rows = []
    for direction, a, b in (("내선", 0.6, 0.4), ("외선", 0.4, 0.6)):
        rows += [
            {
                "station_no": 222,
                "direction": direction,
                "day_type": "평일",
                "time_slot": "08:00",
                "ratio": a,
            },
            {
                "station_no": 222,
                "direction": direction,
                "day_type": "평일",
                "time_slot": "08:30",
                "ratio": b,
            },
        ]
    # 07시는 내선만 있고 70/30
    rows += [
        {
            "station_no": 222,
            "direction": "내선",
            "day_type": "평일",
            "time_slot": "07:00",
            "ratio": 0.35,
        },
        {
            "station_no": 222,
            "direction": "내선",
            "day_type": "평일",
            "time_slot": "07:30",
            "ratio": 0.15,
        },
        # ~06 은 05:30 하나
        {
            "station_no": 222,
            "direction": "내선",
            "day_type": "평일",
            "time_slot": "05:30",
            "ratio": 0.2,
        },
    ]
    return pd.DataFrame(rows)


def test_half_hour_shares_average_directions_and_sum_to_one():
    sh = half_hour_shares(_calibration()).set_index(["time_slot", "time_slot_30min"])["share"]
    assert sh[("08-09", "08:00")] == pytest.approx(0.5)
    assert sh[("07-08", "07:00")] == pytest.approx(0.7)
    assert sh[("07-08", "07:30")] == pytest.approx(0.3)
    assert sh[("~06", "05:30")] == pytest.approx(1.0)


def test_split_conserves_mass_and_leaves_missing_nan():
    panel = pd.DataFrame(
        {
            "date": pd.Timestamp("2025-03-03"),
            "station_no": [222, 222, 222],
            "day_type": "평일",
            "time_slot": ["07-08", "08-09", "10-11"],  # 10-11 은 배율표에 없다
            "boarding": [1000.0, 2000.0, 500.0],
            "alighting": [100.0, 200.0, 50.0],
        }
    )
    out = split_hourly_to_30min(panel, _calibration())
    assert len(out) == 6
    by_hour = out.groupby("time_slot")["boarding_30min_est"].sum()
    assert by_hour["07-08"] == pytest.approx(1000.0)
    assert by_hour["08-09"] == pytest.approx(2000.0)
    assert out.loc[out["time_slot"] == "10-11", "boarding_30min_est"].isna().all()
    first = out[(out["time_slot"] == "07-08") & (out["time_slot_30min"] == "07:00")]
    assert first["boarding_30min_est"].iloc[0] == pytest.approx(700.0)


def _timetable():
    # 08:00~08:29 슬롯: 08:02, 08:08, 08:14(6분 간격) / 08:30 슬롯: 08:44 (14분 → long)
    return pd.DataFrame(
        {
            "station_no": 222,
            "direction": "내선",
            "day_type": "평일",
            "train_id": ["T1", "T2", "T3", "T4", "T5"],
            "arrival_time": ["07:56", "08:02", "08:08", "08:14", "08:44"],
        }
    )


def test_allocate_shares_by_headway_and_conserves_slot_mass():
    loads = pd.DataFrame(
        {
            "date": pd.Timestamp("2025-03-03"),
            "station_no": 222,
            "direction": "내선",
            "day_type": "평일",
            "time_slot_30min": ["08:00", "08:30"],
            "onboard_30min_est": [1800.0, 900.0],
        }
    )
    out = allocate_to_trains(loads, _timetable())
    s1 = out[out["time_slot_30min"] == "08:00"]
    assert list(s1["train_id"]) == ["T2", "T3", "T4"]
    assert s1["load_est"].sum() == pytest.approx(1800.0)
    assert np.allclose(s1["share"], 1 / 3)  # 6분씩 균등
    assert not s1["headway_long"].any()
    s2 = out[out["time_slot_30min"] == "08:30"]
    assert list(s2["train_id"]) == ["T5"]
    assert s2["load_est"].iloc[0] == pytest.approx(900.0)
    assert s2["headway_long"].iloc[0]  # 30분 간격


def test_slot_without_trains_is_dropped_not_filled():
    loads = pd.DataFrame(
        {
            "date": pd.Timestamp("2025-03-03"),
            "station_no": 222,
            "direction": "내선",
            "day_type": "평일",
            "time_slot_30min": ["09:00"],
            "onboard_30min_est": [100.0],
        }
    )
    assert allocate_to_trains(loads, _timetable()).empty


def test_after_midnight_slots_fold_to_end_of_service_day():
    assert slot30_start_minutes("00:30") == 24 * 60 + 30
    assert slots_in_order()[0] == "05:30" and slots_in_order()[-1] == "00:30"
    assert len(slots_in_order()) == 39
