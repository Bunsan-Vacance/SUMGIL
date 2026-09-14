"""0-2 — 날씨(강수·기온)가 따릉이 재고에 실제로 신호를 주는지 가볍게 확인한다.

ASOS(기상청 지상관측, 지점 108=서울) 시간 자료를 `date`(+`hour`) 기준으로 netflow
산출물과 조인해서, 강수/비강수·기온 구간별 net_flow 차이를 본다. 예보가 아니라 **실측**
기준이다 — 예보 이력은 아직 없어서(0-1 확인됨) 이 단계에선 실측 기준 효과만 본다.

컬럼명이 기상청 다운로드 버전마다 조금씩 달라서(예: "강수량(mm)" vs "강수량"), 실행하면
먼저 실제 컬럼명을 출력한다 — 안 맞으면 COL_MAP만 고치면 됨.

실행:
    cd AI
    PYTHONPATH=. PYTHONIOENCODING=utf-8 python validation/BYC/lightgbm-stock-conversion-check/src/weather_effect_check.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.BIKE.pipeline.dataset import monthly_paths

AI_ROOT = Path(__file__).resolve().parents[4]
ASOS_DIR = AI_ROOT / "data" / "EXTERNAL" / "weather" / "raw" / "asos"
ASOS_FILES = [
    "SURFACE_ASOS_108_HR_2024_2024_2025.csv",
    "SURFACE_ASOS_108_HR_2025_2025_2026.csv",
]

# 기상청 CSV 컬럼명이 파일마다 다를 수 있어 후보를 여러 개 둔다.
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
        if not path.exists():
            raise FileNotFoundError(f"{path} 없음 — Drive에서 받아서 넣어야 함")
        try:
            df = pd.read_csv(path, encoding="cp949")
        except UnicodeDecodeError:
            df = pd.read_csv(path, encoding="utf-8-sig")
        frames.append(df)
    raw = pd.concat(frames, ignore_index=True)
    print(f"[날씨] 원본 컬럼: {raw.columns.tolist()}")

    dt_col = _pick(raw, DATETIME_COL_CANDIDATES)
    temp_col = _pick(raw, TEMP_COL_CANDIDATES)
    rain_col = _pick(raw, RAIN_COL_CANDIDATES)

    out = raw[[dt_col, temp_col, rain_col]].rename(
        columns={dt_col: "datetime", temp_col: "temp", rain_col: "rain_mm"}
    )
    out["datetime"] = pd.to_datetime(out["datetime"])
    out["date"] = out["datetime"].dt.normalize()
    out["hour"] = out["datetime"].dt.hour
    out["rain_mm"] = out["rain_mm"].fillna(0.0)  # 결측=비 안 옴(기상청 관례)
    out["is_rain"] = out["rain_mm"] > 0
    return out[["date", "hour", "temp", "rain_mm", "is_rain"]]


def main() -> None:
    weather = load_asos()
    print(f"[날씨] {len(weather):,}행, 기간 {weather['date'].min().date()} ~ {weather['date'].max().date()}")

    all_paths = monthly_paths("train", None) + monthly_paths("valid", None) + monthly_paths("test", None)

    rows = []
    for p in all_paths:
        df = pd.read_parquet(p, columns=["date", "hour", "horizon_min", "target_net_flow"])
        df = df[df["horizon_min"] == 5]
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        merged = df.merge(weather, on=["date", "hour"], how="inner")
        rows.append(merged[["is_rain", "temp", "target_net_flow"]])

    combined = pd.concat(rows, ignore_index=True)
    print(f"\n[날씨] 조인된 행수: {len(combined):,}")

    print("\n[날씨] 강수 여부별 net_flow 평균/표준편차:")
    print(combined.groupby("is_rain")["target_net_flow"].agg(["mean", "std", "count"]).to_string())

    print("\n[날씨] 기온 구간별 net_flow 평균/표준편차:")
    combined["temp_bin"] = pd.cut(combined["temp"], bins=[-30, 0, 10, 20, 30, 45])
    print(combined.groupby("temp_bin", observed=True)["target_net_flow"].agg(["mean", "std", "count"]).to_string())


if __name__ == "__main__":
    main()


def activity_volume_check() -> None:
    """net_flow(순증감)는 비가 와도 안 변할 수 있지만, 대여+반납 '총량'(활동량) 자체는 줄어들 수 있다.
    사용자 지적대로 이걸 직접 확인한다."""
    weather = load_asos()
    all_paths = monthly_paths("train", None) + monthly_paths("valid", None) + monthly_paths("test", None)

    rows = []
    for p in all_paths:
        df = pd.read_parquet(
            p, columns=["date", "hour", "horizon_min", "target_rent_count", "target_return_count"]
        )
        df = df[df["horizon_min"] == 5]
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        merged = df.merge(weather, on=["date", "hour"], how="inner")
        merged["activity"] = merged["target_rent_count"] + merged["target_return_count"]
        rows.append(merged[["is_rain", "temp", "activity", "target_rent_count", "target_return_count"]])

    combined = pd.concat(rows, ignore_index=True)
    print(f"\n[활동량] 조인된 행수: {len(combined):,}")

    print("\n[활동량] 강수 여부별 (대여+반납) 총 활동량 평균/표준편차:")
    print(combined.groupby("is_rain")["activity"].agg(["mean", "std", "count"]).to_string())

    base = combined.loc[~combined["is_rain"], "activity"].mean()
    rain = combined.loc[combined["is_rain"], "activity"].mean()
    print(f"\n[활동량] 비 올 때 활동량 변화율: {(rain - base) / base:.1%}")

    print("\n[활동량] 강수 여부별 대여량/반납량 평균 (따로):")
    print(combined.groupby("is_rain")[["target_rent_count", "target_return_count"]].mean().to_string())

    print("\n[활동량] 기온 구간별 활동량 평균:")
    combined["temp_bin"] = pd.cut(combined["temp"], bins=[-30, 0, 10, 20, 30, 45])
    print(combined.groupby("temp_bin", observed=True)["activity"].agg(["mean", "std", "count"]).to_string())


if __name__ == "__main__":
    activity_volume_check()
