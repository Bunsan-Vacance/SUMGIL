from DATA_ENGINE.collect.kbo_crowd_backfill import (
    _extract_hidden_fields,
    _parse_delta_response,
    parse_crowd_table,
)

_SAMPLE_TABLE_HTML = """
<table class="tData" summary="날짜,요일,홈,방문,구장,관중수,">
    <tbody>
        <tr class="order">
            <td>2024/03/23</td>
            <td>토</td>
            <td>LG</td>
            <td>한화</td>
            <td>잠실</td>
            <td>23,750</td>
        </tr>
        <tr class="order">
            <td>2024/04/21</td>
            <td>일</td>
            <td>두산</td>
            <td>키움</td>
            <td>잠실</td>
            <td>6,197</td>
        </tr>
    </tbody>
</table>
"""


def test_parse_delta_response_handles_pipes_inside_content():
    # content 안에 "|"가 섞여 있어도(HTML이므로 당연히 있음) 길이 prefix로 정확히 잘라야 한다.
    content = "<div>a|b|c</div>"
    text = f"{len(content)}|updatePanel|myPanelId|{content}|8|hiddenField|__VIEWSTATE|abcd1234|"

    parts = _parse_delta_response(text)

    assert parts["myPanelId"] == content
    assert parts["__VIEWSTATE"] == "abcd1234"


def test_parse_crowd_table_extracts_rows():
    games = parse_crowd_table(_SAMPLE_TABLE_HTML)

    assert games == [
        {
            "date": "2024-03-23",
            "weekday": "토",
            "home_team": "LG",
            "away_team": "한화",
            "stadium": "잠실",
            "attendance": 23750,
        },
        {
            "date": "2024-04-21",
            "weekday": "일",
            "home_team": "두산",
            "away_team": "키움",
            "stadium": "잠실",
            "attendance": 6197,
        },
    ]


def test_parse_crowd_table_skips_malformed_rows():
    html = """
    <table class="tData"><tbody>
        <tr class="order"><td>2024/03/23</td><td>토</td></tr>
    </tbody></table>
    """

    assert parse_crowd_table(html) == []


def test_extract_hidden_fields_reads_viewstate_trio():
    html = """
    <input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="vs123" />
    <input type="hidden" name="__VIEWSTATEGENERATOR" id="__VIEWSTATEGENERATOR" value="gen456" />
    <input type="hidden" name="__EVENTVALIDATION" id="__EVENTVALIDATION" value="ev789" />
    """

    fields = _extract_hidden_fields(html)

    assert fields == {
        "__VIEWSTATE": "vs123",
        "__VIEWSTATEGENERATOR": "gen456",
        "__EVENTVALIDATION": "ev789",
    }
