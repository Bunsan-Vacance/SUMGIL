"""재학습 루프 공통 — 경로 상수·KST 시간·원자적 쓰기·JSON 입출력.

pandas/numpy와 표준 라이브러리만 쓴다(서빙 계층과 달리 무거운 의존성 없음).
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[4]
MONITORING_DIR = AI_ROOT / "data" / "CROWD" / "monitoring"
SCORE_DIR = MONITORING_DIR / "score_daily"
PRED_ARCHIVE_DIR = MONITORING_DIR / "pred_archive"
SERVING_DIR = AI_ROOT / "data" / "CROWD" / "serving"
# `dataset.RECENT_LONG_PATH`와 같은 경로다. dataset을 import하면 topology(yaml)·features까지
# 딸려 오므로 가볍게 유지하려고 여기서 다시 정의한다.
RECENT_LONG_PATH = AI_ROOT / "data" / "CROWD" / "interim" / "crowd_recent_ridership_long.parquet"
REQUEST_PATH = MONITORING_DIR / "retrain_request.json"
STATE_PATH = MONITORING_DIR / "retrain_state.json"
DEPLOY_STAMP_PATH = AI_ROOT / "DEPLOY_STAMP.json"

SCORE_PARQUET_NAME = "part.parquet"
SCORE_META_NAME = "part.meta.json"

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> pd.Timestamp:
    """현재 시각(KST, tz-aware)."""
    return pd.Timestamp(datetime.now(KST))


def today_kst() -> pd.Timestamp:
    """KST 기준 오늘 날짜(자정, tz 없음)."""
    return now_kst().tz_localize(None).normalize()


def parse_generated_at(value: str) -> pd.Timestamp:
    """`generated_at` 문자열을 KST tz-aware 시각으로 바꾼다. tz가 없으면 서울 시각으로 본다."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize(KST)
    return ts.tz_convert(KST)


def atomic_write_text(path: Path, text: str) -> None:
    """임시 파일에 쓴 뒤 `Path.replace`로 교체한다. 실패하면 임시 파일만 지운다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def atomic_write_parquet(df: pd.DataFrame, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        df.to_parquet(tmp, index=False)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def jsonable(obj: Any) -> Any:
    """numpy 스칼라·NaN·Timestamp를 JSON 직렬화 가능한 값으로 바꾼다(NaN/inf → None)."""
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [jsonable(v) for v in obj.tolist()]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        value = float(obj)
        return value if math.isfinite(value) else None
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    return obj


def write_json(path: Path, obj: Any) -> None:
    text = json.dumps(jsonable(obj), ensure_ascii=False, indent=1, default=str)
    atomic_write_text(path, text + "\n")


def read_json(path: Path) -> dict | None:
    """JSON 파일을 읽는다. 없거나 깨졌으면 None."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_deploy_stamp(path: Path = DEPLOY_STAMP_PATH) -> dict | None:
    """서버 파일 복사 배포가 남기는 `DEPLOY_STAMP.json`. 없으면 None."""
    return read_json(path)


def score_dir_for(date: pd.Timestamp, root: Path = SCORE_DIR) -> Path:
    return Path(root) / f"dt={pd.Timestamp(date):%Y-%m-%d}"
