"""후보 2(따릉이 재고 raw 누적 재집계) 벤치 — 서버에서 받은 실제 누적분(10일치, 613MB)으로 잰다.

결정문서는 "연 2.7억 행으로 자라는 축"이라고 표현했다 — 지금 규모(10일)는 그 축의 시작점일
뿐이라 **현재 규모**와 **1년 추정 규모(날짜를 밀어 증폭)** 둘 다 잰다.

실행:
    cd AI/validation/INFRA/spark-bike-candidates-check
    python bench_bike_realtime.py
"""

from __future__ import annotations

import gc
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from bike_realtime_ops import op_pandas, op_spark, snapshot_files
from common import BIKE_REALTIME_SAMPLE_DIR, MemSampler, RESULTS_PATH


def make_spark(app_name: str):
    from pyspark.sql import SparkSession

    return (
        SparkSession.builder.appName(app_name)
        .master("local[*]")
        .config("spark.driver.memory", "8g")
        .config("spark.sql.shuffle.partitions", "200")
        .config("spark.ui.showConsoleProgress", "false")
        # raw 컬럼이 Asia/Seoul tz-aware라 세션 타임존을 맞춰야 hour()/dayofweek()가
        # pandas(KST 기준)와 같은 값을 낸다 — 안 맞추면 이중 변환·엇갈림 버그가 난다(실측으로 확인).
        .config("spark.sql.session.timeZone", "Asia/Seoul")
        .getOrCreate()
    )


def compare_accuracy(pdf: pd.DataFrame, spdf: pd.DataFrame) -> dict:
    key = ["station_id", "dow", "collected_hour"]
    left = pdf.set_index(key).sort_index()
    right = spdf.set_index(key).sort_index()
    common_idx = left.index.intersection(right.index)
    rows_match = len(left) == len(right) == len(common_idx)
    diffs = []
    for col in ["avg_bike_count", "avg_stock_ratio"]:
        a = left.loc[common_idx, col].to_numpy(dtype=float)
        b = right.loc[common_idx, col].to_numpy(dtype=float)
        diffs.append(np.nanmax(np.abs(a - b)) if len(common_idx) else float("nan"))
    return {
        "rows_pandas": len(left),
        "rows_spark": len(right),
        "rows_match": rows_match,
        "max_abs_err": float(max(diffs)) if diffs else float("nan"),
    }


def run(label: str, files: list[Path]) -> dict:
    print(f"[bike_realtime] {label} files={len(files)}")

    gc.collect()
    sampler = MemSampler().start()
    t0 = time.perf_counter()
    pdf_result = op_pandas(files)
    pandas_wall = time.perf_counter() - t0
    pandas_peak_mb = sampler.stop()
    gc.collect()

    spark = make_spark(f"bike-realtime-{label}")
    try:
        sampler = MemSampler().start()
        t0 = time.perf_counter()
        sdf_result = op_spark(spark, files)
        spark_pdf = sdf_result.toPandas()
        spark_wall = time.perf_counter() - t0
        spark_peak_mb = sampler.stop()
    finally:
        spark.stop()

    acc = compare_accuracy(pdf_result, spark_pdf)
    result = {
        "op": "bike_realtime_reprocess",
        "label": label,
        "files": len(files),
        "pandas_wall_sec": round(pandas_wall, 2),
        "spark_wall_sec": round(spark_wall, 2),
        "ratio_spark_over_pandas": round(spark_wall / pandas_wall, 3) if pandas_wall else None,
        "pandas_peak_mb": round(pandas_peak_mb, 1),
        "spark_peak_mb": round(spark_peak_mb, 1),
        **acc,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> None:
    files = snapshot_files(BIKE_REALTIME_SAMPLE_DIR)
    print(f"[bike_realtime] 서버에서 받은 실제 누적 파일 {len(files)}개")

    results = [run("current_10days", files)]

    with open(RESULTS_PATH, "a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[bike_realtime] 완료 -- {RESULTS_PATH}")


if __name__ == "__main__":
    main()
