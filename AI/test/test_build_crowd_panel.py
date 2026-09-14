import pandas as pd
import pytest

import DATA_ENGINE.eda.build_crowd_panel as build_crowd_panel_module
from DATA_ENGINE.eda.build_crowd_panel import (
    attach_calendar,
    main,
    panel_output_name,
    pivot_directions,
    slot_to_weather_offset,
    station_name_inventory,
)


@pytest.mark.parametrize(
    ("slot", "expected"),
    [
        ("06-07", (0, 6)),
        ("08-09", (0, 8)),
        ("23-24", (0, 23)),
        # 첫차 구간은 같은 날 05시, 자정 이후 구간은 다음 날 00시에 붙는다.
        ("~06", (0, 5)),
        ("24~", (1, 0)),
    ],
)
def test_slot_to_weather_offset(slot, expected):
    assert slot_to_weather_offset(slot) == expected


def test_station_name_inventory_flags_renamed_stations():
    df = pd.DataFrame(
        {
            "station_no": [409, 409, 150],
            "station_name": ["당고개", "불암산", "서울역"],
        }
    )

    result = station_name_inventory(df)

    assert len(result) == 1
    assert result.iloc[0]["station_no"] == 409
    assert set(result.iloc[0]["names"]) == {"당고개", "불암산"}


def test_station_name_inventory_empty_when_no_rename():
    df = pd.DataFrame({"station_no": [150, 150], "station_name": ["서울역", "서울역"]})

    assert station_name_inventory(df).empty


def test_attach_calendar_keeps_saturday_sunday_distinct_from_weekday_holiday(tmp_path, monkeypatch):
    """holiday_calendar의 is_holiday는 원천(학교 휴업일)상 주말도 대부분 Y다 — dow<5 가드
    없이 조건 없는 덮어쓰기를 쓰면 토요일·일요일이 전부 "휴일"로 사라진다(2026-09-10
    원본 대조로 발견: 일요일 100%·토요일 60%가 is_holiday=True)."""
    holiday = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-06", "2024-01-07", "2024-01-08"]),
            "weekday_ko": ["월", "토", "일", "월"],
            # 01-01 신정(평일 공휴일), 01-06·01-07은 원천상 주말이라 Y, 01-08은 평범한 평일.
            "is_holiday": [True, True, True, False],
        }
    )
    holiday.to_parquet(tmp_path / "holiday_calendar.parquet", index=False)
    monkeypatch.setattr(build_crowd_panel_module, "HOLIDAY_INTERIM", tmp_path)

    result = attach_calendar(pd.DataFrame({"date": holiday["date"]}))

    assert result.set_index("date")["day_type"].to_dict() == {
        pd.Timestamp("2024-01-01"): "휴일",  # 평일에 걸린 공휴일만 덮인다
        pd.Timestamp("2024-01-06"): "토요일",  # is_holiday=True여도 주말이라 유지
        pd.Timestamp("2024-01-07"): "일요일",
        pd.Timestamp("2024-01-08"): "평일",
    }


def test_pivot_directions_makes_boarding_alighting_columns():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01"] * 2),
            "station_no": [150, 150],
            "time_slot": ["08-09", "08-09"],
            "direction": ["boarding", "alighting"],
            "passengers": [100.0, 250.0],
        }
    )

    wide = pivot_directions(df)

    assert len(wide) == 1
    assert wide.loc[0, "boarding"] == 100.0
    assert wide.loc[0, "alighting"] == 250.0


# ── 구간 백필(학습 기간 확장) ──
@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        # 기본 구간은 기존 파일명을 그대로 내야 한다 — 백필 인자를 붙여도 회귀가 없어야 한다.
        ("2024-01-01", "2025-12-31", "crowd_panel_2024_2025.parquet"),
        ("2023-01-01", "2023-12-31", "crowd_panel_2023_2023.parquet"),
        ("2022-01-01", "2025-12-31", "crowd_panel_2022_2025.parquet"),
    ],
)
def test_panel_output_name_is_derived_from_range(start, end, expected):
    assert panel_output_name(pd.Timestamp(start), pd.Timestamp(end)) == expected


def test_main_rejects_reversed_range_before_touching_data():
    """구간이 뒤집혀 있으면 원천을 읽기 전에 멈춘다 — 빈 판을 조용히 저장하지 않는다."""
    with pytest.raises(SystemExit):
        main(["--start", "2025-01-01", "--end", "2024-01-01"])
