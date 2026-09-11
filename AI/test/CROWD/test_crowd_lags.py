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
