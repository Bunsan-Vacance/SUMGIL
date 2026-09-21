"""대여소 위경도 -> 행정동코드 매핑 (point-in-polygon).

서울 생활인구(250m 격자) 데이터는 행정동코드 단위로도 집계돼 있어서(`행정동코드` 컬럼),
대여소를 행정동에 매핑하면 격자 좌표 변환 없이 바로 조인할 수 있다. 경계 폴리곤은
서울시 상권분석서비스(영역-행정동) shapefile(EPSG:5181, 한국 중부원점 TM)을 쓴다 —
`ADSTRD_CD` 속성이 생활인구 데이터의 `행정동코드`와 동일한 8자리 코드 체계임을 확인했다
(예: 11110515 = 청운효자동).

대여소 좌표는 `build_station_master.py`/`build_full_station_distance.py`와 같은 패턴으로
전체 train/valid/test 파일을 스캔해 합친다(한 달 파일만 보면 그 이후 신설 역이 빠진다).

출력:
    AI/data/EXTERNAL/population/processed/station_dong_mapping.parquet
    컬럼: od_station_id, dong_code, dong_name, match_method(within|nearest)

실행:
    cd AI
    python validation/BYC/floating-population-check/src/build_station_dong_mapping.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(AI_ROOT))

from app.BIKE.pipeline.dataset import BIKE_FULL_RUN_DIR

BOUNDARY_SHP = (
    AI_ROOT
    / "data"
    / "EXTERNAL"
    / "population"
    / "raw"
    / "서울시 상권분석서비스(영역-행정동)"
    / "서울시 상권분석서비스(영역-행정동).shp"
)
OUTPUT_PATH = (
    AI_ROOT / "data" / "EXTERNAL" / "population" / "processed" / "station_dong_mapping.parquet"
)


def load_all_station_coords() -> pd.DataFrame:
    frames = []
    for path in sorted(BIKE_FULL_RUN_DIR.glob("*_netflow_q3_mapped_full_*.parquet")):
        frames.append(pd.read_parquet(path, columns=["od_station_id", "lat_stock", "lon_stock"]))
    combined = pd.concat(frames, ignore_index=True)
    return combined.drop_duplicates("od_station_id").dropna(subset=["lat_stock", "lon_stock"])


def build_mapping() -> pd.DataFrame:
    coords = load_all_station_coords()
    points = gpd.GeoDataFrame(
        coords,
        geometry=gpd.points_from_xy(coords["lon_stock"], coords["lat_stock"]),
        crs="EPSG:4326",
    ).to_crs("EPSG:5181")

    boundary = gpd.read_file(BOUNDARY_SHP)[["ADSTRD_CD", "ADSTRD_NM", "geometry"]]
    boundary["ADSTRD_CD"] = boundary["ADSTRD_CD"].astype("int64")

    joined = gpd.sjoin(points, boundary, how="left", predicate="within")
    joined = joined.drop(columns="index_right")
    joined["match_method"] = "within"

    missing_mask = joined["ADSTRD_CD"].isna()
    n_missing = int(missing_mask.sum())
    if n_missing:
        print(f"  within 매칭 실패 {n_missing}개 역 -- 최근접 폴리곤으로 재시도")
        missing_points = points.loc[missing_mask.to_numpy(), ["od_station_id", "geometry"]]
        nearest = gpd.sjoin_nearest(missing_points, boundary, how="left")
        nearest = nearest.drop(columns="index_right")
        nearest["match_method"] = "nearest"
        joined = joined.loc[~missing_mask.to_numpy()]
        joined = pd.concat([joined, nearest], ignore_index=True)

    still_missing = int(joined["ADSTRD_CD"].isna().sum())
    if still_missing:
        print(f"  최근접 재시도 후에도 매칭 실패 {still_missing}개 역 -- 결측으로 남김(원칙 8)")

    out = joined[["od_station_id", "ADSTRD_CD", "ADSTRD_NM", "match_method"]].rename(
        columns={"ADSTRD_CD": "dong_code", "ADSTRD_NM": "dong_name"}
    )
    out.loc[out["dong_code"].isna(), "match_method"] = None
    return out.reset_index(drop=True)


def main() -> None:
    out = build_mapping()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUTPUT_PATH, index=False)
    matched = out["dong_code"].notna().sum()
    nearest_used = (out["match_method"] == "nearest").sum()
    print(f"저장: {OUTPUT_PATH}")
    print(
        f"  전체 {len(out):,}개 역, 매칭 {matched:,}개(within 그대로 {matched - nearest_used:,} / nearest 보정 {nearest_used:,})"
    )


if __name__ == "__main__":
    main()
