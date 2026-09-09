import pandas as pd

from DATA_ENGINE.eda.parsers_festival import CAPITAL_PROVINCES, filter_capital_area


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
