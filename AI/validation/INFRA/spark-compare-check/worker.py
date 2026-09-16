"""벤치마크 셀 하나(OP x 스케일 x 엔진)를 실행하는 워커.

`bench.py`가 셀마다 이 스크립트를 별도 서브프로세스로 띄운다 — pandas가 OOM으로
죽거나(MemoryError) OS가 프로세스를 강제 종료해도 오케스트레이터 프로세스 자체는 죽지
않고 다음 셀로 넘어갈 수 있게 하기 위해서다. 결과는 `--out`에 JSON 한 덩어리로 쓴다.

모드:
  --mode bench      OP x 스케일 x 엔진 하나의 처리 시간·메모리 측정
  --mode accuracy   1x 스케일에서 pandas·Spark 결과값이 수치적으로 동일한지 검증
  --mode session    SparkSession 최초 생성(JVM 기동) 시간만 측정
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback

import pandas as pd
import pyarrow.parquet as pq
from common import DATA_PATHS, NEEDED_COLS, MemSampler, amplify_pandas, amplify_spark
from ops import OPS, op_a_spark, op_b_spark, op_c_spark

FLOAT_TOL = 1e-6

ACCURACY_KEYS = {
    "A": ["station_no", "time_slot", "date"],
    "B": ["station_no", "time_slot", "day_type", "direction"],
    "C": ["date", "line", "station_no", "time_slot"],
}


def base_row_count(op: str) -> int:
    """parquet 메타데이터만 읽어 행 수를 구한다(데이터 스캔 없음 — 중복 스캔 방지)."""
    return pq.ParquetFile(DATA_PATHS[op]).metadata.num_rows


def build_spark_session(master: str, shuffle_partitions: int):
    from pyspark.sql import SparkSession

    t0 = time.time()
    spark = (
        SparkSession.builder.appName(f"spark-compare-check-{master}")
        .master(master)
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", str(shuffle_partitions))
        .config("spark.driver.memory", "8g")
        .getOrCreate()
    )
    session_seconds = time.time() - t0
    return spark, session_seconds


def run_bench(args) -> dict:
    op = args.op
    result: dict = {
        "cell_id": args.cell_id,
        "op": op,
        "scale": args.scale,
        "engine": args.engine,
        "master": args.master,
        "shuffle_partitions": args.shuffle_partitions,
        "pivot_variant": args.pivot_variant,
    }

    sampler = MemSampler(interval=0.2).start()
    try:
        rows_in = base_row_count(op) * args.scale
        result["rows_in"] = rows_in

        if args.engine == "pandas":
            t0 = time.time()
            df = pd.read_parquet(DATA_PATHS[op], columns=NEEDED_COLS[op])
            t1 = time.time()
            df = amplify_pandas(df, args.scale)
            t2 = time.time()
            pandas_fn, _ = OPS[op]
            out = pandas_fn(df)
            rows_out = len(out)
            t3 = time.time()

            result.update(
                read_seconds=t1 - t0,
                amplify_seconds=t2 - t1,
                compute_seconds=t3 - t2,
                rows_out=rows_out,
                status="ok",
            )
        else:
            spark, session_seconds = build_spark_session(args.master, args.shuffle_partitions)
            try:
                t0 = time.time()
                sdf = spark.read.parquet(str(DATA_PATHS[op])).select(NEEDED_COLS[op])
                t1 = time.time()  # Spark는 lazy이므로 여기까지는 실행계획 구성 시간뿐이다.
                sdf = amplify_spark(sdf, args.scale)
                t2 = time.time()

                if op == "C" and args.pivot_variant == "explicit":
                    out_sdf = op_c_spark(sdf, pivot_values=["boarding", "alighting"])
                elif op == "A":
                    out_sdf = op_a_spark(sdf)
                elif op == "B":
                    out_sdf = op_b_spark(sdf)
                else:
                    out_sdf = op_c_spark(sdf)

                rows_out = out_sdf.count()  # materialize (lazy 실행 강제)
                t3 = time.time()

                result.update(
                    session_seconds=session_seconds,
                    read_seconds=t1 - t0,
                    amplify_seconds=t2 - t1,
                    compute_seconds=t3 - t2,
                    rows_out=rows_out,
                    status="ok",
                )
            finally:
                spark.stop()

        wall = (
            result.get("read_seconds", 0)
            + result.get("amplify_seconds", 0)
            + result.get("compute_seconds", 0)
        )
        result["wall_seconds"] = wall
        if result.get("compute_seconds", 0) > 0:
            result["rows_per_sec"] = result["rows_out"] / result["compute_seconds"]
        else:
            result["rows_per_sec"] = None
    except MemoryError:
        result["status"] = "oom"
        result["error"] = "MemoryError"
    except Exception as exc:
        msg = str(exc)
        result["status"] = (
            "oom" if "OutOfMemory" in msg or "java.lang.OutOfMemoryError" in msg else "error"
        )
        result["error"] = f"{type(exc).__name__}: {msg[:2000]}"
        result["traceback"] = traceback.format_exc()[-4000:]
    finally:
        result["peak_rss_mb"] = sampler.stop()

    return result


def _normalize_date(df: pd.DataFrame, col: str = "date") -> pd.DataFrame:
    df = df.copy()
    if col in df.columns:
        df[col] = pd.to_datetime(df[col])
    return df


def run_accuracy(args) -> dict:
    op = args.op
    keys = ACCURACY_KEYS[op]
    result = {"cell_id": args.cell_id, "op": op, "mode": "accuracy"}
    try:
        pandas_fn, spark_fn = OPS[op]

        pdf_in = pd.read_parquet(DATA_PATHS[op], columns=NEEDED_COLS[op])
        pdf_out = _normalize_date(pandas_fn(pdf_in))

        spark, _ = build_spark_session(args.master, args.shuffle_partitions)
        try:
            sdf_in = spark.read.parquet(str(DATA_PATHS[op])).select(NEEDED_COLS[op])
            sdf_out = spark_fn(sdf_in)
            spf_out = _normalize_date(sdf_out.toPandas())
        finally:
            spark.stop()

        pdf_sorted = pdf_out.sort_values(keys).reset_index(drop=True)
        spf_sorted = spf_out.sort_values(keys).reset_index(drop=True)

        rows_pandas, rows_spark = len(pdf_sorted), len(spf_sorted)
        result["rows_pandas"] = rows_pandas
        result["rows_spark"] = rows_spark
        result["rows_match"] = rows_pandas == rows_spark

        if not result["rows_match"]:
            result["status"] = "mismatch"
            result["max_abs_diff"] = None
        else:
            merged = pdf_sorted.merge(spf_sorted, on=keys, suffixes=("_pd", "_sp"))
            numeric_cols = [
                c
                for c in pdf_sorted.columns
                if c not in keys and pd.api.types.is_numeric_dtype(pdf_sorted[c])
            ]
            per_col = {}
            null_mismatches = {}
            max_diff = 0.0
            for c in numeric_cols:
                cp, cs = f"{c}_pd", f"{c}_sp"
                if cp not in merged.columns or cs not in merged.columns:
                    continue
                null_p = merged[cp].isna()
                null_s = merged[cs].isna()
                mismatch = int((null_p != null_s).sum())
                null_mismatches[c] = mismatch
                both_valid = ~null_p & ~null_s
                if both_valid.any():
                    diff = (merged.loc[both_valid, cp] - merged.loc[both_valid, cs]).abs()
                    col_max = float(diff.max())
                else:
                    col_max = 0.0
                per_col[c] = col_max
                max_diff = max(max_diff, col_max)

            result["per_column_max_abs_diff"] = per_col
            result["null_mismatches"] = null_mismatches
            result["max_abs_diff"] = max_diff
            any_null_mismatch = any(v > 0 for v in null_mismatches.values())
            result["status"] = (
                "ok" if max_diff <= FLOAT_TOL and not any_null_mismatch else "mismatch"
            )
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {str(exc)[:2000]}"
        result["traceback"] = traceback.format_exc()[-4000:]
    return result


def run_session(args) -> dict:
    result = {"cell_id": args.cell_id, "mode": "session", "master": args.master}
    try:
        spark, session_seconds = build_spark_session(args.master, args.shuffle_partitions)
        result["session_seconds"] = session_seconds
        result["status"] = "ok"
        spark.stop()
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {str(exc)[:2000]}"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["bench", "accuracy", "session"], default="bench")
    parser.add_argument("--op", choices=["A", "B", "C"])
    parser.add_argument("--engine", choices=["pandas", "spark"])
    parser.add_argument("--scale", type=int, default=1)
    parser.add_argument("--master", default="local[*]")
    parser.add_argument("--shuffle-partitions", type=int, default=200)
    parser.add_argument("--pivot-variant", choices=["auto", "explicit"], default="auto")
    parser.add_argument("--cell-id", dest="cell_id", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    if args.mode == "bench":
        result = run_bench(args)
    elif args.mode == "accuracy":
        result = run_accuracy(args)
    else:
        result = run_session(args)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, default=str)

    sys.exit(0)


if __name__ == "__main__":
    main()
