import pandas as pd

from DATA_ENGINE.eda.filter_kleague_seoul_metro import filter_seoul_metro_games


def test_filter_seoul_metro_games_keeps_only_target_stadiums():
    games = pd.DataFrame(
        {
            "date": ["2024-03-01", "2024-03-02", "2024-03-03"],
            "home_team": ["FC서울", "포항", "인천"],
            "stadium": ["서울 월드컵", "포항 스틸야드", "인천 전용"],
            "attendance": [10000, 8000, 7000],
        }
    )

    result = filter_seoul_metro_games(games)

    assert set(result["stadium"]) == {"서울 월드컵", "인천 전용"}
    assert len(result) == 2


def test_filter_seoul_metro_games_empty_when_no_match():
    games = pd.DataFrame({"stadium": ["포항 스틸야드"], "attendance": [1000]})

    assert filter_seoul_metro_games(games).empty
