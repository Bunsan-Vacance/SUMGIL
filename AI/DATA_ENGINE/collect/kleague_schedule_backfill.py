"""K리그 2024~2025 시즌 경기 일정·결과 백필 — 날짜, 구장, 홈/원정팀, 스코어.

요청 형태(URL·헤더·JSON 바디)는 실제 브라우저 Network 탭 캡처(2026-09-09, kleague.com
schedule.do에서 "Copy as cURL")로 확인된 값이다. KBO와 달리 바디가 그냥 JSON이라 훨씬
단순하다 — 다만 쿠키에 `JSESSIONID`가 있었던 걸 보면 세션이 필요할 가능성이 높아, KBO와
동일하게 일정 페이지를 먼저 GET해서 세션을 챙긴 뒤 POST하도록 짜뒀다(미검증 — 세션 없이
바로 POST해도 되는지는 --check-schema로 확인 안 됨. 401 등이 나면 이 가정이 틀린 것).

`leagueId`는 캡처 당시 "1"(K리그1로 추정). K리그2가 필요하면 실제 값을 확인해서
`LEAGUE_ID`를 바꾸거나 --league-id 인자로 넘길 것 — 이 파일에서는 확인 못 했다.

응답은 `data.scheduleList`에 경기당 하나씩 깔끔한 레코드로 온다(KBO처럼 HTML 조각을 셀에
욱여넣은 그리드가 아니다) — 2024-04 응답으로 확인됨(2026-09-09). **관중수(`audienceQty`)도
포함돼 있다** — KBO 엔드포인트에는 없던 필드라 K리그 쪽에서만 얻을 수 있다. `gameStatus`는
표본에서 전부 "FE"(완료로 추정)만 나와 다른 값(예정/취소 등 코드)은 확인하지 못했다 —
원문 코드를 그대로 남겨두고 재해석하지 않는다.

실행:
    cd AI
    python -m DATA_ENGINE.collect.kleague_schedule_backfill --check-schema   # 1개월만 호출, 원문 저장
    python -m DATA_ENGINE.collect.kleague_schedule_backfill --seasons 2024 2025 --yes
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import requests

from DATA_ENGINE.collect.common import AI_ROOT, http_retry

logger = logging.getLogger("kleague_schedule_backfill")

BASE_URL = "https://www.kleague.com/getScheduleList.do"
SCHEDULE_PAGE_URL = "https://www.kleague.com/schedule.do"
LEAGUE_ID = "1"  # TODO: K리그2 등 다른 리그 코드는 미확인

RAW_DIR = AI_ROOT / "data" / "EXTERNAL" / "events" / "raw" / "kleague"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://www.kleague.com",
    "Referer": SCHEDULE_PAGE_URL,
    "Content-Type": "application/json; charset=UTF-8",
}

_session: requests.Session | None = None


def _get_session() -> requests.Session:
    """일정 페이지를 먼저 GET해서 세션 쿠키(JSESSIONID 등)를 챙긴 뒤 재사용한다.

    KBO 쪽에서 쿠키 없이 바로 POST하면 401이 났던 것과 같은 패턴을 예방적으로 적용한 것 —
    이 사이트에서 실제로 필요한지는 --check-schema로만 확인된다(세션 없이도 될 수 있다).
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
    """한 시즌·한 달치 일정을 호출한다. game_month는 "09"처럼 2자리 문자열."""
    session = _get_session()
    resp = session.post(
        BASE_URL,
        json={
            "leagueId": LEAGUE_ID,
            "teamId": "",
            "year": str(season_id),
            "month": game_month,
            "ticketYn": "",
        },
        headers=_HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _parse_schedule_response(payload: dict) -> list[dict]:
    """payload → [{date, time, game_id, round, home_team, away_team, home_score, away_score,
    stadium, attendance, status, broadcaster}, ...].

    `data.scheduleList`가 없거나 빈 응답이면(호출 실패를 raise_for_status가 못 잡는
    resultCode 기반 실패 등) 빈 리스트를 반환하지 않고 그대로 드러낸다 — resultCode가
    "200"이 아니면 KeyError 대신 명시적으로 에러를 낸다.
    """
    if payload.get("resultCode") != "200":
        raise RuntimeError(f"K리그 API 실패 응답: {payload.get('resultMsg')!r}")

    games = []
    for g in payload.get("data", {}).get("scheduleList", []):
        raw_date = g.get("gameDate", "")
        games.append(
            {
                "date": raw_date.replace(".", "-") if raw_date else None,
                "time": g.get("gameTime"),
                "game_id": g.get("gameId"),
                "round": g.get("roundId"),
                "home_team": g.get("homeTeamName"),
                "away_team": g.get("awayTeamName"),
                "home_score": g.get("homeGoal"),
                "away_score": g.get("awayGoal"),
                "stadium": g.get("fieldName"),
                "attendance": g.get("audienceQty"),
                # 원문 코드 그대로("FE" 등) — 의미를 다 확인하지 못해 재라벨링하지 않는다.
                "status": g.get("gameStatus"),
                "broadcaster": g.get("broadcastName"),
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
            games = _parse_schedule_response(payload)
            out_path = RAW_DIR / f"kleague_{season_id}{game_month}.json"
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
