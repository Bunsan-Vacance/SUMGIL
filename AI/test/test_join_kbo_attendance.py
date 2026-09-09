import pandas as pd

from DATA_ENGINE.eda.join_kbo_attendance import (
    drop_doubleheader_days,
    duplicate_group_inventory,
    filter_seoul_metro_games,
    identify_doubleheader_keys,
    join_kbo_attendance,
    report_team_order,
)


def _games_row(date, stadium, left, right, **kw):
    row = {
        "date": date,
        "time": "18:30",
        "game_id": f"{date}{left}{right}0",
        "team_left": left,
        "team_right": right,
        "score_left": 1,
        "score_right": 0,
        "broadcaster": "KN-T",
        "stadium": stadium,
        "status": "-",
    }
    row.update(kw)
    return row


def _crowd_row(date, stadium, home, away, attendance):
    return {
        "date": date,
        "weekday": "화",
        "home_team": home,
        "away_team": away,
        "stadium": stadium,
        "attendance": attendance,
    }


def test_join_matches_single_game_regardless_of_left_right_order():
    games = pd.DataFrame([_games_row("2024-04-02", "잠실", "한화", "LG")])
    crowd = pd.DataFrame([_crowd_row("2024-04-02", "잠실", "LG", "한화", 15000)])

    merged = join_kbo_attendance(games, crowd)

    assert merged.loc[0, "attendance"] == 15000
    assert merged.loc[0, "home_team"] == "LG"


def test_join_disambiguates_doubleheader_by_order():
    games = pd.DataFrame(
        [
            _games_row("2024-04-21", "잠실", "두산", "키움"),
            _games_row("2024-04-21", "잠실", "두산", "키움"),
        ]
    )
    crowd = pd.DataFrame(
        [
            _crowd_row("2024-04-21", "잠실", "두산", "키움", 13745),
            _crowd_row("2024-04-21", "잠실", "두산", "키움", 6197),
        ]
    )

    merged = join_kbo_attendance(games, crowd)

    assert list(merged["attendance"]) == [13745, 6197]


def test_join_leaves_unmatched_games_as_nan():
    games = pd.DataFrame([_games_row("2024-04-02", "사직", "롯데", "KT")])
    crowd = pd.DataFrame([_crowd_row("2024-04-02", "잠실", "LG", "한화", 15000)])

    merged = join_kbo_attendance(games, crowd)

    assert merged.loc[0, "attendance"] is None or pd.isna(merged.loc[0, "attendance"])


def test_report_team_order_counts_matches():
    merged = pd.DataFrame(
        {
            "team_left": ["LG", "두산"],
            "team_right": ["한화", "키움"],
            "home_team": ["LG", "키움"],
            "away_team": ["한화", "두산"],
        }
    )

    report = report_team_order(merged)

    assert "team_left==home_team: 1건" in report
    assert "team_left==away_team: 1건" in report


def test_filter_seoul_metro_games_keeps_only_target_stadiums_regardless_of_home_away():
    merged = pd.DataFrame(
        [
            # 원정 팀(삼성)이 잠실로 온 경기 — 서울 교통량과 관련 있으니 남아야 한다.
            _games_row("2024-04-02", "잠실", "LG", "삼성"),
            # 서울권 팀(두산)이 지방(대구)으로 원정 간 경기 — 무관하니 빠져야 한다.
            _games_row("2024-04-03", "대구", "두산", "삼성"),
        ]
    )

    result = filter_seoul_metro_games(merged)

    assert len(result) == 1
    assert result.iloc[0]["stadium"] == "잠실"


def test_identify_doubleheader_keys_finds_multi_game_days():
    crowd = pd.DataFrame(
        [
            _crowd_row("2024-04-21", "잠실", "두산", "키움", 13745),
            _crowd_row("2024-04-21", "잠실", "두산", "키움", 6197),
            _crowd_row("2024-04-02", "잠실", "LG", "한화", 15000),
        ]
    )

    keys = identify_doubleheader_keys(crowd)

    assert list(keys) == [("2024-04-21", "잠실")]


def test_drop_doubleheader_days_removes_both_games_of_flagged_dates():
    games = pd.DataFrame(
        [
            _games_row("2024-04-21", "잠실", "키움", "두산"),
            _games_row("2024-04-21", "잠실", "키움", "두산"),
            _games_row("2024-04-02", "잠실", "한화", "LG"),
        ]
    )
    dh_keys = pd.MultiIndex.from_tuples([("2024-04-21", "잠실")])

    result = drop_doubleheader_days(games, dh_keys)

    assert len(result) == 1
    assert result.iloc[0]["date"] == "2024-04-02"


def test_drop_doubleheader_days_keeps_everything_when_no_doubleheaders():
    games = pd.DataFrame([_games_row("2024-04-02", "잠실", "한화", "LG")])
    dh_keys = pd.MultiIndex.from_tuples([], names=["date", "stadium"])

    result = drop_doubleheader_days(games, dh_keys)

    assert len(result) == 1


def test_duplicate_group_inventory_flags_more_than_two_same_matchup():
    crowd = pd.DataFrame(
        [
            _crowd_row("2024-04-21", "잠실", "두산", "키움", 1),
            _crowd_row("2024-04-21", "잠실", "두산", "키움", 2),
            _crowd_row("2024-04-21", "잠실", "두산", "키움", 3),
        ]
    )

    result = duplicate_group_inventory(crowd)

    assert len(result) == 1
    assert result.iloc[0]["count"] == 3
