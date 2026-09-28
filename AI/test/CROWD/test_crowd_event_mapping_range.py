"""200 — `map_events_to_stations`의 `--start`/`--end` 구간 override 파싱(`resolve_range`).

배치 서빙용 미래 구간(2026) 이벤트 표를 만들 때 패널 날짜 대신 명시 구간을 쓸 수 있어야
한다(문제 설명 참고). 순수 함수로 뽑아 argparse 없이 검증한다.
"""

from __future__ import annotations

import pandas as pd
import pytest

from DATA_ENGINE.eda.map_events_to_stations import range_output_name, resolve_range


def _panel_dates() -> pd.Series:
    return pd.Series(pd.to_datetime(["2024-01-01", "2024-06-15", "2025-12-31"]))


def test_resolve_range_both_given_overrides_panel():
    start, end = resolve_range(_panel_dates(), "2026-01-01", "2026-12-31")
    assert start == pd.Timestamp("2026-01-01")
    assert end == pd.Timestamp("2026-12-31")


def test_resolve_range_none_given_uses_panel_range():
    start, end = resolve_range(_panel_dates(), None, None)
    assert start == pd.Timestamp("2024-01-01")
    assert end == pd.Timestamp("2025-12-31")


def test_resolve_range_only_start_given_raises_system_exit():
    with pytest.raises(SystemExit):
        resolve_range(_panel_dates(), "2026-01-01", None)


def test_resolve_range_only_end_given_raises_system_exit():
    with pytest.raises(SystemExit):
        resolve_range(_panel_dates(), None, "2026-12-31")


def test_range_output_name_uses_start_end_years():
    name = range_output_name(pd.Timestamp("2026-01-01"), pd.Timestamp("2026-12-31"))
    assert name == "crowd_station_events_2026_2026.parquet"
