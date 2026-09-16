"""날짜 → 요일유형(day_type) 파생. 서빙 배치가 미래 날짜의 패널 골격을 만들 때 쓴다.

`DATA_ENGINE/eda/build_crowd_panel.attach_calendar`와 같은 규칙이다(그 docstring에 버그 경위가 있다):
- 토요일→"토요일", 일요일→"일요일", 평일 공휴일→"휴일", 나머지→"평일".
- 휴일 달력(`holiday_calendar.parquet`)의 `is_holiday`는 학교 휴업일 기준이라 주말이 대부분 Y다.
  그래서 **평일(dow<5)에 걸린 날만** 휴일로 덮어쓴다 — 이 가드가 없으면 토·일이 전부 "휴일"로
  흡수돼 lookup 키가 2종으로 줄어든다(88에서 잡은 버그).
- 달력 파일에 없는 날짜(미래)는 `is_holiday`를 False로 본다 — 공휴일 갱신이 안 됐을 수 있으니
  배치 메타에 "달력 커버리지 끝 날짜"를 함께 기록한다.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_HOLIDAY_PATH = (
    AI_ROOT / "data" / "EXTERNAL" / "holiday" / "interim" / "holiday_calendar.parquet"
)

WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


def load_holidays(path: Path = DEFAULT_HOLIDAY_PATH) -> pd.DataFrame:
    """date·is_holiday 두 컬럼. 파일이 없으면 빈 프레임(전부 비공휴일 취급)."""
    path = Path(path)
    if not path.exists():
        return pd.DataFrame({"date": pd.to_datetime([]), "is_holiday": pd.Series([], dtype=bool)})
    hol = pd.read_parquet(path)[["date", "is_holiday"]]
    hol["date"] = pd.to_datetime(hol["date"]).dt.normalize()
    return hol


def attach_calendar(frame: pd.DataFrame, holidays: pd.DataFrame | None = None) -> pd.DataFrame:
    """`date` 컬럼에 dow·weekday_ko·is_weekend·is_holiday·day_type을 붙인다."""
    if holidays is None:
        holidays = load_holidays()
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    out = out.merge(holidays, on="date", how="left")
    out["is_holiday"] = out["is_holiday"].fillna(False).astype(bool)
    out["dow"] = out["date"].dt.dayofweek
    out["weekday_ko"] = out["dow"].map(lambda d: WEEKDAY_KO[d])
    out["is_weekend"] = out["dow"] >= 5
    out["day_type"] = "평일"
    out.loc[out["dow"] == 5, "day_type"] = "토요일"
    out.loc[out["dow"] == 6, "day_type"] = "일요일"
    out.loc[out["is_holiday"] & (out["dow"] < 5), "day_type"] = "휴일"
    return out


def holiday_coverage_end(holidays: pd.DataFrame) -> pd.Timestamp | None:
    return None if holidays.empty else pd.Timestamp(holidays["date"].max())
