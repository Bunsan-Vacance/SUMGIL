import pandas as pd

from DATA_ENGINE.eda.parsers_festival import (
    CAPITAL_PROVINCES,
    add_duration_days,
    drop_duplicate_festivals,
    filter_capital_area,
    find_reversed_dates,
)


def test_filter_capital_area_keeps_only_seoul_gyeonggi_incheon():
    df = pd.DataFrame(
        {
            "name": ["서울축제", "부산축제", "경기축제", "인천축제"],
            "province": ["서울특별시", "부산광역시", "경기도", "인천광역시"],
        }
    )

    result = filter_capital_area(df)

    assert set(result["province"]) == set(CAPITAL_PROVINCES)
    assert len(result) == 3
    assert "부산축제" not in result["name"].values


def test_filter_capital_area_resets_index():
    df = pd.DataFrame(
        {"name": ["a", "b", "c"], "province": ["부산광역시", "서울특별시", "대구광역시"]}
    )

    result = filter_capital_area(df)

    assert list(result.index) == [0]


def _festivals(**overrides):
    base = {
        "festival_id": ["a", "b", "c"],
        "name": ["불꽃축제", "불꽃축제", "박물관 기획전"],
        "start_date": pd.to_datetime(["2024-10-05", "2024-10-05", "2024-03-01"]),
        "end_date": pd.to_datetime(["2024-10-05", "2024-10-05", "2024-08-31"]),
        "lat": [37.5, 37.5, 37.6],
        "lon": [127.0, 127.0, 127.1],
    }
    base.update(overrides)
    return pd.DataFrame(base)


def test_drop_duplicate_festivals_merges_same_event_registered_twice():
    """이름·기간·좌표가 같으면 ID가 달라도 한 축제다 — 안 합치면 개수가 2배로 잡힌다."""
    deduped, removed = drop_duplicate_festivals(_festivals())

    assert removed == 1
    assert len(deduped) == 2
    assert set(deduped["name"]) == {"불꽃축제", "박물관 기획전"}


def test_drop_duplicate_festivals_keeps_same_name_on_different_dates():
    """이름만 같고 기간이 다르면 다른 회차다 — 합치면 안 된다."""
    df = _festivals(
        start_date=pd.to_datetime(["2024-10-05", "2025-10-04", "2024-03-01"]),
        end_date=pd.to_datetime(["2024-10-05", "2025-10-04", "2024-08-31"]),
    )

    deduped, removed = drop_duplicate_festivals(df)

    assert removed == 0
    assert len(deduped) == 3


def test_add_duration_days_counts_single_day_festival_as_one():
    result = add_duration_days(_festivals())

    assert result.loc[0, "duration_days"] == 1
    assert result.loc[2, "duration_days"] == 184


def test_find_reversed_dates_flags_end_before_start():
    """종료일이 시작일보다 이르면 개최일 전개에서 조용히 사라지므로 따로 잡아낸다."""
    df = _festivals(
        start_date=pd.to_datetime(["2025-09-27", "2024-10-05", "2024-03-01"]),
        end_date=pd.to_datetime(["2024-10-06", "2024-10-05", "2024-08-31"]),
    )

    reversed_rows = find_reversed_dates(add_duration_days(df))

    assert len(reversed_rows) == 1
    assert reversed_rows.iloc[0]["festival_id"] == "a"


def test_find_reversed_dates_empty_when_all_valid():
    assert find_reversed_dates(add_duration_days(_festivals())).empty
