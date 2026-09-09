"""서울시 지하철 호선별 역별 시간대별 승하차 인원 정보(수동 다운로드 CSV)
→ data/CROWD/interim/*.parquet.

`parsers_crowd.py`가 다루는 혼잡도(%) "대표 1주" 스냅샷과는 별개 원천이다 — 이쪽은
**월(`사용월`) 단위 실측 집계**라 날짜가 아니라 "그 달 한 달 치 시간대별 총 승하차"다.
일 단위 시계열도 아니라서(혼잡도 스냅샷과 같은 한계) 날씨·공휴일과 일 단위 상관분석에는
못 쓰지만, 월 단위 추세·계절성 분석에는 쓸 수 있다 — 2015년 1월부터 매달 실측이 쌓여 있어
혼잡도의 "대표 1주" 한 번보다 표본이 훨씬 많다.

원본은 (사용월, 호선명, 지하철역) 단위 wide-format이고, 시간대별 승차/하차 컬럼이
"04시-05시 승차인원"처럼 붙어 있다 — 이걸 long-format으로 melt한다. `작업일자`(데이터
처리일, 실측 시점이 아님)는 버린다.

실행:
    cd AI
    python -m DATA_ENGINE.eda.parsers_crowd_ridership
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = AI_ROOT / "data" / "CROWD" / "raw"
INTERIM_DIR = AI_ROOT / "data" / "CROWD" / "interim"

_ID_VARS = ["usage_month", "line", "station_name"]
_RENAME = {"사용월": "usage_month", "호선명": "line", "지하철역": "station_name"}
_TIME_COL_PATTERN = re.compile(r"^(\d{2}시-\d{2}시) (승차|하차)인원$")
_DIRECTION_KO_TO_EN = {"승차": "boarding", "하차": "alighting"}


def load_monthly_ridership_csv(path: str | Path) -> pd.DataFrame:
    """원본 wide-format CSV 한 개를 (usage_month, line, station_name, time_slot, direction,
    passengers) tidy long-format으로 변환한다."""
    df = pd.read_csv(path, encoding="cp949")
    df = df.rename(columns=_RENAME)

    time_cols = [c for c in df.columns if _TIME_COL_PATTERN.match(c)]
    long_df = df.melt(
        id_vars=_ID_VARS, value_vars=time_cols, var_name="raw_col", value_name="passengers"
    )
    extracted = long_df["raw_col"].str.extract(_TIME_COL_PATTERN)
    long_df["time_slot"] = extracted[0]
    long_df["direction"] = extracted[1].map(_DIRECTION_KO_TO_EN)
    return long_df.drop(columns="raw_col")


def duplicate_cell_inventory(df: pd.DataFrame) -> pd.DataFrame:
    """(usage_month, line, station_name, time_slot, direction) 조합이 중복된 행을 그대로
    나열한다 — 평균으로 조용히 뭉개지 않는다."""
    key = ["usage_month", "line", "station_name", "time_slot", "direction"]
    dup_mask = df.duplicated(subset=key, keep=False)
    return df[dup_mask].sort_values(key)


def save_interim(df: pd.DataFrame) -> Path:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    out_path = INTERIM_DIR / "crowd_ridership_long.parquet"
    df.to_parquet(out_path, index=False)
    return out_path


def main() -> None:
    csv_paths = sorted(RAW_DIR.glob("서울시 지하철 호선별 역별 시간대별 승하차 인원 정보*.csv"))
    if not csv_paths:
        raise FileNotFoundError(f"{RAW_DIR} 에서 승하차 인원 csv 원본을 찾지 못했습니다.")

    df = load_monthly_ridership_csv(csv_paths[0])
    dups = duplicate_cell_inventory(df)
    out_path = save_interim(df)
    print(
        f"저장 완료: {out_path} ({len(df):,}행, "
        f"{df['usage_month'].min()} ~ {df['usage_month'].max()}, 중복 셀 {len(dups)}건)"
    )


if __name__ == "__main__":
    main()
