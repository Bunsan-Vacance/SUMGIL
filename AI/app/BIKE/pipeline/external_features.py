"""날짜축 멀티소스 모델(B4-2)용 외부 피처 — 날씨(ASOS 실측)·KBO(잠실)·공휴일.

0단계에서 net_flow 평균만으로는 놓쳤다가, 활동량·미래 empty/full 발생률까지 같이 보고서야
효과를 확인한 세 피처만 채택했다(`validation/BYC/lightgbm-stock-conversion-check/RESULTS.md`).
공휴일 세분화(명절/연휴전후)는 원본에 그 구분이 없어서 binary만 쓴다. 유동인구는 raw
데이터 시기(2026년)가 학습·평가 기간(2024~2025)과 안 맞아 제외했다.

**학습/서빙 값 출처가 다르다**(계획서 3단계):

| 피처 | 학습 | 서빙 |
|---|---|---|
| 날씨 | ASOS 실측 | 예보 이력 없음(수집기 배포 최근) — 지금은 실측만 지원, 예보 연동은 후속 |
| KBO | 확정 일정 | 동일(미래 일정도 이미 확정) |
| 공휴일 | 확정 | 동일 |

구장 좌표는 CROWD가 만든 `DATA_ENGINE/conf/venue_coordinates.yaml`을 그대로 재사용한다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

AI_ROOT = Path(__file__).resolve().parents[3]
VENUE_CONF = AI_ROOT / "DATA_ENGINE" / "conf" / "venue_coordinates.yaml"
KBO_PARQUET = (
    AI_ROOT / "data" / "EXTERNAL" / "events" / "processed" / "kbo_games_with_attendance.parquet"
)
ASOS_DIR = AI_ROOT / "data" / "EXTERNAL" / "weather" / "raw" / "asos"
ASOS_FILES = ["SURFACE_ASOS_108_HR_2024_2024_2025.csv", "SURFACE_ASOS_108_HR_2025_2025_2026.csv"]

EARTH_RADIUS_KM = 6371.0
JAMSIL_STADIUM_NAME = "잠실"


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def load_weather() -> pd.DataFrame:
    """ASOS 지점108(서울) 시간 실측. 컬럼: date, hour, temp, rain_mm, is_rain."""
    frames = []
    for name in ASOS_FILES:
        path = ASOS_DIR / name
        if not path.exists():
            raise FileNotFoundError(
                f"{path} 없음 — Drive data/EXTERNAL/weather/raw/asos/에서 받아야 함"
            )
        try:
            df = pd.read_csv(path, encoding="cp949")
        except UnicodeDecodeError:
            df = pd.read_csv(path, encoding="utf-8-sig")
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
    """관중수 있는(=실제 개최된) 잠실 홈경기 날짜 집합. 미래 일정도 확정돼 있어 서빙 시에도 동일하게 조회 가능."""
    if not KBO_PARQUET.exists():
        raise FileNotFoundError(f"{KBO_PARQUET} 없음")
    games = pd.read_parquet(KBO_PARQUET).dropna(subset=["attendance"])
    games = games[games["stadium"] == JAMSIL_STADIUM_NAME]
    return set(pd.to_datetime(games["date"]).dt.normalize())


def jamsil_nearby_stations(station_coords: pd.DataFrame) -> set:
    """`station_coords`(od_station_id, lat_stock, lon_stock 컬럼)에서 잠실 반경 1.5km 역 집합."""
    conf = yaml.safe_load(VENUE_CONF.read_text(encoding="utf-8"))
    lat, lon = conf["kbo"][JAMSIL_STADIUM_NAME]["lat"], conf["kbo"][JAMSIL_STADIUM_NAME]["lon"]
    radius_km = float(conf["radius_km"])
    df = station_coords.drop_duplicates("od_station_id").dropna(subset=["lat_stock", "lon_stock"])
    d = haversine_km(df["lat_stock"].to_numpy(), df["lon_stock"].to_numpy(), lat, lon)
    return set(df.loc[d <= radius_km, "od_station_id"])


def attach_external(
    df: pd.DataFrame,
    weather: pd.DataFrame,
    holidays: pd.DataFrame,
    jamsil_dates: set,
    jamsil_stations: set,
    date_col: str = "date",
    hour_col: str = "hour",
) -> pd.DataFrame:
    """`is_holiday`/`is_rain`/`temp`/`is_kbo_game_jamsil`을 한 번에 부착한다.

    `date_col`/`hour_col`은 anchor 기준이든 target 기준이든 호출부가 고른 컬럼명을 그대로
    쓴다 — 30분 이내는 거의 안 바뀌는 근사라 anchor 기준으로 붙여도 된다(계획서에 명시된
    단순화, `RESULTS.md` 참고).
    """
    df = df.merge(weather, left_on=[date_col, hour_col], right_on=["date", "hour"], how="left")
    df = df.merge(holidays, left_on=date_col, right_on="date", how="left", suffixes=("", "_hol"))
    df["is_holiday"] = df["is_holiday"].fillna(False)
    # 날씨 실측 범위 밖 날짜(서빙 시점이 ASOS 이력보다 미래인 경우, Phase D 갭)는 매칭이
    # 안 돼서 NaN이 섞이는데, bool 컬럼에 NaN이 들어가면 dtype이 object로 깨져서
    # LightGBM이 거부한다(`ValueError: pandas dtypes must be int, float or bool`) —
    # 반드시 fillna 뒤 bool로 명시 캐스팅한다.
    df["is_rain"] = df["is_rain"].fillna(False).astype(bool)
    df["is_kbo_game_jamsil"] = df["od_station_id"].isin(jamsil_stations) & df[date_col].isin(
        jamsil_dates
    )
    return df
