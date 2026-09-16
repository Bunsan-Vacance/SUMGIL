"""3단계 — 0단계에서 효과가 확인된 외부 피처만 조인한다.

**주의: 공휴일 세분화는 뺐다.** 원본(`사립학교교직원연금공단_공휴일 관리 정보`)을 다시
열어보니 `일자/공휴일여부(Y·N)/요일`뿐이고 명절·연휴전후 구분 자체가 없다 — 지금 쓰는
binary `is_holiday`가 우리가 가진 전부다.

채택된 피처 3종 (0단계 `RESULTS.md` 근거):

| 피처 | 학습값 | 서빙값 |
|---|---|---|
| `is_holiday` | 확정 | 확정(문제 없음) |
| `is_rain`, `temp` | ASOS 실측 | 예보 이력 없어 실측 기준만(한계로 명시, 검증 2는 보류) |
| `is_kbo_game_jamsil` | `kbo_games_with_attendance.parquet` | 동일(미래 일정도 확정돼 있음) — **잠실만**, 고척은 0단계에서 신호 약해 제외 |

산출물: `data/BIKE/interim/lightgbm_multisource_<월>.parquet` (도메인별 interim 디렉터리 관례,
`AI/CLAUDE.md`). 파생은 한 번만 붙이고 이후 4~5단계는 이 파일들을 읽기만 한다.

실행:
    cd AI
    PYTHONPATH=. PYTHONIOENCODING=utf-8 python validation/BYC/lightgbm-stock-conversion-check/src/join_multisource_features.py
    python validation/BYC/lightgbm-stock-conversion-check/src/join_multisource_features.py --months 202401  # 소규모 먼저
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from app.BIKE.pipeline.calendar import load_holidays
from app.BIKE.pipeline.dataset import monthly_paths

AI_ROOT = Path(__file__).resolve().parents[4]
VENUE_CONF = AI_ROOT / "DATA_ENGINE" / "conf" / "venue_coordinates.yaml"
KBO_PARQUET = (
    AI_ROOT / "data" / "EXTERNAL" / "events" / "processed" / "kbo_games_with_attendance.parquet"
)
ASOS_DIR = AI_ROOT / "data" / "EXTERNAL" / "weather" / "raw" / "asos"
ASOS_FILES = ["SURFACE_ASOS_108_HR_2024_2024_2025.csv", "SURFACE_ASOS_108_HR_2025_2025_2026.csv"]
OUT_DIR = AI_ROOT / "data" / "BIKE" / "interim"

EARTH_RADIUS_KM = 6371.0
JAMSIL_RADIUS_KM = 1.5


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def load_weather() -> pd.DataFrame:
    frames = []
    for name in ASOS_FILES:
        try:
            df = pd.read_csv(ASOS_DIR / name, encoding="cp949")
        except UnicodeDecodeError:
            df = pd.read_csv(ASOS_DIR / name, encoding="utf-8-sig")
        frames.append(df)
    raw = pd.concat(frames, ignore_index=True)
    out = raw[["일시", "기온(°C)", "강수량(mm)"]].rename(
        columns={"일시": "datetime", "기온(°C)": "temp", "강수량(mm)": "rain_mm"}
    )
    out["datetime"] = pd.to_datetime(out["datetime"])
    out["date"] = out["datetime"].dt.normalize()
    out["hour"] = out["datetime"].dt.hour
    out["rain_mm"] = out["rain_mm"].fillna(0.0)
    out["is_rain"] = out["rain_mm"] > 0
    return out[["date", "hour", "temp", "rain_mm", "is_rain"]]


def load_jamsil_game_dates() -> set:
    games = pd.read_parquet(KBO_PARQUET).dropna(subset=["attendance"])
    games = games[games["stadium"] == "잠실"]
    return set(pd.to_datetime(games["date"]).dt.normalize())


def jamsil_nearby_stations(sample_path: Path) -> set:
    conf = yaml.safe_load(VENUE_CONF.read_text(encoding="utf-8"))
    lat, lon = conf["kbo"]["잠실"]["lat"], conf["kbo"]["잠실"]["lon"]
    df = pd.read_parquet(sample_path, columns=["od_station_id", "lat_stock", "lon_stock"])
    df = df.drop_duplicates("od_station_id").dropna(subset=["lat_stock", "lon_stock"])
    d = haversine_km(df["lat_stock"].to_numpy(), df["lon_stock"].to_numpy(), lat, lon)
    return set(df.loc[d <= JAMSIL_RADIUS_KM, "od_station_id"])


def build_month(
    path: Path,
    weather: pd.DataFrame,
    holidays: pd.DataFrame,
    jamsil_dates: set,
    jamsil_stations: set,
) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()

    df = df.merge(weather, on=["date", "hour"], how="left")
    df = df.merge(holidays, on="date", how="left")
    df["is_holiday"] = df["is_holiday"].fillna(False)

    df["is_kbo_game_jamsil"] = df["od_station_id"].isin(jamsil_stations) & df["date"].isin(
        jamsil_dates
    )
    return df


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--months", nargs="+", default=None, help="YYYYMM 목록(생략 시 전체 train+valid+test)"
    )
    args = ap.parse_args(argv)

    weather = load_weather()
    holidays = load_holidays()
    jamsil_dates = load_jamsil_game_dates()

    # monthly_paths는 없는 조합이면 FileNotFoundError를 던지므로, prefix마다 개별 시도한다.
    all_paths = []
    for prefix in ("train", "valid", "test"):
        try:
            all_paths += monthly_paths(prefix, args.months)
        except FileNotFoundError:
            pass  # --months가 이 prefix엔 해당 없음(예: valid는 202412 하나뿐)

    jamsil_stations = jamsil_nearby_stations(all_paths[0])
    print(f"[3단계] 잠실 인근 역 {len(jamsil_stations)}개, KBO 경기일(잠실) {len(jamsil_dates)}건")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for p in all_paths:
        out = build_month(p, weather, holidays, jamsil_dates, jamsil_stations)
        out_path = OUT_DIR / f"lightgbm_multisource_{p.stem.split('_')[-1]}.parquet"
        out.to_parquet(out_path, index=False)
        print(f"  {p.name} -> {out_path.name} ({len(out):,}행)")
        del out


if __name__ == "__main__":
    main(sys.argv[1:])
