import pytest

from DATA_ENGINE.collect.kleague_schedule_backfill import _parse_schedule_response


def test_parse_schedule_response_maps_known_fields():
    payload = {
        "resultCode": "200",
        "resultMsg": "성공",
        "data": {
            "scheduleList": [
                {
                    "gameId": 25,
                    "roundId": 5,
                    "gameDate": "2024.04.02",
                    "gameTime": "19:30",
                    "homeTeamName": "포항",
                    "awayTeamName": "수원FC",
                    "fieldName": "포항 스틸야드",
                    "homeGoal": 1,
                    "awayGoal": 1,
                    "audienceQty": 5143,
                    "gameStatus": "FE",
                    "broadcastName": "JTBC G&S//COUPANGPLAY",
                }
            ]
        },
    }

    games = _parse_schedule_response(payload)

    assert games == [
        {
            "date": "2024-04-02",
            "time": "19:30",
            "game_id": 25,
            "round": 5,
            "home_team": "포항",
            "away_team": "수원FC",
            "home_score": 1,
            "away_score": 1,
            "stadium": "포항 스틸야드",
            "attendance": 5143,
            "status": "FE",
            "broadcaster": "JTBC G&S//COUPANGPLAY",
        }
    ]


def test_parse_schedule_response_empty_list_is_not_an_error():
    payload = {"resultCode": "200", "resultMsg": "성공", "data": {"scheduleList": []}}

    assert _parse_schedule_response(payload) == []


def test_parse_schedule_response_raises_on_failed_result_code():
    payload = {"resultCode": "500", "resultMsg": "서버 오류", "data": {}}

    with pytest.raises(RuntimeError, match="서버 오류"):
        _parse_schedule_response(payload)
