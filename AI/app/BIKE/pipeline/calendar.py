"""날짜 → dow_type(요일유형) 파생, 5분 슬롯 → 30분 슬롯 변환.

BE `bike_stock_pred` 스키마의 `dow_type`(0 평일 / 1 토 / 2 일·공휴일)을 계산한다.
CROWD의 `day_type`(평일/토요일/일요일/휴일 4분류)과는 분류 체계가 달라 그 모듈을
재사용하지 않는다 — 토요일을 먼저 판정하므로 공휴일 캘린더가 토요일도 Y로 잡아도
문제없다(`data/EXTERNAL/holiday/interim/holiday_calendar.parquet`, 사립학교교직원연금공단
공휴일 자료, 1980~2035 커버 — CROWD의 `calendar.load_holidays()`와 같은 파일을 쓴다).
"""

from __future__ import annotations

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
