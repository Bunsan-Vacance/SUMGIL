"""전체 역(train/valid/test 전체 커버리지, ~2,583개) 지하철·버스 도보거리 — 하버사인 버전.

`validation/BYC/phase3-station-static/src/build_station_distance_features.py`(OSRM 기반,
510개 역만 커버)와 같은 목적이지만, 로컬에 OSRM 서버가 없어서 하버사인(직선거리)으로
대체한다. Phase 3 검증(`data/EXTERNAL/station/processed/station_distance_report.md`)에서
K값 민감도가 0%였고 하버사인과 OSRM 거리가 대부분 근접했던 걸 근거로, 이 피처가 애초에
효과가 있는지부터 빠르게 확인하는 용도다 — 효과가 확인되면 그때 OSRM으로 정교화한다.

`external_features.haversine_km()`을 그대로 재사용한다(KBO 인근역 판정에 쓰는 것과 동일).

출력:
    AI/data/EXTERNAL/station/processed/station_distance_features_full_haversine.csv
    컬럼: od_station_id, dist_subway_m, nearest_subway_name, dist_bus_m, nearest_bus_name

실행:
    cd AI
    python validation/BYC/anchor-horizon-feature-check/src/build_full_station_distance.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(AI_ROOT))

from app.BIKE.pipeline.dataset import BIKE_FULL_RUN_DIR
from app.BIKE.pipeline.external_features import haversine_km

STATION_DIR = AI_ROOT / "data" / "EXTERNAL" / "station"
SUBWAY_PATH = STATION_DIR / "raw" / "서울시 역사마스터 정보.csv"
BUS_PATH = STATION_DIR / "raw" / "서울시버스정류소위치정보(20260902).xlsx"
OUTPUT_PATH = STATION_DIR / "processed" / "station_distance_features_full_haversine.csv"


def load_all_station_coords() -> pd.DataFrame:
    """train/valid/test 전체 monthly parquet에서 station 좌표를 모아 중복 제거한다.

    `dataset.load_station_static()`은 파일 하나만 읽어서 그 달에 없는 역을 놓친다 —
    여기서는 전체 파일을 훑어 합집합을 만든다(`train.py`의 station_ids 수집과 동일 원칙).
    """
    frames = []
    for path in sorted(BIKE_FULL_RUN_DIR.glob("*_netflow_q3_mapped_full_*.parquet")):
        frames.append(pd.read_parquet(path, columns=["od_station_id", "lat_stock", "lon_stock"]))
    combined = pd.concat(frames, ignore_index=True)
    return combined.drop_duplicates("od_station_id").dropna(subset=["lat_stock", "lon_stock"])


def load_subway() -> pd.DataFrame:
    df = pd.read_csv(SUBWAY_PATH, encoding="cp949")
    return df.rename(columns={"역사_ID": "id", "역사명": "name", "위도": "lat", "경도": "lon"})[
        ["id", "name", "lat", "lon"]
    ]


def load_bus() -> pd.DataFrame:
    df = pd.read_excel(BUS_PATH)
    df = df.rename(
        columns={
            "NODE_ID": "node_id",
            "정류소명": "name",
            "X좌표": "lon",
            "Y좌표": "lat",
        }
    )
    return df[["node_id", "name", "lat", "lon"]]


def nearest_haversine(
    stations: pd.DataFrame, facilities: pd.DataFrame
) -> tuple[np.ndarray, np.ndarray]:
    """station마다 시설까지 하버사인 최단거리(m)와 그 시설 이름을 벡터 연산으로 구한다."""
    dist_km = haversine_km(
        stations["lat_stock"].to_numpy()[:, None],
        stations["lon_stock"].to_numpy()[:, None],
        facilities["lat"].to_numpy()[None, :],
        facilities["lon"].to_numpy()[None, :],
    )
    nearest_idx = np.argmin(dist_km, axis=1)
    nearest_m = dist_km[np.arange(len(stations)), nearest_idx] * 1000.0
    nearest_name = facilities["name"].to_numpy()[nearest_idx]
    return nearest_m, nearest_name


def main() -> None:
    stations = load_all_station_coords()
    subway = load_subway()
    bus = load_bus()
    print(f"station: {len(stations):,}, subway: {len(subway):,}, bus: {len(bus):,}")

    dist_subway_m, nearest_subway_name = nearest_haversine(stations, subway)
    dist_bus_m, nearest_bus_name = nearest_haversine(stations, bus)

    out = pd.DataFrame(
        {
            "od_station_id": stations["od_station_id"].to_numpy(),
            "dist_subway_m": dist_subway_m,
            "nearest_subway_name": nearest_subway_name,
            "dist_bus_m": dist_bus_m,
            "nearest_bus_name": nearest_bus_name,
        }
    )
    out.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {OUTPUT_PATH} ({len(out):,}행)")
    print(out[["dist_subway_m", "dist_bus_m"]].describe())


if __name__ == "__main__":
    main()
