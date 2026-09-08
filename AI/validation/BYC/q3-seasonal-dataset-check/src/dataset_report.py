"""Phase 0 — target_net_flow 데이터셋 검증 리포트.

build_target_dataset.py가 만든 train/valid/test를 독립적으로 검증하고,
dataset_report.md 등 산출물을 outputs/에 남긴다.

실행 예:
    python dataset_report.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_target_dataset import HORIZONS, SPLIT_DEFS  # noqa: E402

COVERAGE_PASS_THRESHOLD = 0.95
ZERO_RATIO_WARN_THRESHOLD = 0.90
HORIZON_BALANCE_WARN_PCT = 0.05
EXCEPTION_FLAG_PERCENTILE = 0.95

EXPECTED_COLUMNS = [
    "station_id",
    "station_no",
    "base_time",
    "horizon_min",
    "known_stock_at_request",
    "known_stock_source",
    "minutes_since_stock_anchor",
    "capacity_proxy",
    "target_rent_count",
    "target_return_count",
    "target_net_flow",
    "hour",
    "minute",
    "day_of_week",
    "is_weekend",
    "month",
    "known_stock_ratio",
]

FEATURE_AVAILABILITY = [
    {
        "feature": "known_stock_at_request",
        "trainable": "가능(hourly anchor 대체)",
        "servable": "가능(실시간 API)",
        "used_in_baseline": "포함",
    },
    {
        "feature": "minutes_since_stock_anchor",
        "trainable": "가능",
        "servable": "가능",
        "used_in_baseline": "포함",
    },
    {
        "feature": "historical_profile_net (Phase 2)",
        "trainable": "가능",
        "servable": "가능",
        "used_in_baseline": "포함 예정",
    },
    {
        "feature": "recent_net_15m/30m/60m (A안)",
        "trainable": "가능",
        "servable": "불가",
        "used_in_baseline": "제외",
    },
    {
        "feature": "weather_current (Phase 4)",
        "trainable": "가능",
        "servable": "가능",
        "used_in_baseline": "포함 예정",
    },
    {
        "feature": "future_weather_observed",
        "trainable": "가능",
        "servable": "불가",
        "used_in_baseline": "제외",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="target_net_flow 데이터셋 Phase 0 검증 리포트를 만든다.")
    script_dir = Path(__file__).resolve()
    ai_dir = script_dir.parents[4]
    default_dataset_dir = ai_dir / "data" / "processed" / "BYC" / "stock_q3_seasonal_net_flow"
    default_master_dir = ai_dir / "data" / "processed" / "BYC" / "stock_q3_seasonal"
    default_output_dir = script_dir.parents[1] / "outputs"
    parser.add_argument("--dataset-dir", default=str(default_dataset_dir))
    parser.add_argument("--master-dir", default=str(default_master_dir))
    parser.add_argument("--output-dir", default=str(default_output_dir))
    return parser.parse_args()


def load_splits(dataset_dir: Path) -> dict[str, pd.DataFrame]:
    splits = {}
    for split_name, _year, _start, _end in SPLIT_DEFS:
        path = dataset_dir / f"{split_name}_q3_target_net_flow.csv.gz"
        df = pd.read_csv(path)
        df["base_time"] = pd.to_datetime(df["base_time"])
        df["station_id"] = df["station_id"].astype(str)
        splits[split_name] = df
    return splits


def check_schema(splits: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for name, df in splits.items():
        missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
        extra = [c for c in df.columns if c not in EXPECTED_COLUMNS]
        rows.append(
            {
                "split": name,
                "missing_columns": ",".join(missing),
                "extra_columns": ",".join(extra),
                "ok": len(missing) == 0,
            }
        )
    return pd.DataFrame(rows)


def check_split_boundaries(splits: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    ranges = {}
    for split_name, _year, start, end in SPLIT_DEFS:
        df = splits[split_name]
        bmin, bmax = df["base_time"].min(), df["base_time"].max()
        in_range = bool((df["base_time"] >= start).all() and (df["base_time"] < end).all())
        ranges[split_name] = (pd.Timestamp(start), pd.Timestamp(end))
        rows.append(
            {
                "split": split_name,
                "base_time_min": bmin,
                "base_time_max": bmax,
                "expected_start": start,
                "expected_end_exclusive": end,
                "within_expected_range": in_range,
            }
        )

    names = list(ranges.keys())
    overlaps = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a_start, a_end = ranges[names[i]]
            b_start, b_end = ranges[names[j]]
            if max(a_start, b_start) < min(a_end, b_end):
                overlaps.append(f"{names[i]}<->{names[j]}")

    df_out = pd.DataFrame(rows)
    df_out["overlap_with_other_split"] = ",".join(overlaps) if overlaps else ""
    return df_out


def check_station_coverage(splits: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, list[str]]:
    all_stations = sorted(set().union(*[set(df["station_id"].unique()) for df in splits.values()]))
    max_timestamps = {name: df["base_time"].nunique() for name, df in splits.items()}

    rows = []
    for station in all_stations:
        row = {"station_id": station}
        for name, df in splits.items():
            sub = df[df["station_id"] == station]
            ts_count = sub["base_time"].nunique()
            denom = max_timestamps[name] or 1
            row[f"in_{name}"] = ts_count > 0
            row[f"row_count_{name}"] = len(sub)
            row[f"coverage_ratio_{name}"] = ts_count / denom
        rows.append(row)

    df_out = pd.DataFrame(rows)
    presence_cols = [f"in_{name}" for name in splits]
    intersection_stations = df_out.loc[df_out[presence_cols].all(axis=1), "station_id"].tolist()
    return df_out, intersection_stations


def horizon_distribution(splits: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for name, df in splits.items():
        total = len(df)
        counts = df["horizon_min"].value_counts()
        for h in HORIZONS:
            c = int(counts.get(h, 0))
            rows.append(
                {
                    "split": name,
                    "horizon_min": h,
                    "row_count": c,
                    "ratio_within_split": c / total if total else 0.0,
                }
            )
    return pd.DataFrame(rows)


def target_distribution(splits: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for name, df in splits.items():
        for h in HORIZONS:
            sub = df.loc[df["horizon_min"] == h, "target_net_flow"]
            if sub.empty:
                continue
            rows.append(
                {
                    "split": name,
                    "horizon_min": h,
                    "mean": sub.mean(),
                    "std": sub.std(),
                    "min": sub.min(),
                    "p1": sub.quantile(0.01),
                    "p50": sub.quantile(0.5),
                    "p99": sub.quantile(0.99),
                    "max": sub.max(),
                    "zero_ratio": float((sub == 0).mean()),
                }
            )
    return pd.DataFrame(rows)


def direction_distribution(splits: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for name, df in splits.items():
        for h in HORIZONS:
            sub = df.loc[df["horizon_min"] == h, "target_net_flow"]
            if sub.empty:
                continue
            total = len(sub)
            rows.append(
                {
                    "split": name,
                    "horizon_min": h,
                    "decrease_ratio": float((sub < 0).sum() / total),
                    "stable_ratio": float((sub == 0).sum() / total),
                    "increase_ratio": float((sub > 0).sum() / total),
                }
            )
    return pd.DataFrame(rows)


def leakage_check(splits: dict[str, pd.DataFrame]) -> list[str]:
    issues = []
    for name, df in splits.items():
        anchor_time = df["base_time"] - pd.to_timedelta(df["minutes_since_stock_anchor"], unit="m")
        future_anchor = anchor_time > df["base_time"]
        negative_minutes = df["minutes_since_stock_anchor"] < 0
        if future_anchor.any():
            issues.append(f"[{name}] anchor 시점이 base_time보다 미래인 row {int(future_anchor.sum())}건")
        if negative_minutes.any():
            issues.append(f"[{name}] minutes_since_stock_anchor 음수 row {int(negative_minutes.sum())}건")
    return issues


def exception_concentration(master_dir: Path) -> pd.DataFrame:
    frames = []
    for year in (2024, 2025):
        path = master_dir / f"master_{year}_q3_top300.csv.gz"
        df = pd.read_csv(path, usecols=["station_id", "datetime_5m", "exception_delta_hour"])
        df["datetime_5m"] = pd.to_datetime(df["datetime_5m"])
        df["hour_bucket"] = df["datetime_5m"].dt.floor("h")
        hourly = df.drop_duplicates(subset=["station_id", "hour_bucket"])
        frames.append(hourly)
    combined = pd.concat(frames, ignore_index=True)
    agg = combined.groupby("station_id")["exception_delta_hour"].apply(lambda s: s.abs().sum())
    agg = agg.reset_index()
    agg.columns = ["station_id", "exception_abs_sum"]
    threshold = agg["exception_abs_sum"].quantile(EXCEPTION_FLAG_PERCENTILE)
    agg["high_exception_flag"] = agg["exception_abs_sum"] >= threshold
    return agg


def build_quality_flags(
    coverage_df: pd.DataFrame, exception_df: pd.DataFrame, intersection_stations: list[str]
) -> pd.DataFrame:
    flags = []
    for _, row in coverage_df.iterrows():
        station = row["station_id"]
        if station not in intersection_stations:
            flags.append(
                {
                    "station_id": station,
                    "flag_type": "missing_in_some_split",
                    "detail_value": "",
                    "recommendation": "exclude",
                }
            )
            continue
        for name in ("train", "valid", "test"):
            cov = row.get(f"coverage_ratio_{name}", 0.0)
            if cov < COVERAGE_PASS_THRESHOLD:
                flags.append(
                    {
                        "station_id": station,
                        "flag_type": "low_coverage",
                        "detail_value": f"{name}:{cov:.3f}",
                        "recommendation": "exclude_or_caution",
                    }
                )

    exc_flagged = exception_df[exception_df["high_exception_flag"]]
    for _, row in exc_flagged.iterrows():
        flags.append(
            {
                "station_id": row["station_id"],
                "flag_type": "high_exception",
                "detail_value": f"{row['exception_abs_sum']:.1f}",
                "recommendation": "exclude_from_profile",
            }
        )
    return pd.DataFrame(flags)


def main() -> None:
    args = parse_args()
    dataset_dir = Path(args.dataset_dir)
    master_dir = Path(args.master_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("split 로드...")
    splits = load_splits(dataset_dir)

    schema_df = check_schema(splits)
    boundary_df = check_split_boundaries(splits)
    coverage_df, intersection_stations = check_station_coverage(splits)
    horizon_df = horizon_distribution(splits)
    target_df = target_distribution(splits)
    direction_df = direction_distribution(splits)
    leakage_issues = leakage_check(splits)

    print("exception 집중도 계산 (master)...")
    exception_df = exception_concentration(master_dir)
    quality_flags_df = build_quality_flags(coverage_df, exception_df, intersection_stations)

    horizon_df.to_csv(output_dir / "horizon_distribution.csv", index=False)
    target_df.to_csv(output_dir / "target_distribution.csv", index=False)
    direction_df.to_csv(output_dir / "direction_distribution.csv", index=False)
    boundary_df.to_csv(output_dir / "split_boundary_check.csv", index=False)
    coverage_df.to_csv(output_dir / "station_coverage.csv", index=False)
    quality_flags_df.to_csv(output_dir / "data_quality_flags.csv", index=False)
    pd.DataFrame(FEATURE_AVAILABILITY).to_csv(output_dir / "feature_availability_matrix.csv", index=False)

    verdicts = []
    verdicts.append(("스키마 검증", "PASS" if bool(schema_df["ok"].all()) else "FAIL"))

    boundary_ok = bool(boundary_df["within_expected_range"].all()) and all(
        v == "" for v in boundary_df["overlap_with_other_split"]
    )
    verdicts.append(("split 경계 검증", "PASS" if boundary_ok else "FAIL"))

    intersection_ratio = len(intersection_stations) / max(len(coverage_df), 1)
    verdicts.append(
        (
            f"station 매칭 (교집합 {len(intersection_stations)}개, {intersection_ratio:.1%})",
            "PASS" if intersection_ratio >= COVERAGE_PASS_THRESHOLD else "WARN",
        )
    )

    horizon_spread = horizon_df.groupby("split")["ratio_within_split"].agg(lambda s: s.max() - s.min())
    horizon_ok = bool((horizon_spread <= HORIZON_BALANCE_WARN_PCT).all())
    verdicts.append(("horizon 분포 균형", "PASS" if horizon_ok else "WARN"))

    zero_ratio_max = target_df["zero_ratio"].max() if not target_df.empty else 0.0
    verdicts.append(
        (
            f"target_net_flow=0 비율 (최대 {zero_ratio_max:.1%})",
            "PASS" if zero_ratio_max < ZERO_RATIO_WARN_THRESHOLD else "WARN",
        )
    )

    verdicts.append(("feature leakage 점검", "PASS" if not leakage_issues else "WARN"))

    high_exception_count = int(exception_df["high_exception_flag"].sum())
    verdicts.append((f"이상치 station flag ({high_exception_count}개)", "INFO"))

    report_lines = ["# Q3 target_net_flow 데이터셋 검증 리포트", "", "## 판정 요약", "", "| 항목 | 판정 |", "|---|---|"]
    report_lines += [f"| {label} | {verdict} |" for label, verdict in verdicts]

    report_lines += ["", "## split별 row 수", ""]
    report_lines += [
        f"- {name}: {len(df):,} rows, station {df['station_id'].nunique()}개" for name, df in splits.items()
    ]

    report_lines += [
        "",
        "## 상세 산출물",
        "",
        "- target_distribution.csv, station_coverage.csv, split_boundary_check.csv",
        "- horizon_distribution.csv, direction_distribution.csv",
        "- feature_availability_matrix.csv, data_quality_flags.csv, leakage_check_report.md",
    ]

    (output_dir / "dataset_report.md").write_text("\n".join(report_lines), encoding="utf-8")

    leakage_lines = ["# feature leakage 점검 결과", ""]
    if leakage_issues:
        leakage_lines += [f"- {issue}" for issue in leakage_issues]
    else:
        leakage_lines.append("이상 없음 — known_stock anchor 시점이 항상 base_time 이전이다.")
    (output_dir / "leakage_check_report.md").write_text("\n".join(leakage_lines), encoding="utf-8")

    print(f"완료. 산출물: {output_dir}")
    for label, verdict in verdicts:
        print(f"  {verdict}: {label}")


if __name__ == "__main__":
    main()
