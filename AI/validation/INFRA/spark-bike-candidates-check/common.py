"""pandas vs PySpark 실측 공통 유틸 — 실제 BIKE 도메인 데이터 기준.

`validation/INFRA/spark-compare-check`(165)는 CROWD 패널을 증폭한 프록시 데이터로 교차점을
쟀다. 이 모듈은 그 교차점이 **실제로 Spark 도입 후보인 두 지점**(대여이력 집계, 재고 raw
누적 재집계)에서도 성립하는지 실측 데이터로 확인한다.

주의: PoC 전용(`validation/`)이며 `app/`에서 import하지 않는다.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import psutil

AI_ROOT = Path(__file__).resolve().parents[3]
RENTAL_HISTORY_DIR = AI_ROOT / "data" / "BIKE" / "raw" / "rental_history"
BIKE_REALTIME_SAMPLE_DIR = Path(__file__).resolve().parent / "data_sample" / "bike_realtime"
RESULTS_PATH = Path(__file__).resolve().parent / "results.jsonl"

# 원본 CSV는 cp949, 컬럼명이 한글이라 위치 기반으로 고정한다(build_full_station_netflow.py와 동일 전제).
RENTAL_RAW_COLS = [
    "date",
    "basis",  # 집계_기준: 출발시간 | 도착시간
    "hhmm",  # 기준_시간대 HHMM
    "start_station_id",
    "start_station_name",
    "end_station_id",
    "end_station_name",
    "count",
    "duration_min",
    "distance_m",
]


def rental_history_months() -> list[str]:
    return sorted(p.name.split("_")[-1] for p in RENTAL_HISTORY_DIR.glob("tpss_bcycl_od_statnhm_*"))


def rental_history_files(months: list[str]) -> list[Path]:
    files: list[Path] = []
    for month in months:
        month_dir = RENTAL_HISTORY_DIR / f"tpss_bcycl_od_statnhm_{month}"
        files.extend(sorted(month_dir.glob("*.csv")))
    return files


class MemSampler:
    """현재 프로세스 + 자식 프로세스(Spark JVM 포함) RSS 합의 피크값을 0.2초 간격 샘플링."""

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
        self.peak_mb = max(self.peak_mb, total / (1024 * 1024))

    def _run(self) -> None:
        while not self._stop.is_set():
            self._sample_once()
            time.sleep(self.interval)

    def start(self) -> "MemSampler":
        self._sample_once()
        self._thread.start()
        return self

    def stop(self) -> float:
        self._stop.set()
        self._thread.join(timeout=2)
        self._sample_once()
        return self.peak_mb
