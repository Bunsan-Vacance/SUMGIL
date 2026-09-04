"""데이터 수집 스크립트 공용 유틸 — 재시도, 시각, parquet 저장."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv()

KST = ZoneInfo("Asia/Seoul")
AI_ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = AI_ROOT / "data" / "raw"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


def now_kst() -> datetime:
    return datetime.now(KST)


def env(key: str, required: bool = True) -> str:
    value = os.environ.get(key, "")
    if required and not value:
        raise RuntimeError(f"환경변수 {key} 가 비어 있습니다. AI/.env를 확인하세요.")
    return value


# API허브·열린데이터광장 모두 일시적 5xx/타임아웃이 흔해 3회 재시도한다.
http_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)


def save_partitioned_parquet(df: pd.DataFrame, base_dir: Path, collected_at: datetime) -> Path:
    """dt=YYYY-MM-DD/hh=HH/ 파티션으로 parquet 저장. 파일명은 timestamp로 유일하게."""
    dt_str = collected_at.strftime("%Y-%m-%d")
    hh_str = collected_at.strftime("%H")
    out_dir = base_dir / f"dt={dt_str}" / f"hh={hh_str}"
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"snapshot_{collected_at.strftime('%Y%m%dT%H%M%S')}.parquet"
    out_path = out_dir / filename
    df.to_parquet(out_path, index=False)
    return out_path
