import pandas as pd

from DATA_ENGINE.eda.parsers_crowd_ridership import (
    duplicate_cell_inventory,
    load_monthly_ridership_csv,
)


def test_load_monthly_ridership_csv_melts_hour_columns(tmp_path):
    csv_path = tmp_path / "ridership.csv"
    csv_path.write_text(
        "사용월,호선명,지하철역,04시-05시 승차인원,04시-05시 하차인원,작업일자\n"
        "202401,1호선,서울역,100,50,20240201\n",
        encoding="cp949",
    )

    result = load_monthly_ridership_csv(csv_path)

    assert set(result.columns) == {
        "usage_month",
        "line",
        "station_name",
        "passengers",
        "time_slot",
        "direction",
    }
    assert len(result) == 2  # 승차 1행 + 하차 1행
    boarding = result[result["direction"] == "boarding"].iloc[0]
    assert boarding["time_slot"] == "04시-05시"
    assert boarding["passengers"] == 100
    alighting = result[result["direction"] == "alighting"].iloc[0]
    assert alighting["passengers"] == 50


def test_duplicate_cell_inventory_flags_repeated_key():
    df = pd.DataFrame(
        {
            "usage_month": [202401, 202401, 202401],
            "line": ["1호선", "1호선", "1호선"],
            "station_name": ["서울역", "서울역", "서울역"],
            "time_slot": ["04시-05시", "04시-05시", "05시-06시"],
            "direction": ["boarding", "boarding", "boarding"],
            "passengers": [100, 105, 200],
        }
    )

    result = duplicate_cell_inventory(df)

    assert len(result) == 2
    assert set(result["passengers"]) == {100, 105}
