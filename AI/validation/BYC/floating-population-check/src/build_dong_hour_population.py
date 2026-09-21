"""서울 생활인구(250m 격자) raw(27GB, 일별 CSV 458개) -> 행정동x일x시간대 집계.

원본은 (일자, 시간, 행정동코드, 250M격자, 생활인구합계 + 연령성별 19열)로 격자 단위다.
`생활인구합계`만 행정동코드로 합산하면(같은 행정동 안의 격자를 더함) 대여소-행정동 매핑과
바로 조인할 수 있는 크기(행정동 426개 x 시간 24 x 일수)로 줄어든다. 연령·성별 세부 컬럼은
"*"로 마스킹된 값이 섞여 있어(개인정보 보호, 소규모 셀) 1차 피처에서는 쓰지 않는다 —
`생활인구합계`는 마스킹 없이 항상 숫자다.

파일 458개 x 하루 25만행(총 27GB)을 한 번에 메모리에 올리지 않는다 — 파일 하나씩 읽어서
그 자리에서 groupby-sum으로 축소한 뒤 원본은 버린다(`AI/CLAUDE.md` 대용량 처리 원칙).

출력:
    AI/data/EXTERNAL/population/processed/dong_hour_population.parquet
    컬럼: date(YYYY-MM-DD), hour(0~23), dong_code(int64), population_total(float)

실행:
    cd AI
    python validation/BYC/floating-population-check/src/build_dong_hour_population.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(AI_ROOT))

RAW_DIR = AI_ROOT / "data" / "EXTERNAL" / "population" / "raw"
OUTPUT_PATH = (
    AI_ROOT / "data" / "EXTERNAL" / "population" / "processed" / "dong_hour_population.parquet"
)

READ_COLS = ["일자", "시간", "행정동코드", "생활인구합계"]
RENAME = {
    "일자": "date_raw",
    "시간": "hour",
    "행정동코드": "dong_code",
    "생활인구합계": "population_total",
}


def aggregate_one_file(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=READ_COLS, encoding="cp949")
    df = df.rename(columns=RENAME)
    # 소규모 셀은 "*"로 마스킹돼 있다(개인정보 보호) — 숫자로 강제 변환하면서 NaN 처리.
    # sum()은 기본으로 NaN을 건너뛰므로 마스킹된 셀은 합계에서 빠진다(원칙 8: 채워 넣지 않는다).
    df["population_total"] = pd.to_numeric(df["population_total"], errors="coerce")
    grouped = df.groupby(["date_raw", "hour", "dong_code"], as_index=False)[
        "population_total"
    ].sum()
    grouped["date"] = pd.to_datetime(grouped["date_raw"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
    grouped["hour"] = grouped["hour"].astype("int8")
    grouped["dong_code"] = grouped["dong_code"].astype("int64")
    grouped["population_total"] = grouped["population_total"].astype("float32")
    return grouped[["date", "hour", "dong_code", "population_total"]]


def build_dong_hour_population() -> pd.DataFrame:
    csv_paths = sorted(RAW_DIR.glob("250_LOCAL_RESD_*/250_LOCAL_RESD_*.csv"))
    if not csv_paths:
        raise FileNotFoundError(f"{RAW_DIR}에 원본 CSV 없음")
    print(f"대상 파일 {len(csv_paths):,}개")

    frames = []
    t0 = time.time()
    for i, path in enumerate(csv_paths, start=1):
        frames.append(aggregate_one_file(path))
        if i % 30 == 0 or i == len(csv_paths):
            elapsed = time.time() - t0
            print(f"  {i:,}/{len(csv_paths):,} 처리, 경과 {elapsed:.0f}초")

    combined = pd.concat(frames, ignore_index=True)
    return combined


def main() -> None:
    out = build_dong_hour_population()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUTPUT_PATH, index=False)
    print(f"저장: {OUTPUT_PATH} ({len(out):,}행)")
    print(f"기간: {out['date'].min()} ~ {out['date'].max()}, 행정동 {out['dong_code'].nunique()}개")


if __name__ == "__main__":
    main()
