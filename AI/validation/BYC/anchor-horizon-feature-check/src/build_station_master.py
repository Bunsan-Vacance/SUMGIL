"""역별 rack_count 룩업 — 실시간 서빙(predictor_eta.py)이 stock_ratio_hour/is_empty_anchor/
is_full_anchor를 계산할 때 쓴다.

학습 원본(train/valid/test 전체 monthly parquet, 수백MB~수GB)에서만 rack_count를
구할 수 있는데, 서버 기동 때마다 그 큰 파일을 스캔하면 안 되니 작은 룩업 파일 하나로
미리 뽑아둔다. `build_full_station_distance.py`의 `load_all_station_coords()`와 같은
패턴(전체 파일 스캔 + station_id 기준 중복 제거).

출력:
    AI/data/EXTERNAL/station/processed/station_master.parquet
    컬럼: od_station_id, rack_count

실행:
    cd AI
    python validation/BYC/anchor-horizon-feature-check/src/build_station_master.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(AI_ROOT))

from app.BIKE.pipeline.dataset import BIKE_FULL_RUN_DIR

OUTPUT_PATH = AI_ROOT / "data" / "EXTERNAL" / "station" / "processed" / "station_master.parquet"


def build_station_master() -> pd.DataFrame:
    frames = []
    for path in sorted(BIKE_FULL_RUN_DIR.glob("*_netflow_q3_mapped_full_*.parquet")):
        frames.append(pd.read_parquet(path, columns=["od_station_id", "rack_count"]))
    combined = pd.concat(frames, ignore_index=True)
    # 같은 역이 파일마다 rack_count가 미세하게 다르게 찍힌 경우(증설 등) 대비 최빈값 채택.
    return (
        combined.groupby("od_station_id")["rack_count"]
        .agg(lambda s: s.mode().iloc[0])
        .reset_index()
    )


def main() -> None:
    out = build_station_master()
    out.to_parquet(OUTPUT_PATH, index=False)
    print(f"저장 완료: {OUTPUT_PATH} ({len(out):,}행)")
    print(out["rack_count"].describe())


if __name__ == "__main__":
    main()
