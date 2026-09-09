"""Phase 0 — q3_mapped_netflow_v5 데이터셋 검증 리포트.

좌표 기반 station 매핑 + target_net_flow가 이미 계산된 상태로 전달받은 데이터셋을
독립적으로(자체 validation_report.json을 그대로 믿지 않고) 재검증한다.

build_target_dataset.py/dataset_report.py(구버전 target_delta 기반)는 이 데이터셋과
무관하다 — target_net_flow 생성이 이미 상류에서 끝나 있어서 여기서는 검증만 한다.

실행 예:
    python dataset_report_v5.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

HORIZONS = [5, 10, 15, 30]

SPLIT_DEFS = [
    ("train", "2024-07-01", "2024-09-16"),
    ("valid", "2024-09-16", "2024-10-01"),
    ("test", "2025-07-01", "2025-10-01"),
]

EXPECTED_COLUMNS = [
    "od_station_id",
    "station_no",
    "station_name",
    "district",
    "lat_stock",
    "lon_stock",
    "rack_count",
    "datetime_5m",
    "datetime_hour",
    "date",
    "year",
    "month",
    "hour",
    "minute",
    "day_of_week",
    "is_weekend",
    "slot_5m",
    "sin_hour",
    "cos_hour",
    "sin_slot",
    "cos_slot",
    "stock_anchor_hour",
    "stock_ratio_hour",
    "minutes_since_stock_anchor",
    "is_empty_anchor",
    "is_full_anchor",
    "rent_count_5m",
    "return_count_5m",
    "net_flow_5m",
    "base_time",
    "horizon_min",
    "target_net_flow",
    "target_rent_count",
    "target_return_count",
]

# A안 전용(배포 불가) — feature_availability_matrix에서 제외 표시할 컬럼
A_ONLY_COLUMNS = {"rent_count_5m", "return_count_5m", "net_flow_5m"}

COVERAGE_PASS_THRESHOLD = 0.95
ZERO_RATIO_WARN_THRESHOLD = 0.90
HORIZON_BALANCE_WARN_PCT = 0.05
EXCEPTION_FLAG_PERCENTILE = 0.95

FEATURE_AVAILABILITY = [
    {"feature": "stock_anchor_hour", "trainable": "가능", "servable": "가능(실시간 API로 대체)", "used_in_baseline": "포함"},
    {"feature": "minutes_since_stock_anchor", "trainable": "가능", "servable": "가능", "used_in_baseline": "포함"},
    {"feature": "stock_ratio_hour", "trainable": "가능", "servable": "가능", "used_in_baseline": "포함"},
    {"feature": "is_empty_anchor / is_full_anchor", "trainable": "가능", "servable": "가능", "used_in_baseline": "포함"},
    {"feature": "sin/cos_hour, sin/cos_slot", "trainable": "가능", "servable": "가능", "used_in_baseline": "포함"},
    {"feature": "district, lat_stock, lon_stock, rack_count", "trainable": "가능", "servable": "가능", "used_in_baseline": "포함(Phase 3 조기 사용)"},
    {"feature": "rent_count_5m / return_count_5m / net_flow_5m", "trainable": "가능", "servable": "불가", "used_in_baseline": "제외 (A안 감사용)"},
    {"feature": "historical_profile_net (Phase 2)", "trainable": "가능", "servable": "가능", "used_in_baseline": "포함 예정"},
    {"feature": "weather_current (Phase 4)", "trainable": "가능", "servable": "가능", "used_in_baseline": "포함 예정"},
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="q3_mapped_netflow_v5 데이터셋 Phase 0 검증 리포트를 만든다.")
    script_dir = Path(__file__).resolve()
    ai_dir = script_dir.parents[4]
    default_dataset_dir = ai_dir / "data" / "processed" / "BYC" / "stock_q3_mapped_netflow_v5"
    default_output_dir = script_dir.parents[1] / "outputs"
    parser.add_argument("--dataset-dir", default=str(default_dataset_dir))
    parser.add_argument("--output-dir", default=str(default_output_dir))
    parser.add_argument(
        "--file-tag",
        default="top300",
        help="파일명 접미사 (예: top300, stratified300) — {split}_netflow_q3_mapped_{tag}.csv.gz",
    )
    return parser.parse_args()


def load_splits(dataset_dir: Path, file_tag: str = "top300") -> dict[str, pd.DataFrame]:
    splits = {}
    for split_name, _start, _end in SPLIT_DEFS:
        path = dataset_dir / f"{split_name}_netflow_q3_mapped_{file_tag}.csv.gz"
        df = pd.read_csv(path)
        df["base_time"] = pd.to_datetime(df["base_time"])
        df["od_station_id"] = df["od_station_id"].astype(str)
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
    for split_name, start, end in SPLIT_DEFS:
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
    all_stations = sorted(set().union(*[set(df["od_station_id"].unique()) for df in splits.values()]))
    max_timestamps = {name: df["base_time"].nunique() for name, df in splits.items()}

    rows = []
    for station in all_stations:
        row = {"od_station_id": station}
        for name, df in splits.items():
            sub = df[df["od_station_id"] == station]
            ts_count = sub["base_time"].nunique()
            denom = max_timestamps[name] or 1
            row[f"in_{name}"] = ts_count > 0
            row[f"row_count_{name}"] = len(sub)
            row[f"coverage_ratio_{name}"] = ts_count / denom
        rows.append(row)

    df_out = pd.DataFrame(rows)
    presence_cols = [f"in_{name}" for name in splits]
    intersection_stations = df_out.loc[df_out[presence_cols].all(axis=1), "od_station_id"].tolist()
    return df_out, intersection_stations


def horizon_distribution(splits: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for name, df in splits.items():
        total = len(df)
        counts = df["horizon_min"].value_counts()
        for h in HORIZONS:
            c = int(counts.get(h, 0))
            rows.append(
                {"split": name, "horizon_min": h, "row_count": c, "ratio_within_split": c / total if total else 0.0}
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


def stock_anchor_coverage(splits: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for name, df in splits.items():
        missing = df["stock_anchor_hour"].isna().mean()
        rows.append(
            {
                "split": name,
                "stock_anchor_missing_rate": float(missing),
                "minutes_since_anchor_max": float(df["minutes_since_stock_anchor"].max()),
                "minutes_since_anchor_min": float(df["minutes_since_stock_anchor"].min()),
                "is_empty_anchor_rate": float(df["is_empty_anchor"].mean()),
                "is_full_anchor_rate": float(df["is_full_anchor"].mean()),
            }
        )
    return pd.DataFrame(rows)


def station_outlier_flags(splits: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """exception_delta_hour 컬럼이 이 데이터셋엔 없어서, target_net_flow 변동성과
    empty/full anchor 비율로 이상치 후보 정류장을 잡는다."""
    train = splits["train"]
    agg = train.groupby("od_station_id").agg(
        target_std=("target_net_flow", "std"),
        empty_rate=("is_empty_anchor", "mean"),
        full_rate=("is_full_anchor", "mean"),
    )
    std_threshold = agg["target_std"].quantile(EXCEPTION_FLAG_PERCENTILE)
    empty_threshold = agg["empty_rate"].quantile(EXCEPTION_FLAG_PERCENTILE)
    full_threshold = agg["full_rate"].quantile(EXCEPTION_FLAG_PERCENTILE)

    agg["high_variance_flag"] = agg["target_std"] >= std_threshold
    agg["high_empty_flag"] = agg["empty_rate"] >= empty_threshold
    agg["high_full_flag"] = agg["full_rate"] >= full_threshold
    return agg.reset_index()


def build_quality_flags(
    coverage_df: pd.DataFrame, outlier_df: pd.DataFrame, intersection_stations: list[str]
) -> pd.DataFrame:
    flags = []
    for _, row in coverage_df.iterrows():
        station = row["od_station_id"]
        if station not in intersection_stations:
            flags.append(
                {"od_station_id": station, "flag_type": "missing_in_some_split", "detail_value": "", "recommendation": "exclude"}
            )
            continue
        for name in ("train", "valid", "test"):
            cov = row.get(f"coverage_ratio_{name}", 0.0)
            if cov < COVERAGE_PASS_THRESHOLD:
                flags.append(
                    {
                        "od_station_id": station,
                        "flag_type": "low_coverage",
                        "detail_value": f"{name}:{cov:.3f}",
                        "recommendation": "exclude_or_caution",
                    }
                )

    for _, row in outlier_df.iterrows():
        if row["high_variance_flag"]:
            flags.append(
                {
                    "od_station_id": row["od_station_id"],
                    "flag_type": "high_target_variance",
                    "detail_value": f"{row['target_std']:.2f}",
                    "recommendation": "review",
                }
            )
        if row["high_empty_flag"] or row["high_full_flag"]:
            flags.append(
                {
                    "od_station_id": row["od_station_id"],
                    "flag_type": "high_empty_or_full_anchor",
                    "detail_value": f"empty={row['empty_rate']:.3f},full={row['full_rate']:.3f}",
                    "recommendation": "review",
                }
            )
    return pd.DataFrame(flags)


def main() -> None:
    args = parse_args()
    dataset_dir = Path(args.dataset_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("split 로드...")
    splits = load_splits(dataset_dir, args.file_tag)

    schema_df = check_schema(splits)
    boundary_df = check_split_boundaries(splits)
    coverage_df, intersection_stations = check_station_coverage(splits)
    horizon_df = horizon_distribution(splits)
    target_df = target_distribution(splits)
    direction_df = direction_distribution(splits)
    leakage_issues = leakage_check(splits)
    anchor_df = stock_anchor_coverage(splits)
    outlier_df = station_outlier_flags(splits)
    quality_flags_df = build_quality_flags(coverage_df, outlier_df, intersection_stations)

    horizon_df.to_csv(output_dir / "horizon_distribution.csv", index=False)
    target_df.to_csv(output_dir / "target_distribution.csv", index=False)
    direction_df.to_csv(output_dir / "direction_distribution.csv", index=False)
    boundary_df.to_csv(output_dir / "split_boundary_check.csv", index=False)
    coverage_df.to_csv(output_dir / "station_coverage.csv", index=False)
    anchor_df.to_csv(output_dir / "stock_anchor_coverage.csv", index=False)
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

    max_missing = anchor_df["stock_anchor_missing_rate"].max()
    verdicts.append((f"stock anchor 결측률 (최대 {max_missing:.2%})", "PASS" if max_missing < 0.05 else "WARN"))

    outlier_count = int(
        (outlier_df["high_variance_flag"] | outlier_df["high_empty_flag"] | outlier_df["high_full_flag"]).sum()
    )
    verdicts.append((f"이상치 station flag ({outlier_count}개)", "INFO"))

    report_lines = [
        "# Q3 mapped netflow v5 데이터셋 검증 리포트",
        "",
        "## 판정 요약",
        "",
        "| 항목 | 판정 |",
        "|---|---|",
    ]
    report_lines += [f"| {label} | {verdict} |" for label, verdict in verdicts]

    report_lines += ["", "## split별 row 수", ""]
    report_lines += [
        f"- {name}: {len(df):,} rows, station {df['od_station_id'].nunique()}개" for name, df in splits.items()
    ]

    report_lines += [
        "",
        "## 상세 산출물",
        "",
        "- target_distribution.csv, station_coverage.csv, split_boundary_check.csv",
        "- horizon_distribution.csv, direction_distribution.csv, stock_anchor_coverage.csv",
        "- feature_availability_matrix.csv, data_quality_flags.csv, leakage_check_report.md",
    ]

    (output_dir / "dataset_report.md").write_text("\n".join(report_lines), encoding="utf-8")

    leakage_lines = ["# feature leakage 점검 결과", ""]
    if leakage_issues:
        leakage_lines += [f"- {issue}" for issue in leakage_issues]
    else:
        leakage_lines.append("이상 없음 — stock anchor 시점이 항상 base_time 이전이다.")
    (output_dir / "leakage_check_report.md").write_text("\n".join(leakage_lines), encoding="utf-8")

    print(f"완료. 산출물: {output_dir}")
    for label, verdict in verdicts:
        print(f"  {verdict}: {label}")


if __name__ == "__main__":
    main()
