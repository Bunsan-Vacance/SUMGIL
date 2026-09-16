"""pandas vs PySpark 벤치마크 공통 유틸.

- 데이터 경로 해석
- 스케일 증폭(날짜 오프셋 방식 — 조인 키 중복을 피하기 위해 원본을 그대로 N번 쌓지 않는다)
- 프로세스 트리 피크 메모리 샘플링(psutil, Spark JVM 자식 프로세스 포함)

주의: 이 모듈은 PoC 전용(`validation/`)이며 `app/`에서 import하지 않는다.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pandas as pd
import psutil

# spark-compare-check/ -> INFRA/ -> validation/ -> AI/
AI_ROOT = Path(__file__).resolve().parents[3]

DATA_PATHS = {
    "A": AI_ROOT / "data/CROWD/processed/crowd_panel_2024_2025.parquet",
    "B": AI_ROOT / "data/CROWD/processed/crowd_congestion_label_calibrated_2024_2026.parquet",
    "C": AI_ROOT / "data/CROWD/interim/crowd_daily_ridership_long.parquet",
}

# 각 OP이 실제로 쓰는 컬럼만 골라 읽는다(저장소 관례: 필요한 컬럼만 select).
NEEDED_COLS = {
    "A": ["station_no", "date", "time_slot", "day_type", "boarding", "alighting"],
    "B": ["station_no", "date", "time_slot", "direction", "congestion_raw_pct"],
    "C": ["date", "line", "station_no", "time_slot", "direction", "passengers"],
}

RESULTS_PATH = Path(__file__).resolve().parent / "results.jsonl"

YEAR_STEP = 3  # 배수 증폭 시 복제본마다 이만큼씩 연도를 밀어 조인 키 중복을 피한다.


def amplify_pandas(
    df: pd.DataFrame, multiplier: int, date_col: str = "date", year_step: int = YEAR_STEP
) -> pd.DataFrame:
    """원본을 그대로 N번 복제하지 않고, 복제본마다 날짜를 year_step*i 년씩 밀어서 이어붙인다.

    같은 행을 그대로 쌓으면 groupby/조인 키가 중복돼 집계·조인 의미가 원본과 달라지므로
    (예: lookup 평균이 그대로 유지되고 lag 조인도 자기 자신과만 매칭됨), 스케일 스윕이
    "더 많은 서로 다른 관측치를 처리하는" 실제 상황을 흉내 내지 못한다. 연도를 밀면
    각 복제본이 독립된 기간처럼 동작해 조인/집계 부하가 실제로 배수만큼 늘어난다.
    """
    if multiplier <= 1:
        return df
    parts = [df]
    for i in range(1, multiplier):
        offset_years = i * year_step
        copy = df.copy()
        copy[date_col] = copy[date_col] + pd.DateOffset(years=offset_years)
        parts.append(copy)
    return pd.concat(parts, ignore_index=True)


def amplify_spark(sdf, multiplier: int, date_col: str = "date", year_step: int = YEAR_STEP):
    from pyspark.sql import functions as F

    # date_add/add_months는 DateType을 반환한다. 증폭하지 않는 1x 포함, 항상 date 컬럼을
    # DateType으로 통일해 이후 union/조인에서 타입이 섞이지 않게 한다.
    sdf = sdf.withColumn(date_col, F.to_date(F.col(date_col)))
    if multiplier <= 1:
        return sdf
    parts = [sdf]
    for i in range(1, multiplier):
        offset_months = i * year_step * 12
        parts.append(sdf.withColumn(date_col, F.add_months(F.col(date_col), offset_months)))
    out = parts[0]
    for p in parts[1:]:
        out = out.unionByName(p)
    return out


class MemSampler:
    """현재 프로세스 + 모든 자식 프로세스(Spark JVM 포함) RSS 합의 피크값을 별도
    스레드에서 0.2초 간격으로 샘플링한다."""

    def __init__(self, pid: int | None = None, interval: float = 0.2):
        self.pid = pid or os.getpid()
        self.interval = interval
        self.peak_mb = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _sample_once(self) -> None:
        try:
            proc = psutil.Process(self.pid)
            total = proc.memory_info().rss
            for child in proc.children(recursive=True):
                try:
                    total += child.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return
        mb = total / (1024 * 1024)
        self.peak_mb = max(self.peak_mb, mb)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._sample_once()
            time.sleep(self.interval)

    def start(self) -> MemSampler:
        self._sample_once()
        self._thread.start()
        return self

    def stop(self) -> float:
        self._stop.set()
        self._thread.join(timeout=2)
        self._sample_once()
        return self.peak_mb
