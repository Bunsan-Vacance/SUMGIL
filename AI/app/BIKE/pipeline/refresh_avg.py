"""Refresh the BIKE avg profile from completed daily bikeList snapshots."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from app.BIKE.pipeline.calendar import dow_type_for_date, load_holidays

AI_ROOT = Path(__file__).resolve().parents[3]
KST = ZoneInfo("Asia/Seoul")
RAW_ROOT = AI_ROOT / "data/BIKE/raw/realtime"
DAILY_ROOT = AI_ROOT / "data/BIKE/processed/avg_daily"
OUTPUT_DIR = AI_ROOT / "models/BIKE/avg-refreshed"
KEYS = ["od_station_id", "dow_type", "time_slot"]
VALUES = ["exp_bikes", "p_empty", "p_full"]
SUMS = ["stock_sum", "empty_sum", "full_sum"]
RAW_COLUMNS = ["stationId", "parkingBikeTotCnt", "rackTotCnt", "collected_at"]
MIN_SAMPLES_PER_SLOT = 6


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        frame.to_parquet(temporary, index=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _daily_path(root: Path, day: date) -> Path:
    return root / f"dt={day.isoformat()}" / "part.parquet"


def aggregate_day(raw_root: Path, day: date, holidays: pd.DataFrame) -> pd.DataFrame:
    paths = sorted((raw_root / f"dt={day.isoformat()}").glob("hh=*/snapshot_*.parquet"))
    if not paths:
        raise FileNotFoundError(f"따릉이 원천 스냅샷 없음: {day}")

    frame = pd.concat(
        (pd.read_parquet(path, columns=RAW_COLUMNS) for path in paths), ignore_index=True
    )
    timestamps = pd.to_datetime(frame["collected_at"], errors="coerce")
    if timestamps.dt.tz is None:
        timestamps = timestamps.dt.tz_localize(KST)
    else:
        timestamps = timestamps.dt.tz_convert(KST)
    frame["collected_at"] = timestamps
    frame = frame.loc[frame["collected_at"].dt.date == day].copy()
    frame["stock"] = pd.to_numeric(frame["parkingBikeTotCnt"], errors="coerce")
    frame["racks"] = pd.to_numeric(frame["rackTotCnt"], errors="coerce")
    frame = frame.dropna(subset=["stationId", "collected_at", "stock", "racks"])
    frame = frame.loc[(frame["stock"] >= 0) & (frame["racks"] > 0)].copy()
    if frame.empty:
        raise ValueError(f"유효한 따릉이 재고 표본 없음: {day}")

    frame["slot_5m"] = frame["collected_at"].dt.hour * 12 + frame["collected_at"].dt.minute // 5
    frame = frame.sort_values("collected_at").drop_duplicates(["stationId", "slot_5m"], keep="last")
    frame["time_slot"] = frame["slot_5m"] // 6
    frame["dow_type"] = dow_type_for_date(day, holidays)
    frame["empty"] = (frame["stock"] == 0).astype("int8")
    frame["full"] = (frame["stock"] >= frame["racks"]).astype("int8")
    frame = frame.rename(columns={"stationId": "od_station_id"})
    result = frame.groupby(KEYS, as_index=False).agg(
        stock_sum=("stock", "sum"),
        empty_sum=("empty", "sum"),
        full_sum=("full", "sum"),
        sample_count=("stock", "size"),
    )
    if result.empty:
        raise ValueError(f"따릉이 일별 집계가 비어 있음: {day}")
    return result


def blend_profile(
    baseline: pd.DataFrame, daily: list[pd.DataFrame], prior_weight: int
) -> pd.DataFrame:
    """Use the historical average as a 48-sample prior for observed recent slots."""
    if prior_weight <= 0:
        raise ValueError("prior_weight는 양수여야 합니다")
    recent = (
        pd.concat(daily, ignore_index=True)
        .groupby(KEYS, as_index=False)[[*SUMS, "sample_count"]]
        .sum()
    )
    baseline = baseline[[*KEYS, *VALUES]].copy()
    combined = baseline.merge(recent, on=KEYS, how="outer", validate="one_to_one")
    n = combined["sample_count"].fillna(0)
    has_prior = combined["exp_bikes"].notna()
    eligible = n >= MIN_SAMPLES_PER_SLOT
    for value, total in zip(VALUES, SUMS):
        blended = (combined[value] * prior_weight + combined[total]) / (prior_weight + n)
        observed = combined[total] / n.replace(0, float("nan"))
        combined[value] = combined[value].where(~eligible, blended.where(has_prior, observed))
    result = combined[[*KEYS, *VALUES]].dropna(subset=VALUES)
    if result.empty or result[KEYS].duplicated().any():
        raise ValueError("avg 통계가 비어 있거나 키가 중복됐습니다")
    if not result["p_empty"].between(0, 1).all() or not result["p_full"].between(0, 1).all():
        raise ValueError("avg 확률 범위가 0~1을 벗어났습니다")
    return result.sort_values(KEYS).reset_index(drop=True)


def run(
    baseline_path: Path,
    raw_root: Path = RAW_ROOT,
    daily_root: Path = DAILY_ROOT,
    output_dir: Path = OUTPUT_DIR,
    as_of: date | None = None,
    window_days: int = 28,
    prior_weight: int = 48,
) -> Path:
    if window_days <= 0:
        raise ValueError("window_days는 양수여야 합니다")
    as_of = as_of or datetime.now(KST).date() - timedelta(days=1)
    if as_of >= datetime.now(KST).date():
        raise ValueError("완료된 날짜(어제 이전)만 avg 갱신에 사용할 수 있습니다")
    baseline_path = Path(baseline_path)
    output_dir = Path(output_dir)
    if baseline_path.resolve() == (output_dir / "stock_profile_avg.parquet").resolve():
        raise ValueError("기준 avg와 갱신 출력은 다른 경로여야 합니다")

    holidays = load_holidays()
    daily: list[pd.DataFrame] = []
    used_days: list[str] = []
    for offset in range(window_days - 1, -1, -1):
        day = as_of - timedelta(days=offset)
        path = _daily_path(daily_root, day)
        if not path.exists() and (raw_root / f"dt={day.isoformat()}").exists():
            _atomic_parquet(aggregate_day(raw_root, day, holidays), path)
        if path.exists():
            daily.append(pd.read_parquet(path))
            used_days.append(day.isoformat())
    if as_of.isoformat() not in used_days:
        raise FileNotFoundError(f"전날({as_of}) 따릉이 원천/일별 집계 없음; 기존 서빙 파일 유지")

    baseline = pd.read_parquet(baseline_path)
    profile = blend_profile(baseline, daily, prior_weight)
    output_path = output_dir / "stock_profile_avg.parquet"
    _atomic_parquet(profile, output_path)
    meta = {
        "source": "avg",
        "baseline": str(baseline_path),
        "as_of": as_of.isoformat(),
        "source_days": used_days,
        "window_days": window_days,
        "prior_weight": prior_weight,
        "min_samples_per_slot": MIN_SAMPLES_PER_SLOT,
        "rows": len(profile),
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
    }
    meta_path = output_dir / "meta.json"
    temporary = meta_path.with_name(f".{meta_path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, meta_path)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"[BIKE avg refresh] {output_path} ({len(profile):,}행, through {as_of})", flush=True)
    return output_path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline", type=Path, required=True, help="검증된 기준 stock_profile_avg.parquet"
    )
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--daily-root", type=Path, default=DAILY_ROOT)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument(
        "--as-of", type=date.fromisoformat, default=None, help="YYYY-MM-DD, 기본: 어제(KST)"
    )
    parser.add_argument("--window-days", type=int, default=28)
    parser.add_argument("--prior-weight", type=int, default=48)
    args = parser.parse_args(argv)
    run(
        args.baseline,
        args.raw_root,
        args.daily_root,
        args.output_dir,
        args.as_of,
        args.window_days,
        args.prior_weight,
    )


if __name__ == "__main__":
    main()
