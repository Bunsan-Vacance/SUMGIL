"""CROWD 운영 데이터 품질 잡 (S15P21A104-341, D1·D2) — raw 승하차를 2024-2025 기준 분포와 견줘 일별로 판정한다.

두 모드가 있다.

1. `--rebuild-baseline` (D1): 2024-2025 와이드 패널(`--base-panel`) -> 기준 분포 표.
   - `<baseline-dir>/dq_baseline.parquet` (롱): day_type, line, station_no, station_name,
     time_slot, direction, mean, std(표본, ddof=1), zero_ratio, n(결측 아닌 일수)
   - `<baseline-dir>/dq_baseline_meta.json`: version(`<패널 파일명>@<패널 행수>`),
     day_types, line_totals{day_type:{line:{mean,std}}}, slot_share{day_type:{slot:ratio}},
     expected_stations[]
   패널에 `day_type`이 없으면 `app.CROWD.pipeline.calendar.attach_calendar`로 날짜에서 붙인다
   (요일유형 평일·토요일·일요일 + 평일 공휴일은 "휴일". 공휴일 표가 없으면 요일로만 나뉜다).
2. 기본 모드 (D2): `--input-root`의 raw 파티션(`--years` 기본 2026, `--full`이면 전부)을
   `crowd_panel_rebuild.aggregate_long_spark`로 롱으로 만들고 날짜마다 DQ1~DQ7을 계산해
   `<out-root>/dt=<D>/part.json`을 쓴다. 끝에 `<out-root>/run_meta.json`.

지표 정의 (요약, 임계는 `DQ_THRESHOLDS` 한 곳)
- DQ1 행 수·역 수: 당일 롱 행 수, 유일 station_no 수. `missing_stations` = 기대 역 집합 - 당일 역 집합.
- DQ2 결손·0 비율: `nan_ratio` = passengers 결측 비율, `zero_ratio` = 결측 아닌 값 중 0 비율.
  기준은 같은 요일유형 기준 표의 n 가중 평균 0 비율(`zero_ratio_baseline`).
- DQ3 호선 총량 z: 호선별 일 승차 총량(boarding 합) vs 요일유형별 일 총량 평균·표준편차.
  `--level-adjust`면 입력 기간 전체에서 호선별 (총량/기준 평균)의 중앙값을 비율 r로 잡고
  기준 평균·표준편차에 r을 곱한 값으로 `z_adjusted`를 함께 기록하고, 경보 판정도 z_adjusted로 한다.
- DQ4 역x슬롯x방향 z: z = (값 - 기준 평균) / 기준 표준편차. 표준편차가 0이거나 n < 5인 셀은 제외.
  |z| > outlier_z 인 셀이 이상치이고 `outliers_top`은 |z| 내림차순 상위 `--top-n`.
- DQ5 슬롯 분포 JS 거리: 당일 승차 슬롯 비율 벡터 vs 기준 비율 벡터의 Jensen-Shannon **거리**
  (밑 2 로그의 JS 발산의 제곱근, 0~1). 양쪽 모두 슬롯 합집합 위에서 합 1로 정규화한다.
- DQ6 스키마: 파티션 파일의 컬럼 집합이 collector `RAW_COLUMNS`와 다르거나, `RAW_NEEDED` 컬럼의
  타입이 문자열·정수가 아니면(`_read_raw`가 허용하는 범위 밖) schema_ok=False와 차이 목록.
- DQ7 수집 지연: 파티션 파일 mtime 날짜 - date (일). 파티션이 없으면 null.
`alerts`는 걸린 지표 ID 목록이다(`alert_levels`에 warn/crit 수준).

실행:
    cd AI
    python -m DATA_ENGINE.spark.jobs.crowd_data_quality --rebuild-baseline
    python -m DATA_ENGINE.spark.jobs.crowd_data_quality --years 2026 --level-adjust

기준 표가 없으면 exit 2(먼저 `--rebuild-baseline`). 집계는 전부 Spark이고 드라이버로는 집계 결과만 수집한다.
textfile 지표 연결은 이 잡의 범위 밖이다(셸 래퍼가 `run_meta.json`을 읽는다).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# 이 import가 PYSPARK_PYTHON 설정과 sys.path(AI 루트) 등록을 먼저 해 준다.
from DATA_ENGINE.spark.jobs.crowd_panel_rebuild import (
    AI_ROOT,
    RAW_NEEDED,
    _peak_rss_mb,
    aggregate_long_spark,
    load_base_panel,
    partition_files,
)

from app.CROWD.pipeline.calendar import attach_calendar  # noqa: E402
from DATA_ENGINE.collect.common import now_kst  # noqa: E402
from DATA_ENGINE.collect.subway_ridership_daily import RAW_COLUMNS  # noqa: E402
from DATA_ENGINE.spark.session import build_spark_session  # noqa: E402

DEFAULT_PANEL = AI_ROOT / "data" / "CROWD" / "processed" / "crowd_panel_2024_2025.parquet"
DEFAULT_INPUT_ROOT = AI_ROOT / "data" / "CROWD" / "raw" / "ridership_daily"
DEFAULT_OUT_ROOT = AI_ROOT / "data" / "CROWD" / "monitoring" / "data_quality"
DEFAULT_BASELINE_DIR = DEFAULT_OUT_ROOT / "baseline"
BASELINE_FILE = "dq_baseline.parquet"
BASELINE_META = "dq_baseline_meta.json"
JOB_NAME = "crowd_data_quality"
EXIT_NO_BASELINE = 2
MIN_N = 5  # 기준 셀의 최소 표본 일수(미만이면 z 제외)
BASELINE_COLUMNS = [
    "day_type",
    "line",
    "station_no",
    "station_name",
    "time_slot",
    "direction",
    "mean",
    "std",
    "zero_ratio",
    "n",
]

# 2026-10-02 실데이터 17일(raw 09-15~10-01, 185,386행, 하루 약 10,900행) 결과로 DQ2·DQ4 조정.
# - DQ4: "이상치 1개라도 있으면 경보"는 정상일에도 83~321개(행의 0.8~3%)가 나와 17일 전부 상시 경보였다.
#   추석 연휴(공휴일 표 없이 평일 기준 비교)는 6,625~8,054개(60~74%), 연휴 전날 09-23은 1,557개(14%),
#   09-18은 532개(4.9%). 그래서 건수 대신 비율(outlier_count/rows)로 판정한다 -- 5%(warn)·20%(crit).
#   `outlier_z`는 이상치 목록·건수를 만드는 기준으로만 남는다.
# - DQ2: 평일 기준 0비율이 0.000이라 0이 하나만 있어도 경보 -> 17일 중 13일 경보(실제 zero_ratio 0.000~0.018).
#   그래서 `zero_ratio_floor`(0.01) 미만의 0비율은 기준 배수와 무관하게 경보하지 않는다. NaN은 수집 결함이라 유지.
# 다음 최적화는 CLI --outlier-ratio-warn/--outlier-ratio-crit/--zero-ratio-floor로 재실행해 비교한다.
DQ_THRESHOLDS = {
    "missing_stations_warn": 1,
    "missing_stations_crit": 10,
    "zero_ratio_factor": 2.0,
    "zero_ratio_floor": 0.01,
    "outlier_ratio_warn": 0.05,
    "outlier_ratio_crit": 0.20,
    "line_z_warn": 2.0,
    "line_z_crit": 3.0,
    "outlier_z": 3.0,
    "slot_js": 0.05,
    "collect_lag_days": 2,
}

_OK_TYPE_PREFIXES = ("string", "large_string", "int")  # `_read_raw`가 문자열로 캐스팅해 받는 범위


# ---------------------------------------------------------------- 공통 유틸


def _clean(obj):
    """json 직렬화용: NaN·inf -> None, numpy 스칼라 -> 파이썬 값."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def _atomic_write_json(path: Path, payload: dict) -> None:
    """tmp에 쓴 뒤 replace(원자적). 상위 디렉터리는 만든다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(
            json.dumps(_clean(payload), ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def day_type_map(dates: list[str]) -> dict[str, str]:
    """ISO 날짜 목록 -> 요일유형. `attach_calendar` 규칙(공휴일 표는 기본 경로, 없으면 요일만)."""
    uniq = sorted(set(dates))
    if not uniq:
        return {}
    frame = attach_calendar(pd.DataFrame({"date": pd.to_datetime(uniq)}))
    return {
        d.strftime("%Y-%m-%d"): t for d, t in zip(frame["date"], frame["day_type"], strict=True)
    }


def _with_ds(df):
    """`date`(timestamp_ntz)에서 ISO 문자열 키 `ds`를 만든다."""
    from pyspark.sql import functions as F

    return df.withColumn("ds", F.date_format(F.col("date"), "yyyy-MM-dd"))


def _day_type_df(spark, mapping: dict[str, str], col: str = "day_type"):
    return spark.createDataFrame(list(mapping.items()), f"ds string, {col} string")


def js_distance(p: dict[str, float], q: dict[str, float]) -> float | None:
    """슬롯 비율 두 벡터의 Jensen-Shannon 거리(밑 2, 0~1). 합이 0인 쪽이 있으면 None."""
    keys = sorted(set(p) | set(q))
    a = np.array([max(p.get(k, 0.0), 0.0) for k in keys], dtype="float64")
    b = np.array([max(q.get(k, 0.0), 0.0) for k in keys], dtype="float64")
    if a.sum() <= 0 or b.sum() <= 0:
        return None
    a, b = a / a.sum(), b / b.sum()
    m = (a + b) / 2

    def _kl(x, y):
        mask = x > 0
        return float(np.sum(x[mask] * np.log2(x[mask] / y[mask])))

    div = (_kl(a, m) + _kl(b, m)) / 2
    return math.sqrt(max(div, 0.0))


def schema_diff(path: Path) -> list[str]:
    """raw 파티션 파일 하나의 스키마가 기준과 어긋난 점의 목록(빈 목록이면 정상)."""
    import pyarrow.parquet as pq

    try:
        schema = pq.read_schema(path)
    except Exception as exc:  # 손상 파일
        return [f"unreadable:{type(exc).__name__}"]
    names = set(schema.names)
    diffs = [f"missing:{c}" for c in RAW_COLUMNS if c not in names]
    diffs += [f"extra:{c}" for c in schema.names if c not in RAW_COLUMNS]
    for c in RAW_NEEDED:
        if c in names and not str(schema.field(c).type).startswith(_OK_TYPE_PREFIXES):
            diffs.append(f"type:{c}={schema.field(c).type}")
    return diffs


# ---------------------------------------------------------------- D1: 기준 분포


def build_baseline(spark, base_panel: Path, baseline_dir: Path) -> dict:
    """와이드(또는 롱) 패널 -> 기준 표 parquet + meta json. 쓴 meta를 돌려준다."""
    from pyspark.sql import functions as F

    raw_panel = spark.read.parquet(str(base_panel))
    panel_rows = raw_panel.count()

    long_df = _with_ds(load_base_panel(spark, base_panel))
    if "day_type" in raw_panel.columns:  # 패널이 이미 가진 요일유형을 우선한다
        dm = _with_ds(raw_panel).select("ds", "day_type").dropDuplicates(["ds"])
    else:
        dates = [r["ds"] for r in long_df.select("ds").distinct().collect()]
        dm = _day_type_df(spark, day_type_map(dates))
    long_df = long_df.join(F.broadcast(dm), "ds").persist()

    zero_flag = F.when(F.col("passengers").isNotNull(), (F.col("passengers") == 0).cast("double"))
    cell = (
        long_df.groupBy("day_type", "line", "station_no", "time_slot", "direction")
        .agg(
            F.max("station_name").alias("station_name"),
            F.avg("passengers").alias("mean"),
            F.stddev_samp("passengers").alias("std"),
            F.avg(zero_flag).alias("zero_ratio"),
            F.count("passengers").alias("n"),
        )
        .select(*BASELINE_COLUMNS)
    )
    base_pd = cell.toPandas()  # 집계 결과(요일유형 x 역 x 슬롯 x 방향)만 수집
    base_pd["station_no"] = base_pd["station_no"].astype("int64")
    base_pd["n"] = base_pd["n"].astype("int64")
    base_pd = base_pd.sort_values(
        ["day_type", "line", "station_no", "time_slot", "direction"], ignore_index=True
    )

    boarding = long_df.filter(F.col("direction") == "boarding")
    daily = boarding.groupBy("ds", "day_type", "line").agg(F.sum("passengers").alias("total"))
    line_pd = (
        daily.groupBy("day_type", "line")
        .agg(F.avg("total").alias("mean"), F.stddev_samp("total").alias("std"))
        .toPandas()
    )
    share_pd = (
        boarding.groupBy("day_type", "time_slot").agg(F.sum("passengers").alias("s")).toPandas()
    )
    stations = sorted(
        int(r["station_no"]) for r in long_df.select("station_no").distinct().collect()
    )
    long_df.unpersist()

    line_totals: dict[str, dict] = {}
    for r in line_pd.itertuples(index=False):
        line_totals.setdefault(r.day_type, {})[r.line] = {"mean": r.mean, "std": r.std}
    slot_share: dict[str, dict] = {}
    for day_type, g in share_pd.groupby("day_type"):
        total = float(g["s"].sum())
        slot_share[day_type] = {
            r.time_slot: (r.s / total if total else 0.0) for r in g.itertuples()
        }

    baseline_dir.mkdir(parents=True, exist_ok=True)
    pq_path = baseline_dir / BASELINE_FILE
    tmp = pq_path.with_name(f".{pq_path.name}.tmp")
    try:
        base_pd.to_parquet(tmp, index=False)
        tmp.replace(pq_path)
    finally:
        tmp.unlink(missing_ok=True)
    meta = {
        "version": f"{base_panel.stem}@{panel_rows}",
        "base_panel": str(base_panel),
        "panel_rows": panel_rows,
        "baseline_rows": int(len(base_pd)),
        "day_types": sorted(line_totals),
        "line_totals": line_totals,
        "slot_share": slot_share,
        "expected_stations": stations,
        "generated_at": now_kst().isoformat(timespec="seconds"),
    }
    _atomic_write_json(baseline_dir / BASELINE_META, meta)
    return meta


# ---------------------------------------------------------------- D2: 일별 판정


def _fallback_day_type(day_type: str, available: set[str]) -> str | None:
    """기준 표에 없는 요일유형(예: 공휴일 표 없이 만든 기준에 "휴일")의 대체: 휴일 -> 일요일 -> 평일."""
    for cand in (day_type, "일요일" if day_type == "휴일" else None, "평일"):
        if cand and cand in available:
            return cand
    return None


def judge_dates(
    spark,
    files: list[Path],
    baseline_dir: Path,
    meta: dict,
    *,
    top_n: int,
    level_adjust: bool,
    mark_synthetic: bool,
    thresholds: dict | None = None,
) -> tuple[dict[str, dict], int]:
    """파티션 파일들을 날짜별로 판정한다. `({ISO 날짜: part.json 내용}, 입력 롱 행 수)`."""
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    thr = {**DQ_THRESHOLDS, **(thresholds or {})}
    long_df = _with_ds(aggregate_long_spark(spark, files)).persist()

    # 파티션 단위 정보(스키마·mtime). 파티션 이름 dt=<ISO>가 날짜 키다.
    part_info: dict[str, dict] = {}
    for f in files:
        ds = f.parent.name.removeprefix("dt=")
        part_info[ds] = {
            "diff": schema_diff(f),
            "mtime": datetime.fromtimestamp(f.stat().st_mtime).date(),
        }

    per_date_rows = long_df.groupBy("ds").agg(
        F.count(F.lit(1)).alias("rows"),
        F.sum(F.col("passengers").isNull().cast("int")).alias("nulls"),
        F.count("passengers").alias("valid"),
        F.sum((F.col("passengers") == 0).cast("int")).alias("zeros"),
    )
    stat = {r["ds"]: r for r in per_date_rows.collect()}
    rows_in = int(sum(r["rows"] for r in stat.values()))
    all_dates = sorted(set(stat) | set(part_info))

    date_dt = day_type_map(all_dates)
    available = set(meta["day_types"])
    baseline_dt = {d: _fallback_day_type(t, available) for d, t in date_dt.items()}
    if any(v is None for v in baseline_dt.values()):
        raise RuntimeError(
            "기준 표에 쓸 수 있는 요일유형이 없다 - --rebuild-baseline을 다시 실행한다"
        )

    dm = _day_type_df(spark, {d: baseline_dt[d] for d in stat}, "bdt")
    long_df = long_df.join(F.broadcast(dm), "ds").persist()

    stations_by_date: dict[str, set[int]] = {}
    for r in long_df.select("ds", "station_no").distinct().collect():
        stations_by_date.setdefault(r["ds"], set()).add(int(r["station_no"]))

    boarding = long_df.filter(F.col("direction") == "boarding")
    line_total = {
        (r["ds"], r["line"]): float(r["t"] or 0.0)
        for r in boarding.groupBy("ds", "line").agg(F.sum("passengers").alias("t")).collect()
    }
    slot_vec: dict[str, dict[str, float]] = {}
    for r in boarding.groupBy("ds", "time_slot").agg(F.sum("passengers").alias("s")).collect():
        slot_vec.setdefault(r["ds"], {})[r["time_slot"]] = float(r["s"] or 0.0)

    # 기준 표 조인 -> 역x슬롯x방향 z
    base = spark.read.parquet(str(baseline_dir / BASELINE_FILE))
    zero_base = {
        r["day_type"]: (r["zr"] if r["zr"] is not None else 0.0)
        for r in base.groupBy("day_type")
        .agg((F.sum(F.col("zero_ratio") * F.col("n")) / F.sum("n")).alias("zr"))
        .collect()
    }
    usable = base.filter((F.col("n") >= MIN_N) & (F.col("std") > 0)).select(
        F.col("day_type").alias("bdt"),
        "line",
        "station_no",
        "time_slot",
        "direction",
        F.col("mean").alias("b_mean"),
        F.col("std").alias("b_std"),
    )
    z = (
        long_df.filter(F.col("passengers").isNotNull())
        .join(F.broadcast(usable), ["bdt", "line", "station_no", "time_slot", "direction"])
        .withColumn("z", (F.col("passengers") - F.col("b_mean")) / F.col("b_std"))
        .filter(F.abs(F.col("z")) > F.lit(float(thr["outlier_z"])))
    )
    out_count = {
        r["ds"]: int(r["c"]) for r in z.groupBy("ds").agg(F.count(F.lit(1)).alias("c")).collect()
    }
    rank = Window.partitionBy("ds").orderBy(
        F.abs(F.col("z")).desc(), "station_no", "time_slot", "direction"
    )
    top_rows: dict[str, list[dict]] = {}
    top = z.withColumn("rn", F.row_number().over(rank)).filter(F.col("rn") <= top_n)
    for r in top.orderBy("ds", "rn").collect():
        top_rows.setdefault(r["ds"], []).append(
            {
                "station_no": int(r["station_no"]),
                "station_name": r["station_name"],
                "line": r["line"],
                "time_slot": r["time_slot"],
                "direction": r["direction"],
                "value": float(r["passengers"]),
                "baseline_mean": float(r["b_mean"]),
                "baseline_std": float(r["b_std"]),
                "z": float(r["z"]),
            }
        )
    long_df.unpersist()

    # 호선 레벨 보정 비율(입력 기간 전체의 호선별 중앙값)
    ratios: dict[str, float] = {}
    if level_adjust:
        per_line: dict[str, list[float]] = {}
        for (ds, line), total in line_total.items():
            m = meta["line_totals"][baseline_dt[ds]].get(line, {}).get("mean")
            if m:
                per_line.setdefault(line, []).append(total / m)
        ratios = {line: float(np.median(v)) for line, v in per_line.items()}

    expected = set(meta["expected_stations"])
    now_iso = now_kst().isoformat(timespec="seconds")
    results: dict[str, dict] = {}
    for ds in all_dates:
        st = stat.get(ds)
        bdt = baseline_dt[ds]
        rows = int(st["rows"]) if st else 0
        valid = int(st["valid"]) if st else 0
        today = stations_by_date.get(ds, set())
        missing = sorted(expected - today)
        zero_ratio = (int(st["zeros"] or 0) / valid) if valid else None
        nan_ratio = (int(st["nulls"] or 0) / rows) if rows else None

        lines = []
        for line in sorted({ln for (d, ln) in line_total if d == ds}):
            ref = meta["line_totals"][bdt].get(line)
            total = line_total[(ds, line)]
            mean = ref["mean"] if ref else None
            std = ref["std"] if ref else None
            row = {
                "line": line,
                "total": total,
                "baseline_mean": mean,
                "baseline_std": std,
                "z": (total - mean) / std if mean is not None and std else None,
            }
            if level_adjust:
                r = ratios.get(line)
                row["level_ratio"] = r
                row["z_adjusted"] = (
                    (total - mean * r) / (std * r) if mean is not None and std and r else None
                )
            lines.append(row)

        js = js_distance(slot_vec.get(ds, {}), meta["slot_share"][bdt]) if rows else None
        info = part_info.get(ds)
        diff = info["diff"] if info else []
        lag = (info["mtime"] - datetime.strptime(ds, "%Y-%m-%d").date()).days if info else None

        z_key = "z_adjusted" if level_adjust else "z"
        line_zs = [abs(r[z_key]) for r in lines if r.get(z_key) is not None]
        max_line_z = max(line_zs) if line_zs else None

        levels: dict[str, str] = {}
        if len(missing) >= thr["missing_stations_warn"]:
            levels["DQ1"] = "crit" if len(missing) >= thr["missing_stations_crit"] else "warn"
        zb = zero_base.get(bdt)
        if (nan_ratio or 0) > 0 or (
            zero_ratio is not None
            and zb is not None
            and zero_ratio >= max(thr["zero_ratio_factor"] * zb, thr["zero_ratio_floor"])
        ):
            levels["DQ2"] = "warn"
        if max_line_z is not None and max_line_z >= thr["line_z_warn"]:
            levels["DQ3"] = "crit" if max_line_z >= thr["line_z_crit"] else "warn"
        outlier_ratio = (out_count.get(ds, 0) / rows) if rows else None
        if outlier_ratio is not None and outlier_ratio >= thr["outlier_ratio_warn"]:
            levels["DQ4"] = "crit" if outlier_ratio >= thr["outlier_ratio_crit"] else "warn"
        if js is not None and js > thr["slot_js"]:
            levels["DQ5"] = "warn"
        if diff:
            levels["DQ6"] = "crit"
        if lag is not None and lag > thr["collect_lag_days"]:
            levels["DQ7"] = "warn"

        results[ds] = {
            "date": ds,
            "baseline_version": meta["version"],
            "day_type": date_dt[ds],
            "baseline_day_type": bdt,
            "rows": rows,
            "stations": len(today),
            "expected_stations": len(expected),
            "missing_stations": missing,
            "nan_ratio": nan_ratio,
            "zero_ratio": zero_ratio,
            "zero_ratio_baseline": zb,
            "line_totals": lines,
            "slot_js": js,
            "schema_ok": not diff,
            "schema_diff": diff,
            "collect_lag_days": lag,
            "outlier_count": out_count.get(ds, 0),
            "outlier_ratio": outlier_ratio,
            "outliers_top": top_rows.get(ds, []),
            "alerts": sorted(levels),
            "alert_levels": levels,
            "generated_at": now_iso,
            "synthetic": bool(mark_synthetic),
        }
    return results, rows_in


# ---------------------------------------------------------------- 실행


def _run_rebuild(args: argparse.Namespace) -> int:
    t0 = time.perf_counter()
    if not args.base_panel.exists():
        print(f"[{JOB_NAME}] 기준 패널 없음: {args.base_panel}", file=sys.stderr)
        return EXIT_NO_BASELINE
    spark = build_spark_session(
        "crowd-data-quality-baseline", cores=args.cores, driver_memory=args.driver_memory
    )
    try:
        meta = build_baseline(spark, args.base_panel, args.baseline_dir)
    finally:
        spark.stop()
    print(
        f"[{JOB_NAME}] 기준 표 완료 -- {args.baseline_dir / BASELINE_FILE} "
        f"({meta['baseline_rows']:,}행, version={meta['version']}, {time.perf_counter() - t0:.1f}s)"
    )
    return 0


def run(args: argparse.Namespace) -> int:
    if args.rebuild_baseline:
        return _run_rebuild(args)

    t0 = time.perf_counter()
    started = now_kst().isoformat(timespec="seconds")
    meta_path = args.baseline_dir / BASELINE_META
    if not (args.baseline_dir / BASELINE_FILE).exists() or not meta_path.exists():
        print(
            f"[{JOB_NAME}] 기준 표 없음: {args.baseline_dir} - 먼저 --rebuild-baseline을 실행한다",
            file=sys.stderr,
        )
        return EXIT_NO_BASELINE
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    files = partition_files(args.input_root, None if args.full else args.years)
    if not files:
        print(f"[{JOB_NAME}] 입력 파티션 없음: {args.input_root}", file=sys.stderr)
        return 1

    thresholds = {
        **DQ_THRESHOLDS,
        **{
            k: v
            for k, v in {
                "outlier_ratio_warn": args.outlier_ratio_warn,
                "outlier_ratio_crit": args.outlier_ratio_crit,
                "zero_ratio_floor": args.zero_ratio_floor,
            }.items()
            if v is not None
        },
    }
    spark = build_spark_session(
        "crowd-data-quality", cores=args.cores, driver_memory=args.driver_memory
    )
    try:
        results, rows_in = judge_dates(
            spark,
            files,
            args.baseline_dir,
            meta,
            top_n=args.top_n,
            level_adjust=args.level_adjust,
            mark_synthetic=args.mark_synthetic,
            thresholds=thresholds,
        )
    finally:
        spark.stop()

    for ds, payload in results.items():
        _atomic_write_json(args.out_root / f"dt={ds}" / "part.json", payload)
    run_meta = {
        "job": JOB_NAME,
        "run": args.run or now_kst().strftime("%Y%m%d-%H%M"),
        "started_at": started,
        "elapsed_sec": round(time.perf_counter() - t0, 2),
        "rows_in": rows_in,
        "dates": sorted(results),
        "baseline_version": meta["version"],
        "thresholds": thresholds,
        "spark": {"cores": args.cores, "driver_memory": args.driver_memory},
        "peak_rss_mb": _peak_rss_mb(),
        "rc": 0,
    }
    _atomic_write_json(args.out_root / "run_meta.json", run_meta)
    n_alert = sum(1 for p in results.values() if p["alerts"])
    print(f"[{JOB_NAME}] 완료 -- {len(results)}일 판정, 경보 {n_alert}일 ({args.out_root})")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    ap.add_argument("--base-panel", type=Path, default=DEFAULT_PANEL, help="2024-2025 패널 parquet")
    ap.add_argument("--baseline-dir", type=Path, default=DEFAULT_BASELINE_DIR)
    ap.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    ap.add_argument("--run", default=None, help="실행 ID(기본 KST YYYYMMDD-HHMM)")
    ap.add_argument("--rebuild-baseline", action="store_true", help="기준 표만 다시 만든다")
    ap.add_argument("--years", type=int, nargs="+", default=[2026], help="판정 대상 연도")
    ap.add_argument("--full", action="store_true", help="전 파티션(없으면 --years 연도만)")
    ap.add_argument("--top-n", type=int, default=50, help="날짜별 이상치 목록 길이")
    ap.add_argument(
        "--outlier-ratio-warn", type=float, default=None, help="DQ4 warn 비율(기본 DQ_THRESHOLDS)"
    )
    ap.add_argument(
        "--outlier-ratio-crit", type=float, default=None, help="DQ4 crit 비율(기본 DQ_THRESHOLDS)"
    )
    ap.add_argument(
        "--zero-ratio-floor", type=float, default=None, help="DQ2 0비율 하한(기본 DQ_THRESHOLDS)"
    )
    ap.add_argument("--level-adjust", action="store_true", help="호선 레벨 보정 z_adjusted 기록")
    ap.add_argument("--mark-synthetic", action="store_true", help="결과에 synthetic=true 표시")
    ap.add_argument("--cores", default="3")
    ap.add_argument("--driver-memory", default="3g")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
