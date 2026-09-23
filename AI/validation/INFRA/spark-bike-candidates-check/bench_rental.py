"""후보 1(대여이력) 벤치 — 실제 원본으로 pandas vs Spark, 1/3/6/12개월 스윕.

실행:
    cd AI/validation/INFRA/spark-bike-candidates-check
    python bench_rental.py --months 1,3,6,12
"""

from __future__ import annotations

import argparse
import gc
import io
import json
import sys
import time
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

from common import MemSampler, RESULTS_PATH, rental_history_files, rental_history_months
from rental_ops import op_pandas, op_spark, read_rental_pandas, read_rental_spark


def make_spark(app_name: str):
    from pyspark.sql import SparkSession

    return (
        SparkSession.builder.appName(app_name)
        .master("local[*]")
        .config("spark.driver.memory", "8g")
        .config("spark.sql.shuffle.partitions", "200")
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate()
    )


def compare_accuracy(pdf: pd.DataFrame, sdf_pandas: pd.DataFrame) -> dict:
    left = pdf.set_index(["station_id", "dow", "slot_5m"]).sort_index()
    right = sdf_pandas.set_index(["station_id", "dow", "slot_5m"]).sort_index()
    common_idx = left.index.intersection(right.index)
    row_match = len(left) == len(right) == len(common_idx)
    max_abs_err = (
        float(
            np.max(
                np.abs(
                    left.loc[common_idx, "net_flow"].to_numpy()
                    - right.loc[common_idx, "net_flow"].to_numpy()
                )
            )
        )
        if len(common_idx)
        else float("nan")
    )
    return {
        "rows_pandas": len(left),
        "rows_spark": len(right),
        "rows_match": row_match,
        "max_abs_err": max_abs_err,
    }


def run_scale(month_count: int, all_months: list[str]) -> dict:
    months = all_months[:month_count]
    files = rental_history_files(months)
    n_files = len(files)
    print(f"[rental] months={month_count} files={n_files}")

    # ── pandas ──
    gc.collect()
    sampler = MemSampler().start()
    t0 = time.perf_counter()
    pdf_raw = read_rental_pandas(files)
    n_rows_raw = len(pdf_raw)
    pdf_result = op_pandas(pdf_raw)
    pandas_wall = time.perf_counter() - t0
    pandas_peak_mb = sampler.stop()
    del pdf_raw
    gc.collect()

    # ── spark ──
    spark = make_spark(f"rental-bench-{month_count}m")
    try:
        sdf_raw, convert_sec = read_rental_spark(
            spark, files
        )  # UTF-8 변환은 시간 밖(1회성 준비 비용)
        sampler = MemSampler().start()
        t0 = time.perf_counter()
        sdf_result = op_spark(sdf_raw)
        spark_pdf = sdf_result.toPandas()
        spark_wall = time.perf_counter() - t0
        spark_peak_mb = sampler.stop()
    finally:
        spark.stop()

    acc = compare_accuracy(pdf_result, spark_pdf)

    result = {
        "op": "rental_history_agg",
        "months": month_count,
        "files": n_files,
        "raw_rows": n_rows_raw,
        "pandas_wall_sec": round(pandas_wall, 2),
        "spark_wall_sec": round(spark_wall, 2),
        "ratio_spark_over_pandas": round(spark_wall / pandas_wall, 3),
        "pandas_peak_mb": round(pandas_peak_mb, 1),
        "spark_peak_mb": round(spark_peak_mb, 1),
        "spark_utf8_convert_sec": round(convert_sec, 2),
        **acc,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", default="1,3,6,12", help="쉼표 구분 월 수 목록")
    args = ap.parse_args()

    all_months = rental_history_months()
    print(f"[rental] 사용 가능한 월 {len(all_months)}개: {all_months[0]} ~ {all_months[-1]}")

    results = []
    for m in [int(x) for x in args.months.split(",")]:
        if m > len(all_months):
            print(f"[rental] skip months={m} (보유 {len(all_months)}개월뿐)")
            continue
        results.append(run_scale(m, all_months))

    with open(RESULTS_PATH, "a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[rental] 완료 — {RESULTS_PATH}")


if __name__ == "__main__":
    main()
