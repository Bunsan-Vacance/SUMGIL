"""app/CROWD/pipeline/lags.py — 일 단위·슬롯 단위 시차 피처."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.CROWD.pipeline.lags import (
    attach_day_lags,
    attach_slot_lag,
    day_lag_names,
    slot_lag_names,
)

SLOTS = ["~06", "06-07", "07-08"]


def _panel() -> pd.DataFrame:
    rows = []
    for day in (1, 2, 3, 8):  # 4일이 빠져 있다 — 위치 shift라면 틀리는 상황
        for i, slot in enumerate(SLOTS):
            rows.append(
                {
                    "date": pd.Timestamp(f"2025-01-{day:02d}"),
                    "station_no": 1,
                    "time_slot": slot,
                    "v": day * 10 + i,
                }
            )
    return pd.DataFrame(rows)


def test_day_lag_joins_by_calendar_date_not_row_position():
    out = attach_day_lags(_panel(), ["v"], day_lags=(1, 7))
    r = out.set_index(["date", "time_slot"])
    assert r.loc[(pd.Timestamp("2025-01-02"), "06-07"), "lag1d_v"] == 11
    assert r.loc[(pd.Timestamp("2025-01-08"), "~06"), "lag7d_v"] == 10
    # 1월 8일의 전날(7일)은 패널에 없다 → NaN (3일 값을 끌어오면 안 된다)
    assert np.isnan(r.loc[(pd.Timestamp("2025-01-08"), "~06"), "lag1d_v"])
    assert np.isnan(r.loc[(pd.Timestamp("2025-01-01"), "~06"), "lag1d_v"])
    assert len(out) == 12


def test_slot_lag_follows_given_order_and_first_slot_is_nan():
    out = attach_slot_lag(_panel(), ["v"], SLOTS)
    r = out.set_index(["date", "time_slot"])
    d = pd.Timestamp("2025-01-01")
    assert np.isnan(r.loc[(d, "~06"), "lag1s_v"])
    assert r.loc[(d, "06-07"), "lag1s_v"] == 10
    assert r.loc[(d, "07-08"), "lag1s_v"] == 11
    assert len(out) == 12


def test_names_match_attached_columns():
    p = _panel()
    assert day_lag_names(["v"], (1, 7)) == ["lag1d_v", "lag7d_v"]
    assert slot_lag_names(["v"]) == ["lag1s_v"]
    assert set(day_lag_names(["v"], (1, 7))) <= set(attach_day_lags(p, ["v"]).columns)
    assert set(slot_lag_names(["v"])) <= set(attach_slot_lag(p, ["v"], SLOTS).columns)


# ── 93 B′: 같은 요일유형 직전 날 ──
def _typed_panel() -> pd.DataFrame:
    # 2025-01-06(월)~01-13(월): 평일 5 + 토·일 + 다음 월. 12일(일)은 공휴일 취급으로 바꿔 둔다.
    rows = []
    for d in range(6, 14):
        ts = pd.Timestamp(f"2025-01-{d:02d}")
        dt = "평일" if ts.weekday() < 5 else ("토요일" if ts.weekday() == 5 else "일요일")
        rows.append({"date": ts, "station_no": 1, "time_slot": "07-08", "day_type": dt, "v": d})
    return pd.DataFrame(rows)


def test_same_day_type_lag_points_to_previous_same_type_day():
    from app.CROWD.pipeline.lags import attach_same_day_type_lag, same_day_type_lag_names

    out = attach_same_day_type_lag(_typed_panel(), ["v"]).set_index("date")
    assert same_day_type_lag_names(["v"]) == ["lagsd_v"]
    # 화(7)의 직전 평일은 월(6); 월(13)의 직전 평일은 금(10) — 전날(일)이 아니다
    assert out.loc["2025-01-07", "lagsd_v"] == 6
    assert out.loc["2025-01-13", "lagsd_v"] == 10
    assert out.loc["2025-01-13", "lagsd_gap_days"] == 3
    # 첫 토·일은 직전 같은 유형이 없다
    assert np.isnan(out.loc["2025-01-11", "lagsd_v"])
    assert np.isnan(out.loc["2025-01-12", "lagsd_v"])
    assert np.isnan(out.loc["2025-01-06", "lagsd_v"])


def test_same_day_type_lag_respects_max_gap_and_row_order():
    from app.CROWD.pipeline.lags import attach_same_day_type_lag

    p = _typed_panel()
    p.loc[p["date"] == "2025-01-12", "day_type"] = "휴일"
    # 같은 휴일이 3주 전에 하나 더 있으면 기본 max_gap 14일을 넘어 NaN, 넉넉히 주면 붙는다
    extra = p.iloc[[0]].copy()
    extra["date"] = pd.Timestamp("2024-12-20")
    extra["day_type"] = "휴일"
    extra["v"] = 99
    p = pd.concat([p, extra], ignore_index=True).sample(frac=1, random_state=0)  # 행 순서 뒤섞기
    out = attach_same_day_type_lag(p, ["v"]).set_index("date")
    assert np.isnan(out.loc["2025-01-12", "lagsd_v"])
    out2 = attach_same_day_type_lag(p, ["v"], max_gap_days=30).set_index("date")
    assert out2.loc["2025-01-12", "lagsd_v"] == 99
    assert out2.loc["2025-01-12", "lagsd_gap_days"] == 23
    assert len(out2) == len(p)
