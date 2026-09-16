from DATA_ENGINE.collect.kbo_schedule_backfill import _parse_play_cell, _parse_schedule_response


def _day_cell(text: str, rowspan: str | None = None) -> dict:
    return {"Text": text, "Class": "day", "RowSpan": rowspan}


def _cell(text: str, cls: str | None = None) -> dict:
    return {"Text": text, "Class": cls}


def test_parse_play_cell_with_score_and_result():
    left, right, left_score, right_score = _parse_play_cell(
        '<span>롯데</span><em><span class="win">1</span><span>vs</span>'
        '<span class="lose">0</span></em><span>한화</span>'
    )
    assert (left, right, left_score, right_score) == ("롯데", "한화", 1, 0)


def test_parse_play_cell_without_score_not_zero():
    # 취소·경기 전 상태 — 점수가 없다는 걸 0으로 뭉개면 실제 0:0 경기와 구분이 안 된다.
    left, right, left_score, right_score = _parse_play_cell(
        "<span>롯데</span><em><span>vs</span></em><span>한화</span>"
    )
    assert (left, right) == ("롯데", "한화")
    assert left_score is None
    assert right_score is None


def test_parse_schedule_response_carries_date_across_same_day_rows():
    payload = {
        "rows": [
            {
                "row": [
                    _day_cell("04.02(화)", rowspan="2"),
                    _cell("<b>18:30</b>", "time"),
                    _cell(
                        '<span>롯데</span><em><span class="win">1</span><span>vs</span>'
                        '<span class="lose">0</span></em><span>한화</span>',
                        "play",
                    ),
                    _cell(
                        "<a href='/Schedule/GameCenter/Main.aspx?"
                        "gameDate=20240402&gameId=20240402LTHH0&section=REVIEW'>리뷰</a>",
                        "relay",
                    ),
                    _cell("<a href='...'>하이라이트</a>"),
                    _cell("KN-T"),
                    _cell(""),
                    _cell("한밭"),
                    _cell("-"),
                ]
            },
            {
                # 같은 날 두 번째 경기 — 날짜 셀이 없다.
                "row": [
                    _cell("<b>18:30</b>", "time"),
                    _cell(
                        "<span>NC</span><em><span>vs</span></em><span>LG</span>",
                        "play",
                    ),
                    _cell("", "relay"),  # 취소된 경기는 리뷰 링크가 없다
                    _cell(""),
                    _cell(""),
                    _cell(""),
                    _cell("잠실"),
                    _cell("우천취소"),
                ]
            },
        ]
    }

    games = _parse_schedule_response(payload, season_id=2024)

    assert len(games) == 2
    assert games[0]["date"] == games[1]["date"] == "2024-04-02"
    assert games[0]["game_id"] == "20240402LTHH0"
    assert games[0]["status"] == "-"
    assert games[1]["game_id"] is None  # 취소된 경기는 리뷰 링크가 없어 game_id도 없다
    assert games[1]["score_left"] is None
    assert games[1]["status"] == "우천취소"


def test_parse_schedule_response_skips_row_with_no_known_date():
    payload = {"rows": [{"row": [_cell("<b>18:30</b>", "time")]}]}

    games = _parse_schedule_response(payload, season_id=2024)

    assert games == []
