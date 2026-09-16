"""서울교통공사 역별 시간대별 승하차인원 D−1 일 배치 수집 — 열린데이터광장 `getStnPsgr`(OA-22723).

왜 필요한가. 배포 모델(lookup + LightGBM 잔차)의 개선폭은 전날·1주 전·같은 요일유형 직전 날 시차 피처에서
나온다. 패널은 연간 CSV라 2025-12-31에서 끝나고, 2026 실제 날짜로 배치 예측을 돌리면 이력 7일이 비어
시차가 전부 NaN → lookup + 이벤트 수준으로 퇴화한다. 이 수집기는 그 이력을 매일 채우는 **유일한 원천**이다.
학습 데이터(패널)는 바꾸지 않는다 — `app/CROWD/pipeline/dataset.extend_panel_with_recent`가 배치 예측 때
패널 뒤에 이어 붙인다.

원천 특성(2026-09-12~13 직접 확인, 143 RESULTS.md)
- URL `http://openapi.seoul.go.kr:8088/{KEY}/json/getStnPsgr/{start}/{end}/{YYYYMMDD}`. 봉투는 data.go.kr식
  `response.header.resultCode("00")` / `response.body.{items.item[], pageNo, numOfRows, totalCount}`.
- 한 번에 최대 1000건. 초과하면 JSON이 아닌 `<RESULT><CODE>ERROR-336</CODE>…` 텍스트가 온다.
- **지연 D−1, 보존 창 정확히 7일.** 창 밖 날짜는 resultCode 00에 totalCount 0. 매일 받지 않으면 영구 결손이라
  기본 실행은 어제부터 7일 중 **누적 파일에 없는 날짜만** 받는다(놓친 날이 있어도 창 안이면 자동 보충, 하루 ≈67회).
  `--refetch`면 창 안 날짜를 전부 다시 받아 교체한다. 누적 파일의 오래된 날짜는 지우지 않는다.
- 갱신 시각: 09-13 03:03에는 어제(09-12)치가 없었고 09-12 21:10에는 어제(09-11)치가 있었다 → 오전 중 어느 시각(미확정).
- 행은 역 × 시간 × 교통카드구분 × 사용자구분으로 갈라져 있어(하루 6.3~6.9만 행) 역×시간으로 **합산**한다.
- 패널 `station_no`는 API의 `stnCd`와 같다(`stnNo`는 `P549`처럼 비숫자값이 있어 쓰지 않는다).
- `pasngHr`는 "00"~"23"(24 없음). 심야 귀속은 `HOUR_TO_SLOT` — 1단계 점검(check_source.py)으로 확정.

출력
- 원문: `data/CROWD/raw/ridership_daily/dt=YYYY-MM-DD/getStnPsgr.parquet` (합산 전, 컬럼 그대로)
- 롱:   `data/CROWD/interim/crowd_recent_ridership_long.parquet` — `crowd_daily_ridership_long.parquet`과 같은 스키마
        (`date, line, station_no, station_name, direction, passengers, time_slot`) + `source, collected_at`.

실행:
    cd AI
    python -m DATA_ENGINE.collect.subway_ridership_daily --check-schema     # 1페이지만 받아 원문 저장(하드 룰 예외)
    python -m DATA_ENGINE.collect.subway_ridership_daily                    # dry-run: 호출 횟수만 출력
    python -m DATA_ENGINE.collect.subway_ridership_daily --days 7 --yes     # 어제부터 7일 중 아직 없는 날짜만(첫 실행 ≈460회, 이후 매일 ≈67회)
    python -m DATA_ENGINE.collect.subway_ridership_daily --date 20260911 --yes --refetch
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from DATA_ENGINE.collect.common import AI_ROOT, env, http_retry, now_kst, save_latest_parquet

logger = logging.getLogger("subway_ridership_daily")

BASE_URL = "http://openapi.seoul.go.kr:8088"
SERVICE = "getStnPsgr"
PAGE_SIZE = 1000
WINDOW_DAYS = 7
SOURCE = "getStnPsgr"

CROWD_RAW_DAILY = AI_ROOT / "data" / "CROWD" / "raw" / "ridership_daily"
RECENT_LONG = AI_ROOT / "data" / "CROWD" / "interim" / "crowd_recent_ridership_long.parquet"

RAW_COLUMNS = [
    "pasngDe",
    "pasngHr",
    "lineNm",
    "stnCd",
    "stnNo",
    "stnNm",
    "trnscdSeCd",
    "trnscdSeCdNm",
    "trnscdUserSeCd",
    "trnscdUserSeCdNm",
    "rideNope",
    "gffNope",
    "crtrYmd",
]
LONG_COLUMNS = [
    "date",
    "line",
    "station_no",
    "station_name",
    "direction",
    "passengers",
    "time_slot",
]


def hour_to_slot(hour: int) -> str:
    """API `pasngHr`(0~23) → 패널 20슬롯.

    서울교통공사 일별 CSV는 운행일 기준이라 `06시이전`(첫차~06시)과 `24시이후`(자정 넘어 막차까지)를 갖는다.
    API도 같은 집계를 시간으로 펼친 것이라 00~03시는 **같은 `pasngDe`의 `24~`**, 04~05시는 `~06`으로 둔다
    (143 1단계에서 00~05시 합계를 2025 같은 요일 `24~`·`~06` 평균과 비교해 확정).
    """
    if hour < 0 or hour > 23:
        raise ValueError(f"pasngHr 범위 밖: {hour}")
    if hour <= 3:
        return "24~"
    if hour <= 5:
        return "~06"
    return f"{hour:02d}-{hour + 1:02d}"


HOUR_TO_SLOT = {h: hour_to_slot(h) for h in range(24)}


def _api_key() -> str:
    return env("SEOUL_SUBWAY_KEY", required=False) or env("SEOUL_API_KEY")


def _url(day: str, start: int, end: int, fmt: str = "json") -> str:
    return f"{BASE_URL}/{_api_key()}/{fmt}/{SERVICE}/{start}/{end}/{day}"


def _parse_response(text: str) -> dict:
    """봉투를 벗겨 body(dict)를 돌려준다. 1000건 초과 등 오류는 JSON이 아닌 `<RESULT>` 텍스트로 온다."""
    stripped = text.lstrip()
    if stripped.startswith("<"):
        raise RuntimeError(f"getStnPsgr 오류 응답: {stripped[:200]}")
    payload = json.loads(stripped)
    resp = payload.get("response", payload)
    header = resp.get("header", {})
    if str(header.get("resultCode")) != "00":
        raise RuntimeError(
            f"getStnPsgr resultCode={header.get('resultCode')} {header.get('resultMsg')}"
        )
    return resp["body"]


@http_retry
def _fetch_page(day: str, start: int, end: int) -> dict:
    r = requests.get(_url(day, start, end), timeout=30)
    r.raise_for_status()
    return _parse_response(r.text)


def _body_rows(body: dict) -> list[dict]:
    items = body.get("items") or {}
    rows = items.get("item", []) if isinstance(items, dict) else items
    return rows or []


def fetch_day(day: str, page_size: int = PAGE_SIZE) -> pd.DataFrame:
    """하루치 전 페이지를 받아 원문 DataFrame으로. 0건이면 빈 DataFrame(창 밖이거나 아직 미갱신)."""
    first = _fetch_page(day, 1, page_size)
    total = int(first.get("totalCount") or 0)
    rows = _body_rows(first)
    if total == 0:
        logger.warning("%s: totalCount 0 — 보존 창(7일) 밖이거나 아직 갱신되지 않았습니다.", day)
        return pd.DataFrame(columns=RAW_COLUMNS)
    for start in range(page_size + 1, total + 1, page_size):
        rows += _body_rows(_fetch_page(day, start, min(start + page_size - 1, total)))
    df = pd.DataFrame(rows)
    if len(df) != total:
        logger.warning("%s: totalCount %d인데 받은 행 %d", day, total, len(df))
    return df.reindex(columns=[*RAW_COLUMNS, *[c for c in df.columns if c not in RAW_COLUMNS]])


def n_calls(total: int, page_size: int = PAGE_SIZE) -> int:
    return max(1, -(-total // page_size))


def to_long(raw: pd.DataFrame, collected_at: datetime | None = None) -> pd.DataFrame:
    """원문(카드·사용자 구분별) → 역×슬롯 합산 롱 포맷(`crowd_daily_ridership_long`과 같은 스키마)."""
    if raw.empty:
        return pd.DataFrame(columns=[*LONG_COLUMNS, "source", "collected_at"])
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(raw["pasngDe"].astype(str), format="%Y%m%d"),
            "line": raw["lineNm"].astype(str),
            "station_no": pd.to_numeric(raw["stnCd"], errors="raise").astype("int64"),
            "station_name": raw["stnNm"].astype(str),
            "time_slot": raw["pasngHr"].astype(int).map(HOUR_TO_SLOT),
            "boarding": pd.to_numeric(raw["rideNope"]).astype("float64"),
            "alighting": pd.to_numeric(raw["gffNope"]).astype("float64"),
        }
    )
    agg = (
        df.groupby(["date", "line", "station_no", "station_name", "time_slot"], as_index=False)[
            ["boarding", "alighting"]
        ]
        .sum()
        .melt(
            id_vars=["date", "line", "station_no", "station_name", "time_slot"],
            value_vars=["boarding", "alighting"],
            var_name="direction",
            value_name="passengers",
        )
    )
    agg["source"] = SOURCE
    agg["collected_at"] = pd.Timestamp(collected_at or now_kst()).tz_localize(None)
    return (
        agg[[*LONG_COLUMNS, "source", "collected_at"]]
        .sort_values(LONG_COLUMNS[:5])
        .reset_index(drop=True)
    )


def merge_recent(existing: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    """같은 날짜는 새 값으로 교체, 다른 날짜는 유지. 보존 창 밖 과거 날짜를 지우지 않는다(누적이 목적)."""
    if existing is None or existing.empty:
        return new.reset_index(drop=True)
    keep = existing[~existing["date"].isin(new["date"].unique())]
    return (
        pd.concat([keep, new], ignore_index=True)
        .sort_values(LONG_COLUMNS[:5])
        .reset_index(drop=True)
    )


def save_raw(raw: pd.DataFrame, day: str) -> Path:
    d = date(int(day[:4]), int(day[4:6]), int(day[6:8]))
    out_dir = CROWD_RAW_DAILY / f"dt={d.isoformat()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{SERVICE}.parquet"
    raw.to_parquet(path, index=False)
    return path


def default_days(n: int = WINDOW_DAYS, today: date | None = None) -> list[str]:
    """어제부터 n일(원천 보존 창) — 최신 날짜 먼저."""
    today = today or now_kst().date()
    return [(today - timedelta(days=i)).strftime("%Y%m%d") for i in range(1, n + 1)]


def already_have(days: list[str], recent_path: Path | None = None) -> set[str]:
    """누적 파일에 이미 있는 날짜(YYYYMMDD). 기본 실행은 이 날짜를 건너뛰어 하루 ≈67회만 호출한다."""
    path = recent_path or RECENT_LONG
    if not path.exists():
        return set()
    have = pd.read_parquet(path, columns=["date"])["date"].dt.strftime("%Y%m%d").unique()
    return set(days) & set(have)


def run(days: list[str], refetch: bool = False) -> pd.DataFrame:
    collected_at = now_kst()
    skip = set() if refetch else already_have(days)
    if skip:
        logger.info(
            "이미 있는 날짜 %d개 건너뜀(--refetch로 다시 받음): %s", len(skip), sorted(skip)
        )
    longs = []
    for day in days:
        if day in skip:
            continue
        raw = fetch_day(day)
        if raw.empty:
            continue
        save_raw(raw, day)
        lg = to_long(raw, collected_at)
        longs.append(lg)
        logger.info(
            "%s: 원문 %d행 → 역×슬롯 %d행 (역 %d)",
            day,
            len(raw),
            len(lg),
            lg["station_no"].nunique(),
        )
    if not longs:
        logger.warning("새로 받은 날짜가 없습니다 — 파일을 바꾸지 않습니다.")
        return (
            pd.read_parquet(RECENT_LONG)
            if RECENT_LONG.exists()
            else pd.DataFrame(columns=[*LONG_COLUMNS, "source", "collected_at"])
        )
    new = pd.concat(longs, ignore_index=True)
    existing = pd.read_parquet(RECENT_LONG) if RECENT_LONG.exists() else None
    merged = merge_recent(existing, new)
    save_latest_parquet(merged, RECENT_LONG)
    logger.info(
        "저장: %s — 날짜 %d개 (%s ~ %s), %d행",
        RECENT_LONG,
        merged["date"].nunique(),
        merged["date"].min().date(),
        merged["date"].max().date(),
        len(merged),
    )
    return merged


def check_schema(day: str) -> Path:
    CROWD_RAW_DAILY.mkdir(parents=True, exist_ok=True)
    body = _fetch_page(day, 1, 5)
    path = CROWD_RAW_DAILY / f"_schema_check_{day}.json"
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "totalCount=%s (하루 예상 호출 %d회) → %s",
        body.get("totalCount"),
        n_calls(int(body.get("totalCount") or 0)),
        path,
    )
    return path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--days",
        type=int,
        default=WINDOW_DAYS,
        help="어제부터 며칠치를 받을지(기본 7 = 원천 보존 창)",
    )
    ap.add_argument("--date", default=None, help="단일 날짜 YYYYMMDD (--days 대신)")
    ap.add_argument(
        "--check-schema",
        action="store_true",
        help="5건만 받아 원문 저장 후 종료(하드 룰의 스키마 확인 예외)",
    )
    ap.add_argument(
        "--refetch", action="store_true", help="누적 파일에 이미 있는 날짜도 다시 받아 교체한다"
    )
    ap.add_argument("--yes", action="store_true", help="실제로 수집한다(없으면 dry-run)")
    args = ap.parse_args(argv)

    days = [args.date] if args.date else default_days(args.days)
    if args.check_schema:
        check_schema(days[0])
        return
    todo = days if args.refetch else [d for d in days if d not in already_have(days)]
    logger.info(
        "대상 %d일 %s … %s 중 새로 받을 날짜 %d일, 예상 호출 ≈ %d회(하루 64~70페이지)",
        len(days),
        days[0],
        days[-1],
        len(todo),
        len(todo) * 67,
    )
    if not args.yes:
        logger.info("dry-run입니다. 실제로 실행하려면 --yes를 붙이세요.")
        return
    run(days, refetch=args.refetch)


if __name__ == "__main__":
    main()
