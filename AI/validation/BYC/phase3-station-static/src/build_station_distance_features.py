"""Phase 3 — station 정적 feature 중 지하철/버스 도보거리를 계산한다.

입력:
  AI/data/EXTERNAL/station/processed/station_union_510.csv       (따릉이 station 510개)
  AI/data/EXTERNAL/station/raw/서울시 역사마스터 정보.csv           (지하철역 784개)
  AI/data/EXTERNAL/station/raw/서울시버스정류소위치정보(20260902).xlsx (버스정류장 11,236개)

처리:
  1. haversine으로 station마다 최근접 후보 K개 추림 (지하철 K=25, 버스 K=20)
  2. 후보들을 OSRM /table 서비스(foot profile, localhost:5000)로 한 번에 쿼리해서
     실제 도보거리 계산, station당 최솟값 채택
  3. OSRM 실패(좌표 스냅 실패/경로 없음) 시 haversine 값으로 fallback, status로 구분

⚠️ 좌표 순서 주의 — OSRM은 lon,lat 순서. 원본 컬럼명은 lat/lon이라 헷갈리기 쉬워서
   요청 직전에 한국 좌표 범위(lat 33~43, lon 124~132)로 assert한다.

출력:
  AI/data/EXTERNAL/station/processed/station_distance_features.csv

실행 예:
    python build_station_distance_features.py
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

AI_DIR = Path(__file__).resolve().parents[4]
STATION_DIR = AI_DIR / "data" / "EXTERNAL" / "station"
UNION_PATH = STATION_DIR / "processed" / "station_union_510.csv"
SUBWAY_PATH = STATION_DIR / "raw" / "서울시 역사마스터 정보.csv"
BUS_PATH = STATION_DIR / "raw" / "서울시버스정류소위치정보(20260902).xlsx"
OUTPUT_PATH = STATION_DIR / "processed" / "station_distance_features.csv"

OSRM_URL = "http://localhost:5000"
K_SUBWAY = 25
K_BUS = 20
EARTH_RADIUS_M = 6371000

KOREA_LAT_RANGE = (33.0, 43.5)
KOREA_LON_RANGE = (124.0, 132.0)


def haversine_matrix(lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    """station(lat1,lon1) x 후보(lat2,lon2) 전체 쌍의 직선거리(m) 행렬을 벡터 연산으로 계산."""
    lat1r, lon1r, lat2r, lon2r = (np.radians(a) for a in (lat1, lon1, lat2, lon2))
    dlat = lat2r[None, :] - lat1r[:, None]
    dlon = lon2r[None, :] - lon1r[:, None]
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1r[:, None]) * np.cos(lat2r[None, :]) * np.sin(dlon / 2) ** 2
    c = 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    return EARTH_RADIUS_M * c


def assert_korea_coord(lat: float, lon: float, label: str) -> None:
    lo, hi = KOREA_LAT_RANGE
    assert lo <= lat <= hi, f"{label}: 위도 범위 이탈({lat}) — lat/lon 순서 확인"
    lo, hi = KOREA_LON_RANGE
    assert lo <= lon <= hi, f"{label}: 경도 범위 이탈({lon}) — lat/lon 순서 확인"


def query_osrm_table(src_lat: float, src_lon: float, cand_lat: np.ndarray, cand_lon: np.ndarray):
    """station 1개 -> 후보 K개 도보거리를 OSRM /table 한 번으로 조회."""
    assert_korea_coord(src_lat, src_lon, "source")
    for la, lo in zip(cand_lat, cand_lon):
        assert_korea_coord(la, lo, "candidate")

    coords = [f"{src_lon},{src_lat}"] + [f"{lo},{la}" for la, lo in zip(cand_lat, cand_lon)]
    url = f"{OSRM_URL}/table/v1/foot/{';'.join(coords)}?sources=0&annotations=distance"
    try:
        resp = requests.get(url, timeout=15)
        data = resp.json()
    except Exception:
        return None, "REQUEST_FAILED"

    if data.get("code") != "Ok":
        return None, data.get("code", "UNKNOWN_ERROR")

    dists = data["distances"][0][1:]
    return dists, "OK"


def load_subway() -> pd.DataFrame:
    df = pd.read_csv(SUBWAY_PATH, encoding="cp949")
    return df.rename(columns={"역사_ID": "id", "역사명": "name", "위도": "lat", "경도": "lon"})[
        ["id", "name", "lat", "lon"]
    ]


def load_bus() -> pd.DataFrame:
    df = pd.read_excel(BUS_PATH)
    df = df.rename(columns={"NODE_ID": "node_id", "ARS_ID": "ars_id", "정류소명": "name", "X좌표": "lon", "Y좌표": "lat"})
    return df[["node_id", "ars_id", "name", "lat", "lon"]]


def nearest_walk_distance(stations: pd.DataFrame, facilities: pd.DataFrame, k: int, id_cols: list[str]):
    """station마다 haversine top-k 후보를 뽑고 OSRM /table로 실제 도보거리를 구한다."""
    dist_mat = haversine_matrix(
        stations["lat"].to_numpy(), stations["lon"].to_numpy(),
        facilities["lat"].to_numpy(), facilities["lon"].to_numpy(),
    )
    topk_idx = np.argsort(dist_mat, axis=1)[:, :k]

    rows = []
    for i, station_id in enumerate(stations["od_station_id"]):
        cand_idx = topk_idx[i]
        cand = facilities.iloc[cand_idx]
        haversine_cands = dist_mat[i, cand_idx]

        osrm_dists, status = query_osrm_table(
            stations["lat"].iloc[i], stations["lon"].iloc[i],
            cand["lat"].to_numpy(), cand["lon"].to_numpy(),
        )

        if osrm_dists is not None:
            osrm_arr = np.array([d if d is not None else np.inf for d in osrm_dists])
            if np.all(np.isinf(osrm_arr)):
                osrm_dists = None

        if osrm_dists is not None:
            best_i = int(np.argmin(osrm_arr))
            dist_final = float(osrm_arr[best_i])
            dist_source = "OSRM"
            osrm_distance_m = dist_final
        else:
            best_i = int(np.argmin(haversine_cands))
            dist_final = float(haversine_cands[best_i])
            dist_source = "HAVERSINE_FALLBACK"
            osrm_distance_m = np.nan
            if status == "OK":
                status = "NO_ROUTE"

        row = {
            "od_station_id": station_id,
            "dist_m": dist_final,
            "dist_source": dist_source,
            "osrm_distance_m": osrm_distance_m,
            "osrm_status": status,
            "haversine_m": float(haversine_cands[best_i]),
            "nearest_name": cand["name"].iloc[best_i],
        }
        for col in id_cols:
            row[f"nearest_{col}"] = cand[col].iloc[best_i]
        rows.append(row)

    return pd.DataFrame(rows)


def main() -> None:
    stations = pd.read_csv(UNION_PATH)
    subway = load_subway()
    bus = load_bus()

    print(f"station: {len(stations)}, subway: {len(subway)}, bus: {len(bus)}")

    t0 = time.time()
    print("지하철 거리 계산 중...")
    subway_result = nearest_walk_distance(stations, subway, K_SUBWAY, id_cols=["id"])
    print(f"  완료 ({time.time() - t0:.1f}s)")

    t0 = time.time()
    print("버스 거리 계산 중...")
    bus_result = nearest_walk_distance(stations, bus, K_BUS, id_cols=["ars_id", "node_id"])
    print(f"  완료 ({time.time() - t0:.1f}s)")

    subway_result = subway_result.rename(columns={
        "dist_m": "dist_subway_m", "dist_source": "dist_subway_source",
        "osrm_distance_m": "subway_osrm_distance_m", "osrm_status": "subway_osrm_status",
        "haversine_m": "subway_haversine_m", "nearest_name": "nearest_subway_name",
        "nearest_id": "nearest_subway_id",
    })
    bus_result = bus_result.rename(columns={
        "dist_m": "dist_bus_m", "dist_source": "dist_bus_source",
        "osrm_distance_m": "bus_osrm_distance_m", "osrm_status": "bus_osrm_status",
        "haversine_m": "bus_haversine_m", "nearest_name": "nearest_bus_name",
        "nearest_ars_id": "nearest_bus_ars_id", "nearest_node_id": "nearest_bus_node_id",
    })

    merged = stations.merge(subway_result, on="od_station_id").merge(bus_result, on="od_station_id")
    merged.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {OUTPUT_PATH} ({len(merged)} rows)")

    print("\n=== subway_osrm_status ===")
    print(merged["subway_osrm_status"].value_counts())
    print("\n=== bus_osrm_status ===")
    print(merged["bus_osrm_status"].value_counts())
    print("\n=== dist_subway_m 분포 ===")
    print(merged["dist_subway_m"].describe())
    print("\n=== dist_bus_m 분포 ===")
    print(merged["dist_bus_m"].describe())


if __name__ == "__main__":
    main()
