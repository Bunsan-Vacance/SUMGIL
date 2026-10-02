"""CROWD 승하차 raw 원문 재집계 잡 (S15P21A104-340, P3) — pandas 롱 포맷과의 일치를 검증한다.

D-1 수집기(`DATA_ENGINE/collect/subway_ridership_daily.py`)가 쌓는 raw 원문
(`data/CROWD/raw/ridership_daily/dt=<D>/getStnPsgr.parquet`, 카드·사용자 구분별 행)을 Spark로
**다시 집계**해 `to_long`(pandas 원본 함수)과 같은 롱 포맷 패널을 만든다. 재현 대상 규칙:

1. `date`는 raw의 `pasngDe`(YYYYMMDD) 값을 쓴다(파티션 경로의 `dt`가 아니다).
2. `(date, line, station_no, station_name, time_slot)`별로 카드·사용자 구분 행을 합산한다
   (`rideNope`->boarding, `gffNope`->alighting). `time_slot`은 `HOUR_TO_SLOT`(24시간 -> 20슬롯).
3. boarding/alighting을 `direction`·`passengers` 두 컬럼으로 펼친다(melt).
4. 출력 컬럼은 `LONG_COLUMNS` + `source`·`collected_at`, `(date, line, station_no, time_slot,
   direction)` 기준 정렬.

입력: `--input-root` 아래 파티션. 기본은 `--years`(기본 2026)의 `dt=<연도>-*`만, `--full`이면 전 파티션.
`--base-panel`(고정 2024-2025 패널 parquet)을 주면 이어 붙인다 - 겹치는 날짜는 새 집계가 우선.
패널이 와이드(boarding·alighting 컬럼)이면 롱으로 펼쳐 키 컬럼만 쓴다(달력·기상 등 파생 컬럼은
이 잡의 범위 밖).

출력: `<out-root>/panel_<run>.parquet`(롱 포맷)과 `<out-root>/meta.json`(입력 파티션 수·행수·결손일·
소요 초·피크 RSS·Spark 설정·검증 결과). 유일성 키 중복이 있으면 아무것도 쓰지 않고 exit 2.
이벤트 표는 별도 잡에서 다룬다.

검증: `--verify-against`(pandas 기준 롱 parquet)가 있으면 양쪽을 공통 날짜 범위로 자른 뒤
키 full outer join으로 대조한다. `max_abs_err <= --tolerance` 이고 행수·키가 모두 일치하면 통과,
아니면 stderr에 요약하고 exit 1(meta에는 결과를 남긴다).

실행:
    cd AI
    python -m DATA_ENGINE.spark.jobs.crowd_panel_rebuild \\
        --base-panel data/CROWD/processed/crowd_panel_2024_2025.parquet \\
        --verify-against data/CROWD/interim/crowd_recent_ridership_long.parquet

드라이버 수집 없음 — 전 단계 Spark DataFrame, 출력은 mapInArrow + pyarrow 스트리밍 단일 파일(Hadoop 네이티브 불필요).
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# mapInArrow 파이썬 워커가 현재 인터프리터를 쓰게 한다(Windows에서 PATH의 python 스텁 방지).
os.environ.setdefault("PYSPARK_PYTHON", sys.executable)

AI_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(AI_ROOT))

from DATA_ENGINE.collect.common import now_kst  # noqa: E402
from DATA_ENGINE.collect.subway_ridership_daily import (  # noqa: E402
    HOUR_TO_SLOT,
    LONG_COLUMNS,
    SOURCE,
)
from DATA_ENGINE.spark.session import build_spark_session  # noqa: E402

DEFAULT_INPUT_ROOT = AI_ROOT / "data" / "CROWD" / "raw" / "ridership_daily"
DEFAULT_OUTPUT_ROOT = AI_ROOT / "data" / "CROWD" / "processed" / "auto"
RAW_FILE_NAME = "getStnPsgr.parquet"
RAW_NEEDED = ["pasngDe", "pasngHr", "lineNm", "stnCd", "stnNm", "rideNope", "gffNope"]
OUT_COLUMNS = [*LONG_COLUMNS, "source", "collected_at"]
KEY_COLS = ["date", "line", "station_no", "time_slot", "direction"]
GROUP_COLS = ["date", "line", "station_no", "station_name", "time_slot"]
BASE_SOURCE = "base_panel"
EXIT_VERIFY_FAIL = 1
EXIT_DUPLICATE_KEY = 2


def partition_files(root: Path, years: list[int] | None) -> list[Path]:
    """`dt=*` 파티션의 raw 파일 목록. `years=None`이면 전부, 아니면 해당 연도 파티션만."""
    pattern_years = [f"{y:04d}" for y in years] if years else ["*"]
    files: list[Path] = []
    for y in pattern_years:
        files += root.glob(f"dt={y}-*/{RAW_FILE_NAME}")
    return sorted(set(files))


def _read_raw(spark, files: list[Path]):
    """raw 파일들을 하나의 DataFrame으로 읽는다. 읽을 파일이 없으면 None.

    수집 시기에 따라 컬럼 타입이 섞여 있을 수 있어(문자열/정수) 파일 스키마가 같은 것끼리 묶어 읽고,
    필요한 컬럼만 문자열로 맞춘 뒤 `unionByName` 한다.
    """
    import pyarrow.parquet as pq
    from pyspark.sql import functions as F

    groups: dict[tuple, list[str]] = {}
    for f in files:
        schema = pq.read_schema(f)
        if not set(RAW_NEEDED) <= set(schema.names):
            continue  # 0건 날의 빈 파일 등 - 집계할 행이 없다
        sig = tuple((n, str(schema.field(n).type)) for n in RAW_NEEDED)
        groups.setdefault(sig, []).append(str(f))

    frames = [
        spark.read.parquet(*paths).select(*[F.col(c).cast("string").alias(c) for c in RAW_NEEDED])
        for paths in groups.values()
    ]
    if not frames:
        return None
    out = frames[0]
    for df in frames[1:]:
        out = out.unionByName(df)
    return out


def _empty_long(spark):
    """`LONG_COLUMNS` 스키마의 빈 DataFrame(입력이 없을 때)."""
    from pyspark.sql import types as T

    return spark.createDataFrame(
        [],
        T.StructType(
            [
                T.StructField("date", T.TimestampNTZType()),
                T.StructField("line", T.StringType()),
                T.StructField("station_no", T.LongType()),
                T.StructField("station_name", T.StringType()),
                T.StructField("direction", T.StringType()),
                T.StructField("passengers", T.DoubleType()),
                T.StructField("time_slot", T.StringType()),
            ]
        ),
    ).select(*LONG_COLUMNS)


def aggregate_long_spark(spark, files: list[Path]):
    """`to_long` 규칙(합산 -> 슬롯 매핑 -> melt)을 Spark로 재현해 Spark DataFrame으로 돌려준다.

    드라이버로 수집하지 않는다. `source`·`collected_at`은 붙이지 않는다(호출부가 채운다).
    타입은 `date` timestamp_ntz(자정)·`station_no` long·`passengers` double, 입력이 비면 같은
    스키마의 빈 DataFrame.
    """
    from pyspark.sql import functions as F

    raw = _read_raw(spark, files)
    if raw is None:
        return _empty_long(spark)

    slot_map = F.create_map(*[x for h, s in HOUR_TO_SLOT.items() for x in (F.lit(h), F.lit(s))])
    df = raw.select(
        F.to_date(F.col("pasngDe"), "yyyyMMdd").cast("timestamp_ntz").alias("date"),
        F.col("lineNm").alias("line"),
        F.col("stnCd").cast("long").alias("station_no"),
        F.col("stnNm").alias("station_name"),
        slot_map[F.col("pasngHr").cast("int")].alias("time_slot"),
        F.col("rideNope").cast("double").alias("boarding"),
        F.col("gffNope").cast("double").alias("alighting"),
    )
    # pandas groupby.sum은 전부 NaN인 그룹도 0이라 coalesce로 맞춘다.
    agg = df.groupBy(*GROUP_COLS).agg(
        F.coalesce(F.sum("boarding"), F.lit(0.0)).alias("boarding"),
        F.coalesce(F.sum("alighting"), F.lit(0.0)).alias("alighting"),
    )
    return _melt(agg)


def _melt(agg):
    """boarding/alighting 두 컬럼을 `direction`·`passengers`로 펼쳐 `LONG_COLUMNS` 순서로 돌려준다."""
    from pyspark.sql import functions as F

    parts = [
        agg.select(
            *GROUP_COLS,
            F.lit(d).alias("direction"),
            F.col(d).cast("double").alias("passengers"),
        )
        for d in ("boarding", "alighting")
    ]
    return parts[0].unionByName(parts[1]).select(*LONG_COLUMNS)


def to_pandas_long(df) -> pd.DataFrame:
    """테스트·소규모 확인용 - Spark 롱 DataFrame을 pandas로 수집한다(전량 파이프라인에서 쓰지 않는다)."""
    out = df.toPandas()
    if out.empty:
        return pd.DataFrame(columns=LONG_COLUMNS)
    out["date"] = pd.to_datetime(out["date"])
    out["station_no"] = out["station_no"].astype("int64")
    out["passengers"] = out["passengers"].astype("float64")
    return out[LONG_COLUMNS].sort_values(KEY_COLS, ignore_index=True)


def check_keys(df, label: str) -> None:
    """키 컬럼 결측은 예외(`to_long`의 errors="raise"에 해당). 유일성 위반은 호출부가 exit 2."""
    from pyspark.sql import functions as F

    any_null = F.lit(False)
    for c in KEY_COLS:
        any_null = any_null | F.col(c).isNull()
    bad = df.filter(any_null).count()
    if bad:
        raise ValueError(f"{label}: 키 컬럼 결측 {bad}행 (날짜·역코드·시간대 파싱 실패)")


def duplicate_keys(df) -> int:
    """유일성 키 중복 행 수(`sum(count - 1)`, pandas `duplicated().sum()`과 같은 의미)."""
    from pyspark.sql import functions as F

    row = (
        df.groupBy(*KEY_COLS)
        .count()
        .filter(F.col("count") > 1)
        .agg(F.sum(F.col("count") - 1).alias("dup"))
        .first()
    )
    return int(row["dup"] or 0)


def missing_days(dates: pd.Series) -> list[str]:
    """집계된 날짜의 최소~최대 사이에서 데이터가 없는 날(ISO) 목록."""
    if dates.empty:
        return []
    have = {pd.Timestamp(d).normalize() for d in dates.unique()}
    days = pd.date_range(min(have), max(have), freq="D")
    return [d.date().isoformat() for d in days if d not in have]


def _norm_date(df):
    """`date` 컬럼을 timestamp_ntz 자정으로 정규화한다."""
    from pyspark.sql import functions as F

    return df.withColumn("date", F.col("date").cast("date").cast("timestamp_ntz"))


def load_base_panel(spark, path: Path):
    """고정 패널을 롱 포맷 Spark DataFrame으로 읽는다. 와이드(boarding·alighting)면 펼치고 키 컬럼만 쓴다."""
    from pyspark.sql import functions as F

    base = spark.read.parquet(str(path))
    if {"direction", "passengers"} <= set(base.columns):
        long_df = base.select(
            *[F.col(c) if c in base.columns else F.lit(None).alias(c) for c in LONG_COLUMNS]
        )
    else:
        cols = [c for c in GROUP_COLS if c in base.columns]
        wide = base.select(*cols, "boarding", "alighting")
        for c in GROUP_COLS:
            if c not in cols:
                wide = wide.withColumn(c, F.lit(None))
        long_df = _melt(wide)
    long_df = _norm_date(long_df)
    return (
        long_df.withColumn("station_no", F.col("station_no").cast("long"))
        .withColumn("passengers", F.col("passengers").cast("double"))
        .withColumn("source", F.lit(BASE_SOURCE))
        .withColumn("collected_at", F.lit(None).cast("timestamp_ntz"))
        .select(*OUT_COLUMNS)
    )


def union_with_base(new, base):
    """겹치는 날짜는 새 집계 우선 - 그 날짜의 base 행은 통째로 버린다(`merge_recent`와 같은 규칙)."""
    new_dates = new.select("date").distinct()
    keep = base.join(new_dates, on="date", how="left_anti")
    return keep.unionByName(new.select(*OUT_COLUMNS))


def verify_against(spark, new, pandas_path: Path, tolerance: float) -> dict:
    """공통 날짜 범위로 자른 뒤 키 full outer join으로 대조한다(드라이버 수집 없음). 판정은 `passed`."""
    from pyspark.sql import functions as F

    ref = _norm_date(spark.read.parquet(str(pandas_path))).select(*KEY_COLS, "passengers")
    cur = new.select(*KEY_COLS, "passengers")
    lo_r, hi_r = ref.agg(F.min("date"), F.max("date")).first()
    lo_s, hi_s = cur.agg(F.min("date"), F.max("date")).first()
    if lo_r is None or lo_s is None:
        return {"passed": False, "reason": "비교할 행이 없음", "tolerance": tolerance}
    lo, hi = max(lo_r, lo_s), min(hi_r, hi_s)
    if lo > hi:
        return {"passed": False, "reason": "공통 날짜 범위 없음", "tolerance": tolerance}
    lo_d, hi_d = lo.date(), hi.date()

    def _clip(df):
        d = F.col("date").cast("date")
        return df.filter((d >= F.lit(lo_d)) & (d <= F.lit(hi_d)))

    left = _clip(ref).withColumnRenamed("passengers", "p_pandas").withColumn("_l", F.lit(1))
    right = _clip(cur).withColumnRenamed("passengers", "p_spark").withColumn("_r", F.lit(1))
    rows_pandas, rows_spark = left.count(), right.count()
    agg = (
        left.join(right, on=KEY_COLS, how="full_outer")
        .agg(
            F.count(F.when(F.col("_l").isNotNull() & F.col("_r").isNotNull(), 1)).alias("both"),
            F.max(F.abs(F.col("p_pandas") - F.col("p_spark"))).alias("max_err"),
        )
        .first()
    )
    rows_match = bool(rows_pandas == rows_spark and agg["both"] == rows_pandas)
    max_abs_err = float(agg["max_err"]) if agg["max_err"] is not None else 0.0
    passed = bool(max_abs_err <= tolerance and rows_match and rows_pandas > 0)
    return {
        "passed": passed,
        "range": [lo_d.isoformat(), hi_d.isoformat()],
        "tolerance": tolerance,
        "rows_pandas": int(rows_pandas),
        "rows_spark": int(rows_spark),
        "rows_match": rows_match,
        "max_abs_err": max_abs_err,
    }


def _peak_rss_mb() -> float | None:
    """`resource`는 Linux/macOS 전용 - Windows에서는 None. Linux ru_maxrss 단위는 KB."""
    try:
        import resource

        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    except ImportError:
        return None


def _write_parquet(df, path: Path) -> int:
    """KEY_COLS 정렬 후 `coalesce(1)` 파티션을 `mapInArrow`로 받아 pyarrow로 단일 parquet에 스트리밍한다.

    Spark `write.parquet`(Hadoop FS)을 거치지 않아 Windows에서도 네이티브 의존 없이 동작한다.
    드라이버로 수집하지 않고 배치 하나씩만 메모리에 둔다. 임시 파일에 쓴 뒤 rename(원자적).
    쓴 행 수를 돌려준다.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq
    from pyspark.sql import functions as F

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp_str = str(tmp)

    def _sink(batches):
        writer = None
        n = 0
        try:
            for b in batches:
                if writer is None:
                    writer = pq.ParquetWriter(tmp_str, b.schema)
                writer.write_batch(b)
                n += b.num_rows
        finally:
            if writer is not None:
                writer.close()
        yield pa.RecordBatch.from_pylist([{"rows": n}], schema=pa.schema([("rows", pa.int64())]))

    try:
        ordered = df.orderBy(*KEY_COLS).coalesce(1)
        total = ordered.mapInArrow(_sink, "rows long").agg(F.sum("rows")).first()[0] or 0
        if total == 0:  # 배치가 없으면 writer도 없다 - 스키마만 가진 빈 parquet
            to_pandas_long(df.limit(0)).to_parquet(tmp, index=False)
        tmp.replace(path)
        return int(total)
    finally:
        tmp.unlink(missing_ok=True)


def run(args: argparse.Namespace) -> int:
    from pyspark.sql import functions as F

    t0 = time.perf_counter()
    run_id = args.run or now_kst().strftime("%Y%m%d-%H%M")
    files = partition_files(args.input_root, None if args.full else args.years)
    if not files:
        print(f"[crowd_panel_rebuild] 입력 파티션 없음: {args.input_root}", file=sys.stderr)
        return EXIT_VERIFY_FAIL
    print(f"[crowd_panel_rebuild] 입력 {len(files)}개 파티션: {args.input_root}")

    spark = build_spark_session(
        "crowd-panel-rebuild", cores=args.cores, driver_memory=args.driver_memory
    )
    try:
        spark.conf.set("spark.sql.parquet.outputTimestampType", "TIMESTAMP_MICROS")
        spark_conf = {
            "master": spark.sparkContext.master,
            "cores": args.cores,
            "driver_memory": args.driver_memory,
            "shuffle_partitions": spark.conf.get("spark.sql.shuffle.partitions"),
            "version": spark.version,
        }
        collected_at = pd.Timestamp(now_kst()).tz_localize(None).isoformat(sep=" ")
        new = (
            aggregate_long_spark(spark, files)
            .withColumn("source", F.lit(SOURCE))
            .withColumn("collected_at", F.lit(collected_at).cast("timestamp_ntz"))
            .select(*OUT_COLUMNS)
        )
        check_keys(new, "새 집계")
        new_dates = pd.Series([r["date"] for r in new.select("date").distinct().collect()])
        meta: dict = {
            "run": run_id,
            "input_root": str(args.input_root),
            "full": bool(args.full),
            "years": None if args.full else args.years,
            "input_partitions": len(files),
            "new_rows": new.count(),
            "missing_days": missing_days(new_dates),
            "spark": spark_conf,
            "driver_collect": False,
        }

        panel = new
        if args.base_panel:
            panel = union_with_base(new, load_base_panel(spark, args.base_panel))
            meta["base_panel"] = str(args.base_panel)
        dup_new, dup_final = duplicate_keys(new), duplicate_keys(panel)
        meta["duplicate_keys"] = {"new": dup_new, "final": dup_final}
        meta["panel_rows"] = panel.count()
        if dup_new or dup_final:
            print(
                f"[crowd_panel_rebuild] 유일성 키 중복 new={dup_new} final={dup_final} - 저장 안 함",
                file=sys.stderr,
            )
            return EXIT_DUPLICATE_KEY

        exit_code = 0
        if args.verify_against:
            verify = verify_against(spark, new, args.verify_against, args.tolerance)
            meta["verify"] = verify
            if not verify["passed"]:
                print(
                    "[crowd_panel_rebuild] 검증 실패: " + json.dumps(verify, ensure_ascii=False),
                    file=sys.stderr,
                )
                exit_code = EXIT_VERIFY_FAIL

        out_path = args.out_root / f"panel_{run_id}.parquet"
        written = _write_parquet(panel, out_path)
        meta["written_rows"] = written
        if written != meta["panel_rows"]:
            print(
                f"[crowd_panel_rebuild] 경고: 쓴 행 수 {written} != panel_rows {meta['panel_rows']}",
                file=sys.stderr,
            )
    finally:
        spark.stop()

    meta["output"] = str(out_path)
    meta["elapsed_sec"] = round(time.perf_counter() - t0, 2)
    meta["peak_rss_mb"] = _peak_rss_mb()
    meta["generated_at"] = now_kst().isoformat(timespec="seconds")
    (args.out_root / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"[crowd_panel_rebuild] 완료 -- {out_path} ({meta['panel_rows']:,}행)")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    ap.add_argument("--base-panel", type=Path, default=None, help="고정 패널 parquet(선택)")
    ap.add_argument("--out-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    ap.add_argument("--run", default=None, help="실행 ID(기본 KST YYYYMMDD-HHMM)")
    ap.add_argument("--full", action="store_true", help="전 파티션(없으면 --years 연도만)")
    ap.add_argument("--years", type=int, nargs="+", default=[2026], help="증분 대상 연도")
    ap.add_argument("--cores", default="3")
    ap.add_argument("--driver-memory", default="3g")
    ap.add_argument("--verify-against", type=Path, default=None, help="pandas 기준 롱 parquet")
    ap.add_argument("--tolerance", type=float, default=1e-6)
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
