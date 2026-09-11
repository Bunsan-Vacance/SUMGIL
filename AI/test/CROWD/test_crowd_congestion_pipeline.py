"""app/CROWD/pipeline/{congestion,calendar,predictor}.py — 서빙 배치의 순수 함수."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.CROWD.pipeline.calendar import attach_calendar
from app.CROWD.pipeline.congestion import (
    apply_calibration,
    bucket_day_type,
    circular_path_masks,
    directional_loads,
    grade,
    hour_bucket_to_30min_slots,
    recursive_congestion,
)
from app.CROWD.pipeline.lookup import DayTypeLookupBaseline
from app.CROWD.pipeline.predictor import LookupPredictor, Predictor, build_predictor

CAPACITY = {"car_capacity": 160, "cars_per_train": {"L": 10}}


# ── congestion ──
def test_directional_loads_conserve_boardings_and_end_empty():
    b = np.array([100.0, 50.0, 0.0, 0.0])
    a = np.array([0.0, 0.0, 60.0, 90.0])
    up, down = directional_loads(b, a)
    # 모두 오름차순으로 가는 OD → 마지막 링크 이후는 0, 내림차순 통과량은 0
    assert up[0] == pytest.approx(100.0)
    assert up[-1] == pytest.approx(0.0)
    assert np.allclose(down, 0.0)


def test_circular_masks_shape_and_shortest_path_choice():
    asc, desc = circular_path_masks(4)
    assert asc.shape == desc.shape == (4, 4, 4)
    # i=0 → j=1 은 오름차순(거리1), 링크 0만 지난다
    assert asc[0, 0, 1] and not asc[1, 0, 1] and not desc[:, 0, 1].any()


def test_recursive_congestion_outputs_both_directions_per_station():
    panel = pd.DataFrame(
        {
            "date": pd.Timestamp("2025-01-01"),
            "station_no": [1, 2, 3],
            "time_slot": "08-09",
            "boarding": [300.0, 100.0, 0.0],
            "alighting": [0.0, 100.0, 300.0],
        }
    )
    seg = {"line": "L", "segment": "본선", "stations": [1, 2, 3]}
    out = recursive_congestion(panel, [seg], CAPACITY)
    assert set(out["direction"]) == {"상선", "하선"}
    assert len(out) == 6
    assert (out["train_capacity"] == 1600).all()
    assert out["congestion_raw_pct"].max() > 0


def test_hour_bucket_edges():
    assert hour_bucket_to_30min_slots("~06") == ["05:30"]
    assert hour_bucket_to_30min_slots("24~") == ["00:00", "00:30"]
    assert hour_bucket_to_30min_slots("08-09") == ["08:00", "08:30"]


def test_bucket_day_type_line9_vs_others():
    line = pd.Series(["9호선", "9호선", "2호선", "2호선"])
    dt = pd.Series(["토요일", "휴일", "토요일", "휴일"])
    out = bucket_day_type(line, dt)
    assert list(out[:3]) == ["휴일", "휴일", "토요일"]
    assert pd.isna(out[3])  # 1~8호선 공휴일은 스냅샷 구간이 없다 → 조인에서 빠진다


def test_apply_calibration_multiplies_ratio_and_leaves_missing_nan():
    labels = pd.DataFrame(
        {
            "date": [pd.Timestamp("2025-01-06")] * 2,
            "station_no": [1, 1],
            "line": ["L", "L"],
            "direction": ["하선", "상선"],
            "time_slot": ["08-09", "08-09"],
            "day_type": ["평일", "평일"],
            "congestion_raw_pct": [200.0, 100.0],
        }
    )
    cal = pd.DataFrame(
        {
            "station_no": [1, 1],
            "direction": ["하선", "하선"],
            "day_type": ["평일", "평일"],
            "time_slot": ["08:00", "08:30"],
            "ratio": [0.5, 0.25],
        }
    )
    out = apply_calibration(labels, cal)
    assert len(out) == 4  # 2행 × 30분 2슬롯
    down = out[out["direction"] == "하선"].set_index("time_slot_30min")["congestion_pct_calibrated"]
    assert down["08:00"] == pytest.approx(100.0) and down["08:30"] == pytest.approx(50.0)
    assert out[out["direction"] == "상선"]["congestion_pct_calibrated"].isna().all()


def test_grade_thresholds_and_nan():
    g = grade(pd.Series([10.0, 50.0, 99.0, 100.0, np.nan]), [50, 100])
    assert list(g[:4]) == [0.0, 1.0, 1.0, 2.0]
    assert np.isnan(g[4])


# ── calendar ──
def test_attach_calendar_weekend_and_weekday_holiday_only():
    frame = pd.DataFrame(
        {"date": pd.to_datetime(["2025-01-01", "2025-01-04", "2025-01-05", "2025-01-06"])}
    )
    holidays = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-01-04", "2025-01-05"]),
            "is_holiday": [True, True, True],
        }
    )
    out = attach_calendar(frame, holidays)
    assert list(out["day_type"]) == ["휴일", "토요일", "일요일", "평일"]
    assert list(out["weekday_ko"]) == ["수", "토", "일", "월"]


# ── predictor ──
def _panel():
    rows = []
    for d in range(3):
        for s in (1, 2):
            rows.append(
                {
                    "date": pd.Timestamp("2025-01-06") + pd.Timedelta(days=d),
                    "station_no": s,
                    "time_slot": "08-09",
                    "day_type": "평일",
                    "boarding": 100.0 * s + d,
                    "alighting": 50.0 * s,
                }
            )
    return pd.DataFrame(rows)


def test_lookup_predictor_conforms_to_protocol_and_roundtrips(tmp_path):
    panel = _panel()
    p = LookupPredictor.fit(panel)
    assert isinstance(p, Predictor)
    out = p.predict(panel, [])
    assert list(out.columns) == [
        "date",
        "station_no",
        "time_slot",
        "boarding_lookup",
        "boarding_pred",
        "alighting_lookup",
        "alighting_pred",
    ]
    assert out.loc[out["station_no"] == 1, "boarding_pred"].iloc[0] == pytest.approx(101.0)
    path = p.lookup.save(tmp_path / "lookup.parquet")
    loaded = build_predictor("lookup", lookup_path=path)
    pd.testing.assert_frame_equal(loaded.predict(panel, []), out)


def test_build_predictor_rejects_unknown_and_llm_is_unconfigured():
    with pytest.raises(ValueError):
        build_predictor("nope")
    llm = build_predictor("llm")
    with pytest.raises(NotImplementedError):
        llm.predict(_panel(), [])


def test_lookup_predictor_needs_source():
    with pytest.raises(ValueError):
        build_predictor("lookup")


def test_lookup_class_is_reused():
    assert isinstance(LookupPredictor.fit(_panel()).lookup, DayTypeLookupBaseline)
