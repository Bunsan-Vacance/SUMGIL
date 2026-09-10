import pandas as pd

from DATA_ENGINE.eda.parsers_crowd_line9_daily_ridership import (
    EXCLUDED_FILENAMES,
    _normalize_hour_column,
    duplicate_cell_inventory,
    load_line9_daily_csv,
)


def test_normalize_hour_column_matches_hh_si_hh_si_format():
    assert _normalize_hour_column("06시-07시") == "06-07"
    assert _normalize_hour_column("00시-01시") == "00-01"
    assert _normalize_hour_column("23시-24시") == "23-24"
    assert _normalize_hour_column("연번") is None


def test_load_line9_daily_csv_parses_boarding_and_alighting(tmp_path):
    csv_path = tmp_path / "a.csv"
    csv_path.write_text(
        "연번,날짜,호선,역번호,역사명,구분,05시-06시,06시-07시\n"
        "1,2025-01-01,9,4126,언주,순승차,10,20\n"
        "2,2025-01-01,9,4126,언주,순하차,5,15\n",
        encoding="cp949",
    )

    result = load_line9_daily_csv(csv_path)

    assert len(result) == 4
    assert set(result["time_slot"]) == {"05-06", "06-07"}
    assert set(result["direction"]) == {"boarding", "alighting"}
    assert (result["line"] == "9호선").all()
    boarding_0607 = result[(result["direction"] == "boarding") & (result["time_slot"] == "06-07")]
    assert boarding_0607["passengers"].iloc[0] == 20


def test_load_line9_daily_csv_strips_thousands_comma(tmp_path):
    """러시아워대 값이 "1,032" 같은 천 단위 콤마로 들어와도 정수로 파싱돼야 한다."""
    csv_path = tmp_path / "b.csv"
    csv_path.write_text(
        "연번,날짜,호선,역번호,역사명,구분,08시-09시\n" '1,2025-03-22,9,4126,언주,순하차,"3,389"\n',
        encoding="cp949",
    )

    result = load_line9_daily_csv(csv_path)

    assert result["passengers"].iloc[0] == 3389
    assert pd.api.types.is_integer_dtype(result["passengers"])


def test_duplicate_cell_inventory_flags_repeated_key():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-03-22", "2025-03-22"]),
            "station_no": [4126, 4126],
            "station_name": ["언주", "언주"],
            "time_slot": ["08-09", "08-09"],
            "direction": ["alighting", "alighting"],
            "passengers": [3389, 431],
        }
    )

    result = duplicate_cell_inventory(df)

    assert len(result) == 2


def test_duplicate_cell_inventory_ignores_unique_keys():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-01-02"]),
            "station_no": [4126, 4126],
            "station_name": ["언주", "언주"],
            "time_slot": ["08-09", "08-09"],
            "direction": ["alighting", "alighting"],
            "passengers": [200, 210],
        }
    )

    assert duplicate_cell_inventory(df).empty


def test_excluded_filenames_contains_the_redundant_subset_file():
    """20250731.csv는 연간 파일(20250101-251231)의 완전한 부분집합이라 제외 대상이다."""
    assert "서울교통공사_9호선2_3단계 역별일별시간대별승하차인원_20250731.csv" in EXCLUDED_FILENAMES
