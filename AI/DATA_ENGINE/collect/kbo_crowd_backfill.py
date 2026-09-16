"""KBO 관중수(경기별·일자별) 백필 — 서울/경기/인천 인접 구장(잠실·고척·문학·수원)만 대상.

koreabaseball.com/Record/Crowd/GraphDaily.aspx는 `kbo_schedule_backfill.py`가 쓰는
ASMX 엔드포인트와 전혀 다른 프로토콜이다 — **ASP.NET UpdatePanel 부분 포스트백**:

- 매 조회 전에 페이지를 먼저 GET해서 `__VIEWSTATE`·`__VIEWSTATEGENERATOR`·
  `__EVENTVALIDATION`(요청마다 새로 발급되는 서버 상태값)을 뽑아 그대로 실어 POST해야
  한다 — 고정값으로 재사용할 수 없다.
- 응답은 JSON이 아니라 `<content 바이트 길이>|타입|id|content|` 반복 형식의 ASP.NET AJAX
  "delta" 포맷이다. content(HTML) 안에 `|`가 섞여 있을 수 있어 길이 prefix를 그대로 읽어야
  하고, 단순 `str.split("|")`로 자르면 깨진다.
- `ddlMonth=0`("월별" 드롭다운의 "전체")로 **시즌 전체를 한 번에** 받는다 — 스케줄
  백필처럼 달마다 나눠 호출할 필요가 없다.

요청/응답은 브라우저 Network 탭 캡처(2026-09-09, GraphDaily.aspx에서 구장=잠실·시즌=2024로
조회)로 그대로 확인했다. 구장 코드는 응답에 포함된 `<select id="...ddlStadium">` 옵션에서
확인: JS=잠실, GC=고척, MH=문학, SW=수원(그 외 KC=광주, DK=대구, DN=대전, MS=마산, SJ=사직,
EC=이천(두산), CW=창원, PH=포항 등은 서비스 범위 밖이라 대상에서 뺐다).

실행:
    cd AI
    python -m DATA_ENGINE.collect.kbo_crowd_backfill --check-schema
    python -m DATA_ENGINE.collect.kbo_crowd_backfill --seasons 2024 2025 --yes
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from DATA_ENGINE.collect.common import AI_ROOT, http_retry

logger = logging.getLogger("kbo_crowd_backfill")

BASE_URL = "https://www.koreabaseball.com/Record/Crowd/GraphDaily.aspx"

# 서울/경기/인천 인접 구장만 — 나머지(광주·대구·대전·마산·사직·이천·창원·포항)는 대상 밖.
STADIUMS = {"JS": "잠실", "GC": "고척", "MH": "문학", "SW": "수원"}

RAW_DIR = AI_ROOT / "data" / "EXTERNAL" / "events" / "raw" / "kbo_crowd"

_PREFIX = "ctl00$ctl00$ctl00$cphContents$cphContents$cphContents$"
_PANEL_ID = "cphContents_cphContents_cphContents_udpRecord"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
    "X-MicrosoftAjax": "Delta=true",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://www.koreabaseball.com",
    "Referer": BASE_URL,
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}


def _extract_hidden_fields(html: str) -> dict[str, str]:
    """페이지 GET 응답에서 ASP.NET WebForms 히든 필드 3종을 뽑는다."""
    # html.parser는 이 페이지에서 __VIEWSTATE를 못 찾는다(2026-09-16 확인) — 앞쪽 <script>가
    # EUC-KR 주석을 섞어 놔서(문서 전체는 UTF-8) 트리 파싱이 그 지점에서 깨진다. lxml은
    # 이 마크업을 그대로 회복해서 파싱한다.
    soup = BeautifulSoup(html, "lxml")
    fields: dict[str, str] = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        tag = soup.find("input", id=name)
        if tag is None:
            raise ValueError(f"페이지에서 {name} 히든 필드를 찾지 못했습니다.")
        fields[name] = tag.get("value", "")
    return fields


def _parse_delta_response(text: str) -> dict[str, str]:
    """ASP.NET AJAX "delta" 부분 포스트백 응답을 {id 또는 type: content} 로 푼다.

    형식은 `<content 바이트 길이>|<type>|<id>|<content>|` 반복이다 — content에 `|`가
    섞여 있을 수 있어(HTML이라 당연히 있다) 길이 prefix를 신뢰하고 정확히 그만큼만 슬라이스
    한다. 단순 `split("|")`는 HTML 안의 `|` 때문에 깨진다.
    """
    parts: dict[str, str] = {}
    i = 0
    n = len(text)
    while i < n:
        sep1 = text.index("|", i)
        length = int(text[i:sep1])
        sep2 = text.index("|", sep1 + 1)
        type_ = text[sep1 + 1 : sep2]
        sep3 = text.index("|", sep2 + 1)
        id_ = text[sep2 + 1 : sep3]
        content_start = sep3 + 1
        content = text[content_start : content_start + length]
        parts[id_ or type_] = content
        i = content_start + length + 1  # +1: content 뒤 구분자 "|"
    return parts


def parse_crowd_table(update_panel_html: str) -> list[dict]:
    """updatePanel 안의 관중 현황 표를 레코드로 변환한다.

    표 헤더가 "날짜,요일,홈,방문,구장,관중수" 순서임을 페이지 summary 속성으로 확인했다
    (2026-09-09). 관중수의 쉼표 구분자는 int 변환 시 제거한다.
    """
    soup = BeautifulSoup(update_panel_html, "lxml")
    games = []
    for tr in soup.select("table.tData tbody tr.order"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) != 6:
            logger.warning("예상과 다른 셀 개수(%d)인 행을 건너뜁니다: %s", len(cells), cells)
            continue
        date_str, weekday, home, away, stadium, attendance_str = cells
        games.append(
            {
                "date": date_str.replace("/", "-"),
                "weekday": weekday,
                "home_team": home,
                "away_team": away,
                "stadium": stadium,
                "attendance": int(attendance_str.replace(",", "")),
            }
        )
    return games


@http_retry
def fetch_stadium_season(stadium_code: str, season: int) -> list[dict]:
    """구장 하나·시즌 하나 전체 경기의 일자별 관중수를 가져온다.

    매번 새 세션으로 페이지를 먼저 GET해 그때그때의 __VIEWSTATE 등을 얻는다 — 같은
    세션으로 여러 번 조회를 이어서 하려면 응답에 포함된 갱신된 __VIEWSTATE를 다음 요청에
    다시 실어야 하는데, 호출 빈도가 낮아(구장×시즌 조합 몇 개뿐) 매번 새로 받는 쪽이
    상태 관리 복잡도 없이 더 안전하다.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": _HEADERS["User-Agent"]})

    get_resp = session.get(BASE_URL, timeout=15)
    get_resp.raise_for_status()
    hidden = _extract_hidden_fields(get_resp.text)

    data = {
        f"{_PREFIX}ScriptManager1": f"{_PREFIX}udpRecord|{_PREFIX}btnSearch",
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "__VIEWSTATE": hidden["__VIEWSTATE"],
        "__VIEWSTATEGENERATOR": hidden["__VIEWSTATEGENERATOR"],
        "__EVENTVALIDATION": hidden["__EVENTVALIDATION"],
        f"{_PREFIX}ddlSeason": str(season),
        f"{_PREFIX}ddlMonth": "0",
        f"{_PREFIX}ddlTeam": "",
        f"{_PREFIX}ddlHomeAway": "",
        f"{_PREFIX}ddlStadium": stadium_code,
        f"{_PREFIX}ddlDayOfWeek": "0",
        "__ASYNCPOST": "true",
        f"{_PREFIX}btnSearch": "검색",
    }
    post_resp = session.post(BASE_URL, data=data, headers=_HEADERS, timeout=15)
    post_resp.raise_for_status()

    parts = _parse_delta_response(post_resp.text)
    panel_html = parts.get(_PANEL_ID)
    if panel_html is None:
        raise RuntimeError(f"응답에서 {_PANEL_ID} 패널을 찾지 못했습니다.")
    return parse_crowd_table(panel_html)


def check_schema(stadium_code: str = "JS", season: int = 2024) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    games = fetch_stadium_season(stadium_code, season)
    out_path = RAW_DIR / f"_schema_check_{stadium_code}{season}.json"
    out_path.write_text(json.dumps(games, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def backfill(seasons: list[int]) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for stadium_code, stadium_name in STADIUMS.items():
        for season in seasons:
            games = fetch_stadium_season(stadium_code, season)
            out_path = RAW_DIR / f"kbo_crowd_{stadium_code}_{season}.json"
            out_path.write_text(json.dumps(games, ensure_ascii=False), encoding="utf-8")
            logger.info(
                "저장 완료: %s (%s %d시즌, %d경기)",
                out_path,
                stadium_name,
                season,
                len(games),
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-schema",
        action="store_true",
        help="구장 1곳·시즌 1개만 조회해 원문 응답을 저장하고 종료 (하드 룰의 스키마 확인 예외)",
    )
    parser.add_argument("--seasons", type=int, nargs="+", default=[2024, 2025])
    parser.add_argument("--yes", action="store_true", help="실제로 전체 백필을 실행한다")
    args = parser.parse_args()

    if args.check_schema:
        out_path = check_schema()
        logger.info("스키마 확인용 응답 저장: %s", out_path)
        return

    n_calls = len(STADIUMS) * len(args.seasons)
    logger.info(
        "구장 %s, 시즌 %s, 예상 조회 %d건(구장×시즌, 각 GET+POST 2콜)",
        list(STADIUMS.values()),
        args.seasons,
        n_calls,
    )

    if not args.yes:
        logger.info("dry-run입니다. 실제로 실행하려면 --yes를 붙이세요.")
        return

    backfill(args.seasons)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    main()
