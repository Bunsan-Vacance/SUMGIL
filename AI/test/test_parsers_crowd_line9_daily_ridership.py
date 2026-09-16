import pandas as pd
import pytest

from DATA_ENGINE.eda.parsers_crowd_line9_daily_ridership import (
    EXCLUDED_FILENAMES,
    _normalize_hour_column,
    attach_station_master,
    drop_conflicting_duplicates,
    duplicate_cell_inventory,
    load_line9_daily_csv,
    load_station_master,
)


def _write_station_master_csv(path):
    """4126~4138(9호선(연장)) 2역 + 범위 밖 1역을 담은 축소 역사마스터 픽스처."""
    path.write_text(
        "역사_ID,역사명,호선,위도,경도\n"
        "4126,언주,9호선(연장),37.507287,127.033868\n"
        "4136,올림픽공원(한국체대),9호선(연장),37.516269,127.130288\n"
        "150,서울역,1호선,37.554648,126.972559\n",
        encoding="cp949",
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


def _conflicting_frame():
    """언주역 2025-03-22 alighting이 값이 다른 2건으로 중복된 상황 — 다른 역·날짜는 정상."""
    return pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2025-03-22", "2025-03-22", "2025-03-22", "2025-01-01", "2025-01-01"]
            ),
            "station_no": [4126, 4126, 4126, 4126, 4127],
            "station_name": ["언주", "언주", "언주", "언주", "선정릉"],
            "time_slot": ["08-09", "08-09", "09-10", "08-09", "08-09"],
            "direction": ["alighting", "alighting", "alighting", "alighting", "alighting"],
            "passengers": [3389, 431, 605, 200, 210],
        }
    )


def test_drop_conflicting_duplicates_removes_only_the_conflicting_station_day():
    """충돌하는 (날짜, 역, 방향) 조합은 그 조합 전체(모든 time_slot)가 빠져야 한다."""
    cleaned, dropped = drop_conflicting_duplicates(_conflicting_frame())

    assert len(dropped) == 1
    assert dropped.iloc[0][["date", "station_no", "direction"]].tolist() == [
        pd.Timestamp("2025-03-22"),
        4126,
        "alighting",
    ]
    # 언주 2025-03-22의 08-09, 09-10 행이 전부 빠지고, 정상 조합(선정릉·2025-01-01 언주)만 남는다.
    assert len(cleaned) == 2
    assert not ((cleaned["station_no"] == 4126) & (cleaned["date"] == "2025-03-22")).any()


def test_load_station_master_keeps_only_stage_2_3_range(tmp_path):
    _write_station_master_csv(tmp_path / "서울시 역사마스터 정보.csv")

    result = load_station_master(tmp_path)

    assert set(result["station_no"]) == {4126, 4136}
    assert list(result.columns) == ["station_no", "station_name_master", "lat", "lon"]


def test_attach_station_master_prefers_master_spelling(tmp_path):
    """이 CSV의 "올림픽공원"과 마스터의 "올림픽공원(한국체대)"이 다르면 마스터 쪽을 쓴다."""
    _write_station_master_csv(tmp_path / "서울시 역사마스터 정보.csv")
    df = pd.DataFrame({"station_no": [4136], "station_name": ["올림픽공원"], "passengers": [10]})

    result = attach_station_master(df, tmp_path)

    assert result["station_name"].iloc[0] == "올림픽공원(한국체대)"
    assert result["lat"].iloc[0] == pytest.approx(37.516269)
    assert "station_name_master" not in result.columns


def test_attach_station_master_raises_on_unknown_station(tmp_path):
    """역사마스터 4126~4138 범위에 없는 station_no가 섞이면 조용히 버리지 않고 예외를 낸다."""
    _write_station_master_csv(tmp_path / "서울시 역사마스터 정보.csv")
    df = pd.DataFrame({"station_no": [4126, 9999], "station_name": ["언주", "미확인역"]})

    with pytest.raises(ValueError, match="9999"):
        attach_station_master(df, tmp_path)


def test_drop_conflicting_duplicates_is_noop_when_no_conflicts():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01"]),
            "station_no": [4126],
            "station_name": ["언주"],
            "time_slot": ["08-09"],
            "direction": ["alighting"],
            "passengers": [200],
        }
    )

    cleaned, dropped = drop_conflicting_duplicates(df)

    assert len(cleaned) == 1
    assert dropped.empty
