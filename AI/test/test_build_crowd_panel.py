import pandas as pd
import pytest

from DATA_ENGINE.eda.build_crowd_panel import (
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
