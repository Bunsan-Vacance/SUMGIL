"""기상청 API허브 ASOS 종관관측 시간자료 과거 2년치 백필 (서울, 지점 108).

하드 룰(AI/CLAUDE.md): 호출 횟수가 큰 백필성 스크립트는 실행 범위를 사용자와
맞춘 뒤에만 실제로 돌린다. 이 스크립트는 기본이 --dry-run이고, --yes를 명시적으로
줘야 실제 API 호출을 시작한다.

엔드포인트는 KMA API허브의 ASOS 시간자료 조회(kma_sfctm3)를 사용한다. API허브 문서상
파라미터·경로가 개정될 수 있으니, 최초 1회는 반드시 스키마 확인용 단건 호출로
응답 형식을 검증한 뒤 백필을 실행할 것.

실행:
    cd AI
    python -m DATA_ENGINE.collect.weather_asos_backfill                 # dry-run (호출 안 함)
    python -m DATA_ENGINE.collect.weather_asos_backfill --yes            # 실제 백필 실행
    python -m DATA_ENGINE.collect.weather_asos_backfill --start 2024-01-01 --end 2024-01-07 --yes  # 범위 좁혀 검증
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timedelta

import pandas as pd
import requests

from DATA_ENGINE.collect.common import EXTERNAL_WEATHER_RAW, env, http_retry, now_kst

logger = logging.getLogger("weather_asos_backfill")

BASE_URL = "https://apihub.kma.go.kr/api/typ01/url/kma_sfctm3.php"
STATION_ID = "108"  # 서울

# help=1 응답으로 확인한 kma_sfctm3 컬럼 순서 (46개 고정폭 필드).
COLUMNS = [
    "tm",
    "stn",
    "wd",
    "ws",
    "gst_wd",
    "gst_ws",
    "gst_tm",
    "pa",
    "ps",
    "pt",
    "pr",
    "ta",
    "td",
    "hm",
    "pv",
    "rn",
    "rn_day",
    "rn_jun",
    "rn_int",
    "sd_hr3",
    "sd_day",
    "sd_tot",
    "wc",
    "wp",
    "ww",
    "ca_tot",
    "ca_mid",
    "ch_min",
    "ct",
    "ct_top",
    "ct_mid",
    "ct_low",
    "vs",
    "ss",
    "si",
    "st_gd",
    "ts",
    "te_005",
    "te_01",
    "te_02",
    "te_03",
    "st_sea",
    "wh",
    "bf",
    "ir",
    "ix",
]


@http_retry
def _fetch_range(tm1: str, tm2: str) -> str:
    params = {
        "tm1": tm1,
        "tm2": tm2,
        "stn": STATION_ID,
        "help": "0",
        "authKey": env("KMA_API_KEY"),
    }
    resp = requests.get(BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.text


def _parse_asos_text(raw_text: str) -> pd.DataFrame:
    """kma_sfctm3 응답(공백 구분 텍스트)을 DataFrame으로. 결측값(-9, -9.0 등)은 그대로 둔다 —
    항목별 결측 코드가 달라(예: RN -9.0=무강수 아님/미관측 구분 필요) 일괄 NaN 치환은 하지 않음."""
    lines = [ln for ln in raw_text.splitlines() if ln and not ln.startswith("#")]
    rows = [ln.split() for ln in lines]
    df = pd.DataFrame(rows, columns=COLUMNS[: len(rows[0])] if rows else COLUMNS)

    numeric_cols = [
        c
        for c in df.columns
        if c not in {"tm", "wc", "wp", "ww", "ct", "ct_top", "ct_mid", "ct_low"}
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["tm"] = pd.to_datetime(df["tm"], format="%Y%m%d%H%M")

    return df


def backfill(start: date, end: date, chunk_days: int = 30) -> None:
    out_dir = EXTERNAL_WEATHER_RAW / "asos"
    out_dir.mkdir(parents=True, exist_ok=True)

    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
        tm1 = cursor.strftime("%Y%m%d0000")
        tm2 = chunk_end.strftime("%Y%m%d2300")

        logger.info("ASOS 조회: %s ~ %s", tm1, tm2)
        raw_text = _fetch_range(tm1, tm2)
        df = _parse_asos_text(raw_text)
        df["fetched_at"] = now_kst()

        out_path = (
            out_dir / f"asos_108_{cursor.strftime('%Y%m%d')}_{chunk_end.strftime('%Y%m%d')}.parquet"
        )
        df.to_parquet(out_path, index=False)
        logger.info("저장 완료: %s (%d rows)", out_path, len(df))

        cursor = chunk_end + timedelta(days=1)


def _estimate_calls(start: date, end: date, chunk_days: int) -> int:
    total_days = (end - start).days + 1
    return (total_days + chunk_days - 1) // chunk_days


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    today = now_kst().date()
    default_start = today - timedelta(days=365 * 2)
    parser.add_argument("--start", type=str, default=default_start.isoformat())
    parser.add_argument("--end", type=str, default=today.isoformat())
    parser.add_argument("--chunk-days", type=int, default=30)
    parser.add_argument("--yes", action="store_true", help="실제로 API를 호출해 백필을 실행한다")
    args = parser.parse_args()

    start = datetime.fromisoformat(args.start).date()
    end = datetime.fromisoformat(args.end).date()
    n_calls = _estimate_calls(start, end, args.chunk_days)

    logger.info("범위: %s ~ %s, chunk=%d일 → 예상 호출 %d회", start, end, args.chunk_days, n_calls)

    if not args.yes:
        logger.info("dry-run입니다. 실제로 실행하려면 --yes를 붙이세요.")
        return

    backfill(start, end, chunk_days=args.chunk_days)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    main()
