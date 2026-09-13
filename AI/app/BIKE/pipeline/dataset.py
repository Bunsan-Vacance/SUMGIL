"""전체 대여소 매핑 데이터셋 로딩 — `validation/BYC/full-coverage-check`의 산출물을 읽는다.

원본 매핑(좌표 6자리 매칭, 5분 OD 집계, 1시간 재고 anchor 조인)은 여전히
`validation/BYC/full-coverage-check/src/build_full_station_netflow.py`가 담당한다(월별로
새 프로세스를 띄워야 메모리가 안전하다는 게 실측으로 확인됐다 — 그 스크립트의 docstring과
`RESULTS.md` 참고). 여기서는 그 산출물(월별 parquet)을 읽는 것만 다룬다.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

AI_ROOT = Path(__file__).resolve().parents[3]
BIKE_FULL_RUN_DIR = AI_ROOT / "validation" / "BYC" / "full-coverage-check" / "outputs" / "full-run"

READ_COLS_BASE = ["od_station_id", "date", "target_rent_count", "target_return_count"]


def monthly_paths(
    prefix: str, months: list[str] | None = None, data_dir: Path = BIKE_FULL_RUN_DIR
) -> list[Path]:
    """prefix는 train/valid/test. months는 YYYYMM 리스트(생략 시 전체)."""
    paths = sorted(Path(data_dir).glob(f"{prefix}_netflow_q3_mapped_full_*.parquet"))
    if not paths:
        raise FileNotFoundError(f"{data_dir}에 {prefix}_netflow_q3_mapped_full_*.parquet 없음")
    if months:
        paths = [p for p in paths if any(m in p.stem for m in months)]
    return paths


def load_paths(
    paths: list[Path],
    columns: list[str],
    target_col: str,
    sample_frac: float | None = None,
    random_state: int = 42,
) -> pd.DataFrame:
    """여러 parquet을 필요한 컬럼만 읽어 합치고, target이 NaN인 행을 제외한다.

    target_net_flow가 NaN인 행이 소수 섞여 있다 — 월 단위로 끊어 만든 데이터셋이라
    각 달 마지막 몇 슬롯은 forward rolling window가 그 달 파일 안에서 미래 데이터를
    못 찾는다(전체의 0.02% 미만, `build_full_station_netflow.py` 참고). 값을 채우지
    않고 그 행만 제외한다(원칙 8: 표본 부족 구간에 값을 채우지 않는다).

    sample_frac은 파일별로 적용한다 — 로딩 도중 피크 메모리도 같이 줄어야
    의미가 있다(다 합친 뒤 샘플링하면 합치는 순간엔 전체가 메모리에 있어야 함).
    """
    frames = []
    for p in paths:
        df = pd.read_parquet(p, columns=columns)
        if sample_frac is not None:
            df = df.sample(frac=sample_frac, random_state=random_state)
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["od_station_id"] = df["od_station_id"].astype(str)
    before = len(df)
    df = df.dropna(subset=[target_col]).reset_index(drop=True)
    dropped = before - len(df)
    if dropped:
        print(f"  {target_col} NaN {dropped:,}행 제외 (월 경계 rolling window 부작용)")
    return df


def scan_station_ids(paths: list[Path]) -> set[str]:
    """od_station_id 컬럼만 훑어서 station id 집합을 얻는다(전체 로드 없이)."""
    ids: set[str] = set()
    for p in paths:
        col = pq.ParquetFile(p).read(columns=["od_station_id"])["od_station_id"]
        ids |= set(col.to_pylist())
    return ids
