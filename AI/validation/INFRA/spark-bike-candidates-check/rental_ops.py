"""후보 1 — 따릉이 대여이력 집계: (역, 5분 슬롯, 요일) 대여/반납 → 순증감(net_flow).

`165`의 OP-A(panel_join)와 같은 성격(집계 + 조인)이지만, 프록시 CROWD 데이터가 아니라
**실제 BIKE 대여이력 원본**(`data/BIKE/raw/rental_history/`)으로 잰다. 슬롯 계산은
`full-coverage-check`에서 발견된 버그(HHMM을 그냥 5로 나눔)를 피해 올바른 식
(`hh*12 + mm//5`)을 쓴다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from common import RENTAL_RAW_COLS

RENT_BASIS = "출발시간"
RETURN_BASIS = "도착시간"

UTF8_CACHE_DIR = Path(__file__).resolve().parent / "data_sample" / "rental_utf8_cache"


def ensure_utf8(files: list[Path]) -> tuple[list[Path], float]:
    """Spark 4.x CSV 리더가 cp949를 지원하지 않는다(허용 charset이 UTF-8류로 고정돼 있음,
    `multiLine`을 켜도 마찬가지 — 실측으로 확인). 원본이 안 바뀌는 정적 파일이라 UTF-8로
    한 번 변환해서 캐시한다. 이 변환은 **Spark 도입 시 실제로 드는 추가 비용**이라 시간을
    따로 재서 결과에 남긴다(대조 벤치 자체의 시간에는 안 넣는다)."""
    UTF8_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    import time as _time

    t0 = _time.perf_counter()
    converted: list[Path] = []
    for f in files:
        out = UTF8_CACHE_DIR / f"{f.parent.name}__{f.name}"
        if not out.exists():
            try:
                with open(f, encoding="cp949") as src:
                    text = src.read()
            except UnicodeDecodeError:
                # pandas 쪽과 동일 파일(2024-11-27, 헤더만 있는 빈 파일) — 데이터 행이
                # 없으므로 아예 빼서 pandas의 "빈 파일 skip"과 표본을 맞춘다.
                with open(f, encoding="utf-8") as src:
                    text = src.read()
                if len(text.strip().splitlines()) <= 1:
                    continue
            out.write_text(text, encoding="utf-8")
        converted.append(out)
    elapsed = _time.perf_counter() - t0
    return converted, elapsed


# ── pandas ──
def read_rental_pandas(files: list[Path]) -> pd.DataFrame:
    """일부 원본 파일이 줄 끝 trailing comma로 빈 열이 하나 더 잡힌다(전례:
    `full-coverage-check/build_full_station_netflow.py`) — 마지막 열이 전부 결측이면 버린다."""
    frames = []
    for f in files:
        try:
            df = pd.read_csv(f, encoding="cp949", header=0)
        except UnicodeDecodeError:
            # 실측: 2024-11-27치가 cp949가 아니라 UTF-8로 저장돼 있고 헤더만 있는 빈 파일이다
            # (원본 수집 결손으로 추정). 값을 채우지 않고 그 날만 건너뛴다(원칙 8).
            df = pd.read_csv(f, encoding="utf-8", header=0)
        if len(df) == 0:
            continue
        if df.shape[1] == len(RENTAL_RAW_COLS) + 1 and df.iloc[:, -1].isna().all():
            df = df.iloc[:, :-1]
        df.columns = RENTAL_RAW_COLS
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def op_pandas(df: pd.DataFrame) -> pd.DataFrame:
    hh = df["hhmm"] // 100
    mm = df["hhmm"] % 100
    slot_5m = (hh * 12 + mm // 5).astype("int16")
    dow = pd.to_datetime(df["date"], format="%Y%m%d").dt.dayofweek.astype("int8")
    df = df.assign(slot_5m=slot_5m, dow=dow)

    rent = (
        df[df["basis"] == RENT_BASIS]
        .groupby(["start_station_id", "slot_5m", "dow"], as_index=False)["count"]
        .sum()
        .rename(columns={"start_station_id": "station_id", "count": "rent_count"})
    )
    ret = (
        df[df["basis"] == RETURN_BASIS]
        .groupby(["end_station_id", "slot_5m", "dow"], as_index=False)["count"]
        .sum()
        .rename(columns={"end_station_id": "station_id", "count": "return_count"})
    )
    merged = rent.merge(ret, on=["station_id", "slot_5m", "dow"], how="outer")
    merged["rent_count"] = merged["rent_count"].fillna(0)
    merged["return_count"] = merged["return_count"].fillna(0)
    merged["net_flow"] = merged["rent_count"] - merged["return_count"]
    return merged.sort_values(["station_id", "dow", "slot_5m"]).reset_index(drop=True)


# ── spark ──
def read_rental_spark(spark, files: list[Path]):
    """pandas 쪽과 같은 이유로 trailing comma 열을 뺀다 — 파일마다 열 수가 섞이면 Spark CSV
    리더가 한 스키마로 못 합치므로 파일을 두 그룹(10열/11열)으로 나눠 읽는다."""
    utf8_files, _convert_sec = ensure_utf8(files)

    groups: dict[int, list[str]] = {}
    for f in utf8_files:
        with open(f, encoding="utf-8") as fh:
            ncols = len(fh.readline().rstrip("\n").split(","))
        groups.setdefault(ncols, []).append(str(f))

    frames = []
    for ncols, paths in groups.items():
        sdf = spark.read.option("header", "true").option("encoding", "UTF-8").csv(paths)
        if ncols == len(RENTAL_RAW_COLS) + 1:
            sdf = sdf.drop(sdf.columns[-1])
        frames.append(sdf.toDF(*RENTAL_RAW_COLS))

    out = frames[0]
    for f in frames[1:]:
        out = out.unionByName(f)
    return out, _convert_sec


def op_spark(sdf):
    from pyspark.sql import functions as F

    hh = (F.col("hhmm") / 100).cast("int")
    mm = (F.col("hhmm") % 100).cast("int")
    sdf = sdf.withColumn("count", F.col("count").cast("long"))
    sdf = sdf.withColumn("slot_5m", (hh * 12 + (mm / 5).cast("int")).cast("int"))
    # Spark dayofweek: 일=1..토=7. pandas dt.dayofweek: 월=0..일=6로 통일한다((spark+5)%7).
    spark_dow = F.dayofweek(F.to_date(F.col("date"), "yyyyMMdd"))
    sdf = sdf.withColumn("dow", ((spark_dow + 5) % 7).cast("int"))

    rent = (
        sdf.filter(F.col("basis") == RENT_BASIS)
        .groupBy(F.col("start_station_id").alias("station_id"), "slot_5m", "dow")
        .agg(F.sum("count").alias("rent_count"))
    )
    ret = (
        sdf.filter(F.col("basis") == RETURN_BASIS)
        .groupBy(F.col("end_station_id").alias("station_id"), "slot_5m", "dow")
        .agg(F.sum("count").alias("return_count"))
    )
    merged = rent.join(ret, on=["station_id", "slot_5m", "dow"], how="outer")
    merged = merged.fillna(0, subset=["rent_count", "return_count"])
    merged = merged.withColumn("net_flow", F.col("rent_count") - F.col("return_count"))
    return merged.orderBy("station_id", "dow", "slot_5m")
