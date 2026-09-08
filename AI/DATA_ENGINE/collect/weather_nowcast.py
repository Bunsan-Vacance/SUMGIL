"""기상청 초단기실황/초단기예보 폴링 (서울 격자좌표 기준).

실황(getUltraSrtNcst)과 예보(getUltraSrtFcst)는 매시 발표 시각이 달라 별도 컬럼(source=
"observed"/"forecast")으로 저장한다. 항목: 기온(T1H), 강수량(RN1), 습도(REH), 풍속(WSD),
강수형태(PTY).

격자좌표는 서울 종로구 기준 기본값(nx=60, ny=127)을 쓴다 — 다른 지점이 필요하면 인자로 override.

실행:
    cd AI
    python -m DATA_ENGINE.collect.weather_nowcast
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

import pandas as pd
import requests

from DATA_ENGINE.collect.common import (
    EXTERNAL_WEATHER_RAW,
    env,
    http_retry,
    now_kst,
    save_partitioned_parquet,
)

logger = logging.getLogger("weather_nowcast")

# 기상청 API허브(authKey 인증) 엔드포인트. 공공데이터포털(data.go.kr, serviceKey 인증)과는
# 별개 시스템이라 혼동 주의 — apihub 발급 키는 이쪽에서만 동작한다.
BASE_URL = "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0"
DEFAULT_NX = 60
DEFAULT_NY = 127
POLL_INTERVAL_SEC = (
    600  # 실황/예보 갱신 주기(시간 단위)에 비해 60초는 과하다 — 10분 기본값, 필요시 조정
)

ITEMS_KEEP = {"T1H", "RN1", "REH", "WSD", "PTY"}


def _ncst_base_datetime(now: datetime) -> tuple[str, str]:
    # 초단기실황: 매시 정각 발표, 약 40분 이후부터 안정적으로 조회 가능.
    candidate = now.replace(minute=0, second=0, microsecond=0)
    if now < candidate + timedelta(minutes=40):
        candidate -= timedelta(hours=1)
    return candidate.strftime("%Y%m%d"), candidate.strftime("%H%M")


def _fcst_base_datetime(now: datetime) -> tuple[str, str]:
    # 초단기예보: 매시 30분 발표, 약 45분 이후부터 안정적으로 조회 가능.
    candidate = now.replace(minute=30, second=0, microsecond=0)
    if now < candidate + timedelta(minutes=15):
        candidate -= timedelta(hours=1)
    return candidate.strftime("%Y%m%d"), candidate.strftime("%H%M")


@http_retry
def _call(endpoint: str, nx: int, ny: int, base_date: str, base_time: str) -> dict:
    params = {
        "authKey": env("KMA_API_KEY"),
        "dataType": "JSON",
        "numOfRows": "100",
        "pageNo": "1",
        "base_date": base_date,
        "base_time": base_time,
        "nx": nx,
        "ny": ny,
    }
    resp = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _items_to_df(body: dict, source: str) -> pd.DataFrame:
    items = body.get("response", {}).get("body", {}).get("items", {}).get("item", [])
    rows = [it for it in items if it.get("category") in ITEMS_KEEP]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["source"] = source
    df["collected_at"] = now_kst()
    return df


def fetch_snapshot(nx: int = DEFAULT_NX, ny: int = DEFAULT_NY) -> pd.DataFrame:
    now = now_kst()
    ncst_date, ncst_time = _ncst_base_datetime(now)
    fcst_date, fcst_time = _fcst_base_datetime(now)

    ncst = _items_to_df(_call("getUltraSrtNcst", nx, ny, ncst_date, ncst_time), source="observed")
    fcst = _items_to_df(_call("getUltraSrtFcst", nx, ny, fcst_date, fcst_time), source="forecast")
    return pd.concat([ncst, fcst], ignore_index=True)


def run_once(nx: int = DEFAULT_NX, ny: int = DEFAULT_NY) -> None:
    df = fetch_snapshot(nx, ny)
    if df.empty:
        logger.warning("초단기실황/예보 응답이 비어 있습니다")
        return
    out_path = save_partitioned_parquet(
        df, EXTERNAL_WEATHER_RAW / "nowcast", df["collected_at"].iloc[0]
    )
    logger.info("저장 완료: %s (%d rows)", out_path, len(df))


def run_forever(interval: int = POLL_INTERVAL_SEC) -> None:
    logger.info("초단기실황/예보 폴링 시작 (간격=%ds)", interval)
    while True:
        started = time.monotonic()
        try:
            run_once()
        except Exception:
            logger.exception("폴링 1회 실패, 다음 주기에 재시도")
        elapsed = time.monotonic() - started
        time.sleep(max(0.0, interval - elapsed))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    run_forever()
