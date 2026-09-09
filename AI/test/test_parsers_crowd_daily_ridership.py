import pandas as pd

from DATA_ENGINE.eda.parsers_crowd_daily_ridership import (
    _normalize_hour_column,
    duplicate_cell_inventory,
    load_daily_ridership_csv,
)


def test_normalize_hour_column_handles_both_file_variants():
    assert _normalize_hour_column("06시이전") == "~06"
    assert _normalize_hour_column("06시 이전") == "~06"
    assert _normalize_hour_column("24시이후") == "24~"
    assert _normalize_hour_column("24시 이후") == "24~"
    assert _normalize_hour_column("06-07시간대") == "06-07"
    assert _normalize_hour_column("06시-07시") == "06-07"
    assert _normalize_hour_column("연번") is None


def test_load_daily_ridership_csv_variant_with_transport_date(tmp_path):
    csv_path = tmp_path / "a.csv"
    csv_path.write_text(
        "연번,수송일자,호선,역번호,역명,승하차구분,06시이전,06-07시간대\n"
        "1,2025-01-01,1호선,150,서울역,승차,10,20\n",
        encoding="cp949",
    )

    result = load_daily_ridership_csv(csv_path)

    assert len(result) == 2
    assert set(result["time_slot"]) == {"~06", "06-07"}
    assert result[result["time_slot"] == "06-07"]["passengers"].iloc[0] == 20
    assert result["direction"].iloc[0] == "boarding"


def test_load_daily_ridership_csv_variant_with_date(tmp_path):
    csv_path = tmp_path / "b.csv"
    csv_path.write_text(
        "연번,날짜,호선,역번호,역명,구분,06시 이전,06시-07시\n"
        "1,2024-01-01,1호선,150,서울역,하차,5,15\n",
        encoding="cp949",
    )

    result = load_daily_ridership_csv(csv_path)

    assert len(result) == 2
    assert set(result["time_slot"]) == {"~06", "06-07"}
    assert result["direction"].iloc[0] == "alighting"


def test_load_daily_ridership_csv_drops_blank_trailing_rows(tmp_path):
    csv_path = tmp_path / "c.csv"
    csv_path.write_text(
        "연번,수송일자,호선,역번호,역명,승하차구분,06시이전,06-07시간대\n"
        "1,2025-01-01,1호선,150,서울역,승차,10,20\n"
        ",,,,,,,\n",
        encoding="cp949",
    )

    result = load_daily_ridership_csv(csv_path)

    assert len(result) == 2  # 빈 꼬리 행은 melt 전에 제거돼 시간대 수만큼 안 뻥튀기된다
    assert result["station_name"].notna().all()


def test_duplicate_cell_inventory_flags_repeated_key():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-01"]),
            "line": ["1호선", "1호선"],
            "station_name": ["서울역", "서울역"],
            "time_slot": ["06-07", "06-07"],
            "direction": ["boarding", "boarding"],
            "passengers": [10, 12],
        }
    )

    result = duplicate_cell_inventory(df)

    assert len(result) == 2
