"""날짜 → dow_type(요일유형) 파생, 5분 슬롯 → 30분 슬롯 변환.

BE `bike_stock_pred` 스키마의 `dow_type`(0 평일 / 1 토 / 2 일·공휴일)을 계산한다.
CROWD의 `day_type`(평일/토요일/일요일/휴일 4분류)과는 분류 체계가 달라 그 모듈을
재사용하지 않는다 — 토요일을 먼저 판정하므로 공휴일 캘린더가 토요일도 Y로 잡아도
문제없다(`data/EXTERNAL/holiday/interim/holiday_calendar.parquet`, 사립학교교직원연금공단
공휴일 자료, 1980~2035 커버 — CROWD의 `calendar.load_holidays()`와 같은 파일을 쓴다).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_HOLIDAY_PATH = (
    AI_ROOT / "data" / "EXTERNAL" / "holiday" / "interim" / "holiday_calendar.parquet"
)

SLOT_MINUTES_5M = 5
SLOTS_PER_DAY_30M = 48


def load_holidays(path: Path = DEFAULT_HOLIDAY_PATH) -> pd.DataFrame:
    """date·is_holiday 두 컬럼. 파일이 없으면 빈 프레임(전부 비공휴일 취급)."""
    path = Path(path)
    if not path.exists():
        return pd.DataFrame({"date": pd.to_datetime([]), "is_holiday": pd.Series([], dtype=bool)})
    hol = pd.read_parquet(path)[["date", "is_holiday"]]
    hol["date"] = pd.to_datetime(hol["date"]).dt.normalize()
    return hol


def attach_dow_type(frame: pd.DataFrame, holidays: pd.DataFrame | None = None) -> pd.DataFrame:
    """`date`(정규화된 날짜) 컬럼에 `dow_type`(0/1/2)을 붙인다.

    우선순위: 토요일(1) → 일요일 또는 공휴일(2) → 평일(0). 토요일을 먼저 걸러서
    공휴일 캘린더가 최신 5일제 기준으로 토요일도 Y로 잡는 것과 충돌하지 않는다.
    """
    if holidays is None:
        holidays = load_holidays()
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    merged = out[["date"]].merge(holidays, on="date", how="left")
    is_holiday = merged["is_holiday"].fillna(False).to_numpy()
    dow = out["date"].dt.dayofweek
    dow_type = pd.Series(0, index=out.index, dtype="int8")
    dow_type[dow == 5] = 1
    is_sunday_or_holiday = (dow == 6) | is_holiday
    dow_type[(dow != 5) & is_sunday_or_holiday] = 2
    out["dow_type"] = dow_type
    return out


def slot_5m_to_time_slot(slot_5m: pd.Series) -> pd.Series:
    """5분 슬롯(0~287, 내부 학습 데이터 기준) → 30분 슬롯(0~47, BE bike_stock_pred 기준)."""
    return (slot_5m // 6).astype("int16")


def dow_type_for_date(when: date, holidays: pd.DataFrame) -> int:
    """단일 날짜용 dow_type. `attach_dow_type`과 완전히 같은 우선순위를 쓴다.

    토요일(1) → 일요일 또는 공휴일(2) → 평일(0). 순서를 바꾸면 토요일이면서
    공휴일인 날이 조용히 dow_type=2로 잘못 판정된다.
    """
    normalized = pd.Timestamp(when).normalize()

    if normalized.dayofweek == 5:
        return 1

    if holidays.empty:
        is_holiday = False
    else:
        matched = holidays.loc[holidays["date"] == normalized, "is_holiday"]
        if matched.empty:
            is_holiday = False
        else:
            is_holiday = bool(matched.iloc[0])

    if normalized.dayofweek == 6 or is_holiday:
        return 2

    return 0


def dow_type_and_time_slot(when: datetime, holidays: pd.DataFrame) -> tuple[int, int]:
    """실시간 서빙용: 임의 datetime → (dow_type, time_slot).

    time_slot 공식은 `features.py`의 `hour*2 + (minute>=30)`과 동일해야
    avg 표의 키(dow_type·time_slot)와 맞는다.
    """
    dow_type = dow_type_for_date(when.date(), holidays)

    if when.minute >= 30:
        half_hour = 1
    else:
        half_hour = 0

    time_slot = when.hour * 2 + half_hour
    return dow_type, time_slot


_holidays_cache: tuple[float, pd.DataFrame] | None = None


def get_holidays_cached(path: Path = DEFAULT_HOLIDAY_PATH) -> pd.DataFrame:
    """`load_holidays()`의 mtime 캐시 버전 — 실시간 요청마다 parquet을 다시 읽지 않는다."""
    global _holidays_cache

    resolved_path = Path(path)
    if not resolved_path.exists():
        return load_holidays(resolved_path)

    mtime = resolved_path.stat().st_mtime
    if _holidays_cache is not None and _holidays_cache[0] == mtime:
        return _holidays_cache[1]

    frame = load_holidays(resolved_path)
    _holidays_cache = (mtime, frame)
    return frame
