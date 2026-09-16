"""KBO 2024~2025 시즌 경기 일정·결과 백필 — 날짜, 시간, 구장, 대진, 스코어, 경기상태
(정상종료/우천취소/미세먼지취소 등), 중계사, gameId.

⚠️ **관중수는 이 엔드포인트에 없다** — 실제 응답을 확인해보니(2026-09-09, 2024년 4월)
정상 종료된 경기도 마지막 셀이 항상 "-"였다. 필요하면 경기별 리뷰 페이지
(`/Schedule/GameCenter/Main.aspx?gameDate=...&gameId=...&section=REVIEW`)를 게임 수만큼 추가
호출해야 하는데, 그건 호출량이 커지므로(시즌당 700경기 이상) 이번 스크립트 범위에 넣지
않았다 — 필요해지면 범위를 다시 사용자와 맞출 것.

요청 형태(URL·헤더·form 파라미터)는 실제 브라우저 Network 탭 캡처(2026-09-09, koreabaseball.com
Schedule.aspx에서 "Copy as cURL")로 확인된 값을 그대로 옮긴 것이다 — 이전에 이 파일 안에서
시도했던 두 추측(GET, JSON 바디)은 각각 서버 에러 페이지·401로 확인되어 틀렸었다. 실제로는
POST + `application/x-www-form-urlencoded`, 그리고 세션 쿠키(`ASP.NET_SessionId`, 일정 페이지를
먼저 GET하면 발급됨)가 필요하다.

응답은 날짜별 그리드이고 각 셀의 `Text`가 HTML 조각이다(표 렌더링용 원본이 그대로 옴) —
`_parse_schedule_response()`가 정규식으로 이걸 레코드로 풀어낸다. 한 경기 행의 셀 순서는
(그날 첫 경기면 맨 앞에 날짜 셀이 하나 더 붙고) 시간 → 대진(스코어) → 리뷰링크(gameId 포함)
→ 하이라이트링크 → 중계사 → (항상 빈칸, 용도 불명) → 구장 → 상태("-" 또는 취소 사유) 순으로
고정돼 있다 — 2024-04 응답 표본(정상 종료·우천취소·미세먼지취소 케이스 확인)으로 검증됨.
팀 표기 순서(왼쪽/오른쪽)가 원정/홈 중 무엇인지는 확인하지 않아 `team_left`/`team_right`로만
남겨뒀다 — 필요하면 실제 경기 결과와 대조해 확정할 것.

실행:
    cd AI
    python -m DATA_ENGINE.collect.kbo_schedule_backfill --check-schema        # 1개월만 호출, 원문 저장
    python -m DATA_ENGINE.collect.kbo_schedule_backfill --seasons 2024 2025 --yes
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

import requests

from DATA_ENGINE.collect.common import AI_ROOT, http_retry

logger = logging.getLogger("kbo_schedule_backfill")

BASE_URL = "https://www.koreabaseball.com/ws/Schedule.asmx/GetScheduleList"
LEAGUE_ID = 1  # KBO
# 실제 브라우저가 기본 로드 시 보낸 값 그대로(2026-09-09 캡처). 시리즈 구분(정규/포스트 등)
# 코드가 뭘 뜻하는지는 --check-schema 응답을 보고 확인할 것 — 지금은 검증된 조합만 그대로 쓴다.
SERIES_ID_LIST = "0,9,6"
TEAM_ID = (
    ""  # 캡처된 요청도 빈 값 — 전체 팀. 특정 팀만 필요하면 --check-schema로 실제 팀 코드 확인.
)

RAW_DIR = AI_ROOT / "data" / "EXTERNAL" / "events" / "raw" / "kbo"

SCHEDULE_PAGE_URL = "https://www.koreabaseball.com/Schedule/Schedule.aspx"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://www.koreabaseball.com",
    "Referer": SCHEDULE_PAGE_URL,
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}

_session: requests.Session | None = None


def _get_session() -> requests.Session:
    """일정 페이지를 먼저 GET해서 세션 쿠키를 챙긴 뒤 재사용한다.

    쿠키 없이 AJAX 엔드포인트를 바로 POST하면 401이 난다(실제로 확인됨, 2026-09-08) —
    페이지 방문 시 발급되는 세션이 있어야 그 뒤 AJAX 호출이 인증된 것으로 처리되는
    흔한 패턴. 모듈 전체에서 세션 하나를 재사용해 매 호출마다 다시 굽지 않는다.
    """
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": _HEADERS["User-Agent"]})
        resp = _session.get(SCHEDULE_PAGE_URL, timeout=15)
        resp.raise_for_status()
    return _session


@http_retry
def _fetch_month(season_id: int, game_month: str) -> dict:
    """한 시즌·한 달치 일정을 호출한다. game_month는 "04"처럼 2자리 문자열.

    form-urlencoded 바디여야 한다 — JSON 바디로 보내면 401이 난다(실제로 확인됨,
    2026-09-08). `teamId`가 없으면 500이 난다(마찬가지로 확인됨) — 빈 문자열이라도 반드시
    포함해야 한다.
    """
    session = _get_session()
    resp = session.post(
        BASE_URL,
        data={
            "leId": LEAGUE_ID,
            "srIdList": SERIES_ID_LIST,
            "seasonId": season_id,
            "gameMonth": game_month,
            "teamId": TEAM_ID,
        },
        headers=_HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


_DAY_CELL_PATTERN = re.compile(r"^(\d{2})\.(\d{2})\(.\)$")
_TIME_CELL_PATTERN = re.compile(r"<b>([\d:]+)</b>")
_PLAY_CELL_PATTERN = re.compile(r"<span>([^<]*)</span><em>(.*?)</em><span>([^<]*)</span>")
_PLAY_SCORE_PATTERN = re.compile(
    r'<span class="(?:win|lose)">(\d+)</span><span>vs</span><span class="(?:win|lose)">(\d+)</span>'
)
_GAME_ID_PATTERN = re.compile(r"gameId=(\w+)")

# 경기 셀 뒤에 이어지는 고정 순서(리뷰 링크 다음부터) — 2024-04 응답 표본으로 검증됨.
_MIN_TRAILING_CELLS = 5  # 하이라이트, 중계사, (빈칸), 구장, 상태


def _parse_play_cell(html: str) -> tuple[str | None, str | None, int | None, int | None]:
    """ "<span>A</span><em>...</em><span>B</span>" → (A, B, A점수, B점수).

    아직 경기 전이거나 취소된 경우 <em> 안이 "<span>vs</span>"뿐이라 점수가 없다 — 이때는
    점수 자리에 None을 넣지 0을 채우지 않는다(0점 경기와 구분되지 않게 되므로).
    """
    match = _PLAY_CELL_PATTERN.match(html)
    if not match:
        return None, None, None, None
    left, mid, right = match.groups()
    score_match = _PLAY_SCORE_PATTERN.match(mid)
    if not score_match:
        return left or None, right or None, None, None
    left_score, right_score = score_match.groups()
    return left, right, int(left_score), int(right_score)


def _parse_schedule_response(payload: dict, season_id: int) -> list[dict]:
    """payload → [{date, time, game_id, team_left, team_right, score_left, score_right,
    broadcaster, stadium, status}, ...].

    응답은 요일이 아니라 "그날 첫 경기 행에만 날짜 셀이 붙고, 같은 날 나머지 경기는 날짜
    셀 없이 이어지는" 그리드다 — `current_date`로 마지막으로 본 날짜를 들고 다닌다.
    구조가 가정과 다른 행(셀 개수가 안 맞는 등)은 조용히 건너뛰지 않고 경고 로그를 남긴다
    — "표본 부족 구간에 값을 채우지 않는다" 원칙의 연장.
    """
    games: list[dict] = []
    current_date: str | None = None

    for row_obj in payload.get("rows", []):
        cells = row_obj.get("row", [])
        if cells and cells[0].get("Class") == "day":
            day_match = _DAY_CELL_PATTERN.match(cells[0].get("Text", ""))
            if day_match:
                month, day = day_match.groups()
                current_date = f"{season_id}-{month}-{day}"
            cells = cells[1:]

        if current_date is None:
            logger.warning("날짜를 특정하지 못한 행을 건너뜁니다: %s", cells)
            continue
        if len(cells) < 3 + _MIN_TRAILING_CELLS:
            logger.warning("예상보다 셀이 적은 행을 건너뜁니다(%d개): %s", len(cells), cells)
            continue

        time_cell, play_cell, relay_cell, *trailing = cells
        _highlight_cell, broadcaster_cell, _blank_cell, stadium_cell, status_cell = trailing[:5]

        time_match = _TIME_CELL_PATTERN.search(time_cell.get("Text", ""))
        game_id_match = _GAME_ID_PATTERN.search(relay_cell.get("Text") or "")
        left, right, left_score, right_score = _parse_play_cell(play_cell.get("Text", ""))

        games.append(
            {
                "date": current_date,
                "time": time_match.group(1) if time_match else None,
                "game_id": game_id_match.group(1) if game_id_match else None,
                "team_left": left,
                "team_right": right,
                "score_left": left_score,
                "score_right": right_score,
                "broadcaster": broadcaster_cell.get("Text") or None,
                "stadium": stadium_cell.get("Text") or None,
                # "-" = 정상 진행, 그 외(우천취소/미세먼지취소 등)는 취소 사유 원문 그대로.
                "status": status_cell.get("Text") or None,
            }
        )

    return games


def check_schema(season_id: int = 2024, game_month: str = "04") -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    payload = _fetch_month(season_id, game_month)
    out_path = RAW_DIR / f"_schema_check_{season_id}{game_month}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def backfill(seasons: list[int]) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for season_id in seasons:
        for month in range(1, 13):
            game_month = f"{month:02d}"
            payload = _fetch_month(season_id, game_month)
            games = _parse_schedule_response(payload, season_id)
            out_path = RAW_DIR / f"kbo_{season_id}{game_month}.json"
            out_path.write_text(json.dumps(games, ensure_ascii=False), encoding="utf-8")
            logger.info("저장 완료: %s (%d건)", out_path, len(games))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-schema",
        action="store_true",
        help="1개월치만 호출해 원문 응답을 저장하고 종료 (하드 룰의 스키마 확인 예외)",
    )
    parser.add_argument("--seasons", type=int, nargs="+", default=[2024, 2025])
    parser.add_argument("--yes", action="store_true", help="실제로 전체 백필을 실행한다")
    args = parser.parse_args()

    if args.check_schema:
        out_path = check_schema()
        logger.info(
            "스키마 확인용 응답 저장: %s — 열어보고 _parse_schedule_response()를 채우세요.",
            out_path,
        )
        return

    n_calls = len(args.seasons) * 12
    logger.info("시즌 %s, 예상 호출 %d회 (시즌당 12개월)", args.seasons, n_calls)

    if not args.yes:
        logger.info("dry-run입니다. 실제로 실행하려면 --yes를 붙이세요.")
        return

    backfill(args.seasons)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    main()
