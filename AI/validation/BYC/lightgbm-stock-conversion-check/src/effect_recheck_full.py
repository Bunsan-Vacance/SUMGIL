"""0-2 재검증 — net_flow 평균만으로는 날씨 효과를 놓친다는 게 확인됐다(대여·반납이 같이
줄면 net_flow는 그대로라 신호가 안 보임). 그래서 세 지표를 같이 본다:

    1. net_flow 평균          — 재고가 느는 방향/주는 방향
    2. 활동량(대여+반납)       — 대여소가 얼마나 활발히 도는지(날씨에서 신호 발견된 지표)
    3. 미래 empty/full 발생률  — stock_anchor_hour + target_net_flow로 미래 재고를 만들어
                                 실제로 0대/만차가 됐는지(우리 최종 목표 p_empty/p_full과 직결)

날씨·공휴일은 전체 데이터에 적용되니 한 번의 순회로 같이 계산한다(62M행을 두 번 안 읽음,
`AI/CLAUDE.md` 원칙). KBO는 구장 근처 역만 대상이라 `kbo_effect_check.py`에서 별도로
같은 세 지표를 추가해 재확인한다.

실행:
    cd AI
    PYTHONPATH=. PYTHONIOENCODING=utf-8 python validation/BYC/lightgbm-stock-conversion-check/src/effect_recheck_full.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.BIKE.pipeline.calendar import load_holidays
from app.BIKE.pipeline.dataset import monthly_paths

# 폴더명에 하이픈이 있어 패키지 import가 안 됨 — weather_effect_check.py의 load_asos()를
# 그대로 복붙(같은 파일 재사용 대신 중복을 감수 — 이 검증 폴더 관례).
AI_ROOT = Path(__file__).resolve().parents[4]
ASOS_DIR = AI_ROOT / "data" / "EXTERNAL" / "weather" / "raw" / "asos"
ASOS_FILES = [
    "SURFACE_ASOS_108_HR_2024_2024_2025.csv",
    "SURFACE_ASOS_108_HR_2025_2025_2026.csv",
]
DATETIME_COL_CANDIDATES = ["일시", "TM"]
TEMP_COL_CANDIDATES = ["기온(°C)", "기온", "TA"]
RAIN_COL_CANDIDATES = ["강수량(mm)", "강수량", "RN"]


def _pick(df: pd.DataFrame, candidates: list[str]) -> str:
    for c in candidates:
        if c in df.columns:
            return c
    raise KeyError(f"컬럼 후보 {candidates} 중 실제 컬럼에 없음 — 실제 컬럼: {df.columns.tolist()}")


def load_asos() -> pd.DataFrame:
    frames = []
    for name in ASOS_FILES:
        path = ASOS_DIR / name
        try:
            df = pd.read_csv(path, encoding="cp949")
        except UnicodeDecodeError:
            df = pd.read_csv(path, encoding="utf-8-sig")
        frames.append(df)
    raw = pd.concat(frames, ignore_index=True)
    dt_col = _pick(raw, DATETIME_COL_CANDIDATES)
    temp_col = _pick(raw, TEMP_COL_CANDIDATES)
    rain_col = _pick(raw, RAIN_COL_CANDIDATES)
    out = raw[[dt_col, temp_col, rain_col]].rename(
        columns={dt_col: "datetime", temp_col: "temp", rain_col: "rain_mm"}
    )
    out["datetime"] = pd.to_datetime(out["datetime"])
    out["date"] = out["datetime"].dt.normalize()
    out["hour"] = out["datetime"].dt.hour
    out["rain_mm"] = out["rain_mm"].fillna(0.0)
    out["is_rain"] = out["rain_mm"] > 0
    return out[["date", "hour", "temp", "rain_mm", "is_rain"]]


NEEDED_COLS = [
    "date",
    "hour",
    "horizon_min",
    "stock_anchor_hour",
    "rack_count",
    "target_net_flow",
    "target_rent_count",
    "target_return_count",
]


def summarize(df: pd.DataFrame, group_col: str, label: str) -> None:
    print(f"\n=== {label} ({group_col}) ===")
    agg = df.groupby(group_col).agg(
        net_flow_mean=("target_net_flow", "mean"),
        activity_mean=("activity", "mean"),
        empty_rate=("is_empty_future", "mean"),
        full_rate=("is_full_future", "mean"),
        n=("target_net_flow", "size"),
    )
    print(agg.to_string())
    if len(agg) == 2:
        base, other = agg.iloc[0], agg.iloc[1]
        print(
            f"  -> 활동량 변화율 {(other['activity_mean'] - base['activity_mean']) / base['activity_mean']:.1%}, "
            f"empty_rate 변화 {other['empty_rate'] - base['empty_rate']:+.4f}, "
            f"full_rate 변화 {other['full_rate'] - base['full_rate']:+.4f}"
        )


def main() -> None:
    weather = load_asos()
    holidays = load_holidays()
    all_paths = monthly_paths("train", None) + monthly_paths("valid", None) + monthly_paths("test", None)

    rows = []
    for p in all_paths:
        df = pd.read_parquet(p, columns=NEEDED_COLS)
        df = df.dropna(subset=["stock_anchor_hour", "target_net_flow"])
        df = df[df["horizon_min"] == 5]
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()

        df["activity"] = df["target_rent_count"] + df["target_return_count"]
        future_stock = df["stock_anchor_hour"] + df["target_net_flow"]
        df["is_empty_future"] = future_stock <= 0
        df["is_full_future"] = future_stock >= df["rack_count"]

        df = df.merge(weather, on=["date", "hour"], how="left")
        df = df.merge(holidays, on="date", how="left")
        df["is_holiday"] = df["is_holiday"].fillna(False)

        rows.append(df[["is_rain", "temp", "is_holiday", "activity", "target_net_flow", "is_empty_future", "is_full_future"]])

    combined = pd.concat(rows, ignore_index=True)
    print(f"[재검증] 전체 {len(combined):,}행")

    summarize(combined, "is_rain", "강수 여부")
    combined["temp_bin"] = pd.cut(combined["temp"], bins=[-30, 0, 10, 20, 30, 45])
    summarize(combined, "temp_bin", "기온 구간")
    summarize(combined, "is_holiday", "공휴일 여부")


if __name__ == "__main__":
    main()
