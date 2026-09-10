"""Phase 2 — 과거 OD 프로파일을 feature로 추가.

Phase 1의 Naive_Profile(station x 요일 x 시간대 과거 평균)을 tree 모델의 입력 feature로
직접 제공한다. train 기간으로만 계산하고 valid/test엔 조인만 한다(leakage 방지).

phase1_baseline.py의 모델 학습/평가 유틸을 그대로 재사용하고, FEATURE_COLS/MODEL_FEATURE_COLS만
historical_* 5개를 추가해 확장한다.

실행 예:
    python phase2_historical_profile.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase1_baseline as p1  # noqa: E402

TARGET_COL = p1.TARGET_COL
HORIZONS = p1.HORIZONS

PROFILE_KEYS_FULL = ["od_station_id", "day_of_week", "hour", "horizon_min"]
PROFILE_KEYS_STATION_HORIZON = ["od_station_id", "horizon_min"]
PROFILE_KEYS_GLOBAL = ["horizon_min"]
PROFILE_STAT_COLS = [
    "historical_net_flow_mean",
    "historical_net_flow_std",
    "historical_rent_mean",
    "historical_return_mean",
]

HISTORICAL_FEATURE_COLS = PROFILE_STAT_COLS + ["historical_profile_fallback_level"]
FEATURE_COLS = p1.FEATURE_COLS + HISTORICAL_FEATURE_COLS
MODEL_FEATURE_COLS = FEATURE_COLS + ["station_code"]

# phase1_baseline의 make_xy/fit_*/feature_importance_rows는 모듈 전역 FEATURE_COLS/
# MODEL_FEATURE_COLS를 호출 시점에 참조한다 — Phase 2 feature셋으로 확장해서 그대로 재사용한다.
p1.FEATURE_COLS = FEATURE_COLS
p1.MODEL_FEATURE_COLS = MODEL_FEATURE_COLS


class HistoricalProfileBuilder:
    """station x 요일 x 시간대 과거 통계를 train 기간으로만 계산하고 조인한다."""

    def __init__(self) -> None:
        self.full: pd.DataFrame | None = None
        self.station_horizon: pd.DataFrame | None = None
        self.global_: pd.DataFrame | None = None

    @staticmethod
    def _aggregate(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
        return (
            df.groupby(keys)
            .agg(
                historical_net_flow_mean=(TARGET_COL, "mean"),
                historical_net_flow_std=(TARGET_COL, "std"),
                historical_rent_mean=("target_rent_count", "mean"),
                historical_return_mean=("target_return_count", "mean"),
            )
            .reset_index()
        )

    def fit(self, train_df: pd.DataFrame) -> None:
        self.full = self._aggregate(train_df, PROFILE_KEYS_FULL)
        self.station_horizon = self._aggregate(train_df, PROFILE_KEYS_STATION_HORIZON)
        self.global_ = self._aggregate(train_df, PROFILE_KEYS_GLOBAL)

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        merged = df.merge(self.full, on=PROFILE_KEYS_FULL, how="left")
        merged["historical_profile_fallback_level"] = 0

        missing = merged["historical_net_flow_mean"].isna()
        if missing.any():
            fallback = merged.loc[missing, PROFILE_KEYS_STATION_HORIZON].merge(
                self.station_horizon, on=PROFILE_KEYS_STATION_HORIZON, how="left"
            )
            for col in PROFILE_STAT_COLS:
                merged.loc[missing, col] = fallback[col].to_numpy()
            merged.loc[missing, "historical_profile_fallback_level"] = 1

        still_missing = merged["historical_net_flow_mean"].isna()
        if still_missing.any():
            fallback = merged.loc[still_missing, PROFILE_KEYS_GLOBAL].merge(
                self.global_, on=PROFILE_KEYS_GLOBAL, how="left"
            )
            for col in PROFILE_STAT_COLS:
                merged.loc[still_missing, col] = fallback[col].to_numpy()
            merged.loc[still_missing, "historical_profile_fallback_level"] = 2

        # 표본 1개짜리 셀은 std가 NaN이 됨 — 변동성 없음(0)으로 채운다.
        merged["historical_net_flow_std"] = merged["historical_net_flow_std"].fillna(0.0)
        return merged


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 2 과거 프로파일 feature 추가 비교.")
    script_dir = Path(__file__).resolve()
    ai_dir = script_dir.parents[4]
    default_data_dir = ai_dir / "data" / "processed" / "BYC" / "stock_q3_mapped_netflow_v5"
    default_output_dir = script_dir.parents[1] / "outputs" / "phase2"
    parser.add_argument("--data-dir", default=str(default_data_dir))
    parser.add_argument("--output-dir", default=str(default_output_dir))
    parser.add_argument("--train-path", help="train CSV 경로. 지정하면 --data-dir/--file-tag보다 우선한다.")
    parser.add_argument("--valid-path", help="valid CSV 경로. 지정하면 --data-dir/--file-tag보다 우선한다.")
    parser.add_argument("--test-path", help="test CSV 경로. 지정하면 --data-dir/--file-tag보다 우선한다.")
    parser.add_argument("--rf-max-rows", type=int, default=2_000_000)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--file-tag", default="top300")
    return parser.parse_args()


def resolve_split_path(args: argparse.Namespace, split: str) -> Path:
    explicit = getattr(args, f"{split}_path", None)
    if explicit:
        return Path(explicit)
    return Path(args.data_dir) / f"{split}_netflow_q3_mapped_{args.file_tag}.csv.gz"


def read_split_with_targets(data_dir: Path, split: str, file_tag: str, path: Path | None = None) -> pd.DataFrame:
    """프로파일 계산에 target_rent_count/target_return_count도 필요해서 phase1의
    read_split보다 컬럼을 더 읽는다."""
    path = path or data_dir / f"{split}_netflow_q3_mapped_{file_tag}.csv.gz"
    # p1.FEATURE_COLS는 이미 확장된 상태라 원래 Phase 1 컬럼만 골라 읽는다.
    base_cols = [c for c in p1.FEATURE_COLS if c not in HISTORICAL_FEATURE_COLS]
    usecols = ["od_station_id", *base_cols, TARGET_COL, "target_rent_count", "target_return_count"]
    df = pd.read_csv(path, usecols=usecols)
    df["od_station_id"] = df["od_station_id"].astype(str)
    return df


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("split 로드...")
    train_df = read_split_with_targets(data_dir, "train", args.file_tag, resolve_split_path(args, "train"))
    valid_df = read_split_with_targets(data_dir, "valid", args.file_tag, resolve_split_path(args, "valid"))
    test_df = read_split_with_targets(data_dir, "test", args.file_tag, resolve_split_path(args, "test"))
    train_df, valid_df, test_df, station_categories = p1.add_station_code(train_df, valid_df, test_df)

    print("historical profile fit (train만 사용)...")
    profile = HistoricalProfileBuilder()
    profile.fit(train_df)
    train_df = profile.transform(train_df)
    valid_df = profile.transform(valid_df)
    test_df = profile.transform(test_df)

    print(
        f"Rows: train={len(train_df):,}, valid={len(valid_df):,}, test={len(test_df):,}, "
        f"stations={len(station_categories):,}, feature수={len(MODEL_FEATURE_COLS)}"
    )
    fallback_dist = test_df["historical_profile_fallback_level"].value_counts(normalize=True).sort_index()
    print(f"test fallback level 분포: {fallback_dist.to_dict()}")

    print("Naive_Profile fit...")
    naive_model = p1.NaiveProfileModel()
    naive_model.fit(train_df)

    fit_results: list[p1.FitResult] = [p1.FitResult("Naive_Profile", naive_model, 0.0)]

    print("RandomForest 학습...")
    fit_results.append(p1.fit_random_forest(train_df, args.rf_max_rows, args.random_state))

    print("XGBoost 학습...")
    fit_results.append(p1.fit_xgboost(train_df, valid_df, args.random_state))

    print("LightGBM 학습...")
    fit_results.append(p1.fit_lightgbm(train_df, valid_df, args.random_state))

    comparison_rows = []
    horizon_rows = []
    importance_rows = []
    fitted_models = {}
    skipped = {}

    for result in fit_results:
        if result.skipped_reason:
            print(f"Skipping {result.name}: {result.skipped_reason}")
            skipped[result.name] = result.skipped_reason
            continue
        print(f"Evaluating {result.name} (test)...")
        fitted_models[result.name] = result.model
        comparison_rows.append(p1.evaluate_model(result.name, result.model, test_df, result.train_time_sec))
        horizon_rows.extend(p1.evaluate_by_horizon(result.name, result.model, test_df, result.train_time_sec))
        importance_rows.extend(p1.feature_importance_rows(result.name, result.model))

    comparison = pd.DataFrame(comparison_rows).sort_values("mae")
    by_horizon = pd.DataFrame(horizon_rows).sort_values(["horizon_min", "mae"])
    feature_importance = pd.DataFrame(importance_rows)
    if not feature_importance.empty:
        feature_importance = feature_importance.sort_values(["model", "importance"], ascending=[True, False])

    best_model_name, best_reason = p1.select_best(comparison)
    best_model = fitted_models[best_model_name]

    comparison.to_csv(output_dir / "model_comparison.csv", index=False)
    by_horizon.to_csv(output_dir / "model_comparison_by_horizon.csv", index=False)
    feature_importance.to_csv(output_dir / "feature_importance.csv", index=False)
    joblib.dump(
        {
            "model_name": best_model_name,
            "model": best_model,
            "feature_cols": FEATURE_COLS,
            "model_feature_cols": MODEL_FEATURE_COLS,
            "station_categories": station_categories,
            "shortage_threshold": p1.SHORTAGE_THRESHOLD,
        },
        output_dir / "best_model.pkl",
    )

    naive_mae = comparison.loc[comparison["model"] == "Naive_Profile", "mae"].iloc[0]
    naive_r2 = comparison.loc[comparison["model"] == "Naive_Profile", "r2"].iloc[0]
    best_row = comparison[comparison["model"] == best_model_name].iloc[0]
    passed = (
        best_model_name != "Naive_Profile"
        and best_row["mae"] < naive_mae
        and best_row["r2"] > naive_r2
    )

    metrics = {
        "best_model": best_model_name,
        "best_reason": best_reason,
        "phase2_pass": bool(passed),
        "phase2_pass_criteria": "트리 모델이 Naive_Profile 대비 MAE와 R2 둘 다에서 앞서야 통과",
        "skipped_models": skipped,
        "row_counts": {
            "train": int(len(train_df)),
            "valid": int(len(valid_df)),
            "test": int(len(test_df)),
            "station_categories": int(len(station_categories)),
        },
        "test_fallback_level_distribution": {str(k): float(v) for k, v in fallback_dist.to_dict().items()},
        "comparison": comparison.to_dict(orient="records"),
        "by_horizon": by_horizon.to_dict(orient="records"),
    }
    (output_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Best model: {best_model_name} (Phase 2 통과 여부: {passed})")
    print(best_reason)
    print(comparison.to_string(index=False))


if __name__ == "__main__":
    main()
