"""BIKE 재고 raw 누적 재집계·품질 리포트 (274, 결정문서 1순위 후보) — 상시 운영 배치.

Kafka로 계속 쌓이는 재고 스냅샷(`data/BIKE/raw/realtime/dt=*/hh=*/snapshot_*.parquet`)을
**전체 누적분** 읽어서 역×요일×시간대별 평균·표준편차 재고를 다시 계산한다. 273에서 실측
확인: 지금 규모(10일치, 5,154개 파일)에서도 Spark가 pandas보다 3.3배 빠르다 — 행 수가
아니라 **작은 파일이 많은 I/O 패턴**이 이유다(파일이 계속 늘어나므로 격차는 더 벌어질
것으로 예상, 실측 재검증 필요).

`bike_avg_baseline.py`(274 B안, `train.py`가 재학습 때만 호출)와 달리 **이 잡은 서버에서
크론/타이머로 상시 자동 실행**하는 게 목적이다 — "Spark를 실제 파이프라인에 넣어 운영한
실적"이 사람이 가끔 켜는 스크립트뿐이면 약하다는 지적에 따라 만들었다.

**출력은 서빙에 연결하지 않는다.** `data/BIKE/processed/realtime_stock_profile/`에 품질
리포트/모니터링용으로만 쓴다 — avg 서빙 경로(`refresh_avg.py`)는 그대로 두고 건드리지 않는다.
나중에 이 출력을 실제로 쓰기로 하면(BE 309 요청 3번 "D-1/D-7 lag를 실시간 수집분에 잇기"의
재료가 될 수 있다) 별도 검토가 필요하다.

실행:
    cd AI
    python -m DATA_ENGINE.spark.jobs.bike_realtime_reprocess \
        --input-root data/BIKE/raw/realtime --out data/BIKE/processed/realtime_stock_profile

대조 검증(pandas와 값 일치 확인, 배포 전 1회 + 정기 점검용):
    python -m DATA_ENGINE.spark.jobs.bike_realtime_reprocess --verify
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

from DATA_ENGINE.batch.build_bike_stock_5min import (  # noqa: E402
    normalize_bike_stock,
    read_raw_snapshots,
)
from DATA_ENGINE.spark.metrics import compare_frames  # noqa: E402
from DATA_ENGINE.spark.schema_reader import read_bike_stock_raw  # noqa: E402
from DATA_ENGINE.spark.session import build_spark_session  # noqa: E402

DEFAULT_INPUT_ROOT = AI_ROOT / "data" / "BIKE" / "raw" / "realtime"
DEFAULT_OUTPUT_ROOT = AI_ROOT / "data" / "BIKE" / "processed" / "realtime_stock_profile"
KEY_COLS = ["station_id", "dow", "collected_hour"]
VALUE_COLS = ["avg_bike_count", "avg_stock_ratio"]


def snapshot_files(root: Path) -> list[Path]:
    return sorted(root.glob("dt=*/hh=*/snapshot_*.parquet"))


def fit_pandas(files: list[Path]) -> pd.DataFrame:
    """프로덕션 함수(`build_bike_stock_5min`)를 그대로 재사용한다 — 273과 동일."""
    raw = read_raw_snapshots(files)
    five_min = normalize_bike_stock(raw)
    agg = (
        five_min.groupby(["station_id", five_min["collected_at"].dt.dayofweek, "collected_hour"])
        .agg(
            avg_bike_count=("current_bike_count", "mean"),
            std_bike_count=("current_bike_count", "std"),
            avg_stock_ratio=("stock_ratio", "mean"),
            n_obs=("current_bike_count", "count"),
        )
        .reset_index()
        .rename(columns={"collected_at": "dow"})
    )
    return agg.sort_values(["station_id", "dow", "collected_hour"]).reset_index(drop=True)


def fit_spark(spark, files: list[Path]):
    """`DATA_ENGINE/spark/schema_reader.py`(혼합 스키마+entity_id 검증)를 재사용하고,
    dedup·집계만 여기서 한다 — 273에서 실측 검증된 로직 그대로."""
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    df = read_bike_stock_raw(spark, files)
    df = df.withColumn(
        "stock_ratio",
        F.when(
            F.col("rack_total_count") > 0, F.col("current_bike_count") / F.col("rack_total_count")
        ),
    )
    df = df.withColumn(
        "slot_5m", F.from_unixtime(F.floor(F.unix_timestamp(F.col("collected_at")) / 300) * 300)
    )

    # 같은 (station, slot_5m) 안에서 가장 최근 값만 남긴다(pandas drop_duplicates(keep="last")와 동일).
    window = Window.partitionBy("station_id", "slot_5m").orderBy(F.col("collected_at").desc())
    deduped = df.withColumn("rn", F.row_number().over(window)).where(F.col("rn") == 1).drop("rn")

    # Spark dayofweek: 일=1..토=7. pandas dt.dayofweek: 월=0..일=6로 통일한다((spark+5)%7).
    spark_dow = F.dayofweek(F.col("collected_at"))
    agg = deduped.groupBy(
        "station_id",
        ((spark_dow + 5) % 7).alias("dow"),
        F.hour(F.col("collected_at")).alias("collected_hour"),
    ).agg(
        F.mean("current_bike_count").alias("avg_bike_count"),
        F.stddev("current_bike_count").alias("std_bike_count"),
        F.mean("stock_ratio").alias("avg_stock_ratio"),
        F.count("current_bike_count").alias("n_obs"),
    )
    return agg.orderBy("station_id", "dow", "collected_hour")


def run(input_root: Path, out_dir: Path) -> dict:
    files = snapshot_files(input_root)
    if not files:
        raise FileNotFoundError(f"재고 raw 스냅샷 없음: {input_root}")
    print(f"[bike_realtime_reprocess] 입력 {len(files)}개 파일: {input_root}")

    spark = build_spark_session("bike-realtime-reprocess")
    try:
        t0 = time.perf_counter()
        result = fit_spark(spark, files).toPandas()
        wall = time.perf_counter() - t0
    finally:
        spark.stop()
    print(f"[bike_realtime_reprocess] spark {wall:.1f}초, {len(result):,}행")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "part.parquet"
    tmp_path = out_path.with_name(f".{out_path.name}.tmp")
    result.to_parquet(tmp_path, index=False)
    tmp_path.replace(out_path)

    meta = {
        "files": len(files),
        "rows": len(result),
        "spark_wall_sec": round(wall, 2),
        "generated_at": pd.Timestamp.now(tz="Asia/Seoul").isoformat(timespec="seconds"),
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[bike_realtime_reprocess] 완료 -- {out_path}")
    return meta


def verify(input_root: Path) -> dict:
    """pandas 대조 — 배포 전 1회 + 정기 점검용. 서빙에 안 쓰이므로 상시 실행에는 안 넣는다."""
    files = snapshot_files(input_root)
    if not files:
        raise FileNotFoundError(f"재고 raw 스냅샷 없음: {input_root}")

    t0 = time.perf_counter()
    pandas_result = fit_pandas(files)
    pandas_wall = time.perf_counter() - t0

    spark = build_spark_session("bike-realtime-reprocess-verify")
    try:
        t0 = time.perf_counter()
        spark_result = fit_spark(spark, files).toPandas()
        spark_wall = time.perf_counter() - t0
    finally:
        spark.stop()

    accuracy = compare_frames(pandas_result, spark_result, key_cols=KEY_COLS, value_cols=VALUE_COLS)
    result = {
        "files": len(files),
        "pandas_wall_sec": round(pandas_wall, 2),
        "spark_wall_sec": round(spark_wall, 2),
        "ratio_spark_over_pandas": round(spark_wall / pandas_wall, 3) if pandas_wall else None,
        **accuracy,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_ROOT)
    ap.add_argument("--verify", action="store_true", help="pandas 대조만 하고 결과는 안 씀")
    args = ap.parse_args(argv)

    if args.verify:
        verify(args.input_root)
    else:
        run(args.input_root, args.out)


if __name__ == "__main__":
    main()
