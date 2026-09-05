"""따릉이 실시간 대여소 재고 폴링.

60초 간격으로 bikeList 전체(약 2,700개소, 1회 최대 1000건)를 3번 나눠 호출해 합치고,
data/raw/bike/realtime/dt=YYYY-MM-DD/hh=HH/snapshot_*.parquet 로 저장한다.

실행:
    cd AI
    python -m DATA_ENGINE.collect.bike_realtime
"""

from __future__ import annotations

import logging
import time

import pandas as pd
import requests

from DATA_ENGINE.collect.common import (
    DATA_RAW,
    env,
    http_retry,
    now_kst,
    save_partitioned_parquet,
)

logger = logging.getLogger("bike_realtime")

BASE_URL = "http://openapi.seoul.go.kr:8088"
PAGE_SIZE = 1000
TOTAL_PAGES = 3  # 1-1000, 1001-2000, 2001-3000 (대여소 약 2,700개소 커버)
POLL_INTERVAL_SEC = 60

FIELDS = [
    "stationId",
    "stationName",
    "rackTotCnt",
    "parkingBikeTotCnt",
    "shared",
    "stationLatitude",
    "stationLongitude",
]


def _api_key() -> str:
    # bikeList 전용 키가 있으면 우선 사용, 없으면 일반 인증키로 대체.
    key = env("SEOUL_BIKE_KEY", required=False)
    return key or env("SEOUL_API_KEY")


@http_retry
def _fetch_page(start: int, end: int) -> list[dict]:
    url = f"{BASE_URL}/{_api_key()}/json/bikeList/{start}/{end}/"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    body = resp.json()

    result = body.get("rentBikeStatus", {}).get("RESULT", {})
    code = result.get("CODE", "")
    if code and code != "INFO-000":
        raise RuntimeError(f"bikeList 응답 오류: {code} {result.get('MESSAGE')}")

    return body.get("rentBikeStatus", {}).get("row", [])


def fetch_snapshot() -> pd.DataFrame:
    rows: list[dict] = []
    for page in range(TOTAL_PAGES):
        start = page * PAGE_SIZE + 1
        end = start + PAGE_SIZE - 1
        rows.extend(_fetch_page(start, end))

    collected_at = now_kst()
    df = pd.DataFrame(rows)
    if df.empty:
        logger.warning("bikeList 응답이 비어 있습니다 (collected_at=%s)", collected_at)
        return df

    df = df[[c for c in FIELDS if c in df.columns]].copy()

    numeric_cols = [
        "rackTotCnt",
        "parkingBikeTotCnt",
        "shared",
        "stationLatitude",
        "stationLongitude",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["collected_at"] = collected_at
    return df


def run_once() -> None:
    df = fetch_snapshot()
    if df.empty:
        return
    out_path = save_partitioned_parquet(
        df, DATA_RAW / "bike" / "realtime", df["collected_at"].iloc[0]
    )
    logger.info("저장 완료: %s (%d개소)", out_path, len(df))


def run_forever(interval: int = POLL_INTERVAL_SEC) -> None:
    logger.info("따릉이 실시간 재고 폴링 시작 (간격=%ds)", interval)
    while True:
        started = time.monotonic()
        try:
            run_once()
        except Exception:
            # 하드 룰: 폴링은 실패해도 프로세스가 죽으면 안 된다 — 로그만 남기고 다음 주기로.
            logger.exception("폴링 1회 실패, 다음 주기에 재시도")

        elapsed = time.monotonic() - started
        time.sleep(max(0.0, interval - elapsed))


if __name__ == "__main__":
    run_forever()
