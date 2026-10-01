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
`compare_frames`로 대조한다. `max_abs_err <= --tolerance` 이고 행수·키가 모두 일치하면 통과,
아니면 stderr에 요약하고 exit 1(meta에는 결과를 남긴다).

실행:
    cd AI
    python -m DATA_ENGINE.spark.jobs.crowd_panel_rebuild \\
        --base-panel data/CROWD/processed/crowd_panel_2024_2025.parquet \\
        --verify-against data/CROWD/interim/crowd_recent_ridership_long.parquet
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

import pandas as pd

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

AI_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(AI_ROOT))

from DATA_ENGINE.collect.common import now_kst  # noqa: E402
from DATA_ENGINE.collect.subway_ridership_daily import (  # noqa: E402
    HOUR_TO_SLOT,
    LONG_COLUMNS,
    SOURCE,
)
from DATA_ENGINE.spark.metrics import compare_frames  # noqa: E402
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


def aggregate_long_spark(spark, files: list[Path]) -> pd.DataFrame:
    """`to_long` 규칙(합산 -> 슬롯 매핑 -> melt)을 Spark로 재현해 pandas로 돌려준다.

    `source`·`collected_at`은 붙이지 않는다(호출부가 상수로 채운다). 입력이 비면 빈 프레임.
    """
    from pyspark.sql import functions as F

    empty = pd.DataFrame(columns=LONG_COLUMNS)
    raw = _read_raw(spark, files)
    if raw is None:
        return empty

    slot_map = F.create_map(*[x for h, s in HOUR_TO_SLOT.items() for x in (F.lit(h), F.lit(s))])
    df = raw.select(
        F.date_format(F.to_date(F.col("pasngDe"), "yyyyMMdd"), "yyyy-MM-dd").alias("date"),
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
    long_df = agg.select(
        *GROUP_COLS, F.lit("boarding").alias("direction"), F.col("boarding").alias("passengers")
    ).unionByName(
        agg.select(
            *GROUP_COLS,
            F.lit("alighting").alias("direction"),
            F.col("alighting").alias("passengers"),
        )
    )
    out = long_df.toPandas()
    if out.empty:
        return empty
    out["date"] = pd.to_datetime(out["date"])
    out["station_no"] = out["station_no"].astype("int64")
    out["passengers"] = out["passengers"].astype("float64")
    return out[LONG_COLUMNS].sort_values(KEY_COLS, ignore_index=True)


def check_keys(df: pd.DataFrame, label: str) -> None:
    """키 컬럼 결측은 예외(`to_long`의 errors="raise"에 해당). 유일성 위반은 호출부가 exit 2."""
    bad = int(df[KEY_COLS].isna().any(axis=1).sum())
    if bad:
        raise ValueError(f"{label}: 키 컬럼 결측 {bad}행 (날짜·역코드·시간대 파싱 실패)")


def duplicate_keys(df: pd.DataFrame) -> int:
    return int(df.duplicated(KEY_COLS).sum())


def missing_days(dates: pd.Series) -> list[str]:
    """집계된 날짜의 최소~최대 사이에서 데이터가 없는 날(ISO) 목록."""
    if dates.empty:
        return []
    have = {pd.Timestamp(d).normalize() for d in dates.unique()}
    days = pd.date_range(min(have), max(have), freq="D")
    return [d.date().isoformat() for d in days if d not in have]


def load_base_panel(path: Path) -> pd.DataFrame:
    """고정 패널을 롱 포맷으로 읽는다. 와이드(boarding·alighting)면 펼치고 키 컬럼만 쓴다."""
    base = pd.read_parquet(path)
    base["date"] = pd.to_datetime(base["date"]).dt.normalize()
    if {"direction", "passengers"} <= set(base.columns):
        long_df = base.reindex(columns=LONG_COLUMNS)
    else:
        long_df = base.melt(
            id_vars=[c for c in GROUP_COLS if c in base.columns],
            value_vars=["boarding", "alighting"],
            var_name="direction",
            value_name="passengers",
        ).reindex(columns=LONG_COLUMNS)
    long_df["station_no"] = long_df["station_no"].astype("int64")
    long_df["passengers"] = long_df["passengers"].astype("float64")
    long_df["source"] = BASE_SOURCE
    long_df["collected_at"] = pd.NaT
    return long_df


def union_with_base(new: pd.DataFrame, base: pd.DataFrame) -> pd.DataFrame:
    """겹치는 날짜는 새 집계 우선 - 그 날짜의 base 행은 통째로 버린다(`merge_recent`와 같은 규칙)."""
    keep = base[~base["date"].isin(new["date"].unique())]
    parts = [p.dropna(axis=1, how="all") for p in (keep, new) if not p.empty]
    out = pd.concat(parts, ignore_index=True) if parts else new
    return out.reindex(columns=OUT_COLUMNS).sort_values(KEY_COLS, ignore_index=True)


def verify_against(spark_long: pd.DataFrame, pandas_path: Path, tolerance: float) -> dict:
    """공통 날짜 범위로 자른 뒤 `compare_frames`로 대조한다. 판정은 `passed`."""
    pandas_df = pd.read_parquet(pandas_path)
    pandas_df["date"] = pd.to_datetime(pandas_df["date"]).dt.normalize()
    if spark_long.empty or pandas_df.empty:
        return {"passed": False, "reason": "비교할 행이 없음", "tolerance": tolerance}
    lo = max(spark_long["date"].min(), pandas_df["date"].min())
    hi = min(spark_long["date"].max(), pandas_df["date"].max())
    if lo > hi:
        return {"passed": False, "reason": "공통 날짜 범위 없음", "tolerance": tolerance}
    left = pandas_df[pandas_df["date"].between(lo, hi)]
    right = spark_long[spark_long["date"].between(lo, hi)]
    res = compare_frames(left, right, key_cols=KEY_COLS, value_cols=["passengers"])
    passed = bool(res["max_abs_err"] <= tolerance and res["rows_match"] and res["rows_pandas"] > 0)
    return {
        "passed": passed,
        "range": [lo.date().isoformat(), hi.date().isoformat()],
        "tolerance": tolerance,
        **res,
    }


def _peak_rss_mb() -> float | None:
    """`resource`는 Linux/macOS 전용 - Windows에서는 None. Linux ru_maxrss 단위는 KB."""
    try:
        import resource

        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    except ImportError:
        return None


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


def run(args: argparse.Namespace) -> int:
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
        spark_conf = {
            "master": spark.sparkContext.master,
            "cores": args.cores,
            "driver_memory": args.driver_memory,
            "shuffle_partitions": spark.conf.get("spark.sql.shuffle.partitions"),
            "version": spark.version,
        }
        new = aggregate_long_spark(spark, files)
    finally:
        spark.stop()

    check_keys(new, "새 집계")
    new["source"] = SOURCE
    new["collected_at"] = pd.Timestamp(now_kst()).tz_localize(None)
    new = new.reindex(columns=OUT_COLUMNS)
    meta: dict = {
        "run": run_id,
        "input_root": str(args.input_root),
        "full": bool(args.full),
        "years": None if args.full else args.years,
        "input_partitions": len(files),
        "new_rows": len(new),
        "missing_days": missing_days(new["date"]),
        "spark": spark_conf,
    }

    panel = new
    if args.base_panel:
        panel = union_with_base(new, load_base_panel(args.base_panel))
        meta["base_panel"] = str(args.base_panel)
    dup_new, dup_final = duplicate_keys(new), duplicate_keys(panel)
    meta["duplicate_keys"] = {"new": dup_new, "final": dup_final}
    meta["panel_rows"] = len(panel)
    if dup_new or dup_final:
        print(
            f"[crowd_panel_rebuild] 유일성 키 중복 new={dup_new} final={dup_final} - 저장 안 함",
            file=sys.stderr,
        )
        return EXIT_DUPLICATE_KEY

    exit_code = 0
    if args.verify_against:
        verify = verify_against(new, args.verify_against, args.tolerance)
        meta["verify"] = verify
        if not verify["passed"]:
            print(
                "[crowd_panel_rebuild] 검증 실패: " + json.dumps(verify, ensure_ascii=False),
                file=sys.stderr,
            )
            exit_code = EXIT_VERIFY_FAIL

    out_path = args.out_root / f"panel_{run_id}.parquet"
    _write_parquet(panel, out_path)
    meta["output"] = str(out_path)
    meta["elapsed_sec"] = round(time.perf_counter() - t0, 2)
    meta["peak_rss_mb"] = _peak_rss_mb()
    meta["generated_at"] = now_kst().isoformat(timespec="seconds")
    (args.out_root / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"[crowd_panel_rebuild] 완료 -- {out_path} ({len(panel):,}행)")
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
