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
import gc
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase1_baseline as p1

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
BASE_COLS = [
    c for c in FEATURE_COLS if c not in HISTORICAL_FEATURE_COLS
]  # historical_* 붙기 전 원본 컬럼

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
        return p1.downcast_memory(merged)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 2 과거 프로파일 feature 추가 비교.")
    script_dir = Path(__file__).resolve()
    ai_dir = script_dir.parents[4]
    default_data_dir = ai_dir / "data" / "processed" / "BYC" / "stock_q3_mapped_netflow_v5"
    default_output_dir = script_dir.parents[1] / "outputs" / "phase2"
    parser.add_argument("--data-dir", default=str(default_data_dir))
    parser.add_argument("--output-dir", default=str(default_output_dir))
    parser.add_argument(
        "--train-path", nargs="+", help="train CSV 경로. 여러 개 지정하면 순서대로 합쳐 읽는다."
    )
    parser.add_argument(
        "--valid-path",
        nargs="+",
        help="valid CSV 경로. 지정하면 --data-dir/--file-tag보다 우선한다.",
    )
    parser.add_argument(
        "--test-path", nargs="+", help="test CSV 경로. 지정하면 --data-dir/--file-tag보다 우선한다."
    )
    parser.add_argument("--rf-max-rows", type=int, default=2_000_000)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--file-tag", default="top300")
    return parser.parse_args()


def resolve_split_path(args: argparse.Namespace, split: str) -> list[Path]:
    explicit = getattr(args, f"{split}_path", None)
    if explicit:
        return [Path(path) for path in explicit]
    return [Path(args.data_dir) / f"{split}_netflow_q3_mapped_{args.file_tag}.csv.gz"]


def read_split_with_targets(
    data_dir: Path, split: str, file_tag: str, path: Path | list[Path] | None = None
) -> pd.DataFrame:
    """프로파일 계산에 target_rent_count/target_return_count도 필요해서 phase1의
    read_split보다 컬럼을 더 읽는다."""
    paths = path or [data_dir / f"{split}_netflow_q3_mapped_{file_tag}.csv.gz"]
    if isinstance(paths, Path):
        paths = [paths]
    usecols = ["od_station_id", *BASE_COLS, TARGET_COL, "target_rent_count", "target_return_count"]
    # od_station_id를 str로 두면 300종류뿐인데도 행마다 별도 Python 문자열 객체가 생겨
    # 큰 스케일에서 수십 GB를 먹는다 — category로 바꿔서 해결하려 했는데(4차 수정), 청크마다
    # (혹은 분기마다) 등장하는 station 종류가 조금만 달라도 pd.concat이 category를 못
    # 지키고 str로 되돌아간다는 걸 실측 확인함(pandas 3.0.5, 카테고리가 다른 Categorical
    # Series를 concat하면 dtype이 str이 됨) — 그래서 09m/12m처럼 청크·분기 수가 많을수록
    # 이 "조용한 원상복구"가 자주 발생해 재시도해도 계속 실패했다(2026-09-12).
    # 고정 카테고리: 전체 경로를 먼저 훑어 station id 전체 집합을 구하고, 모든 청크에
    # 동일한 카테고리를 강제 지정해 concat 중에 category가 절대 깨지지 않게 한다.
    station_ids = p1.scan_station_ids(paths, chunk_size=p1.CHUNK_SIZE)
    station_cat_dtype = pd.CategoricalDtype(categories=sorted(station_ids))
    chunks = []
    for chunk in p1.iter_csv_chunks(paths, usecols, chunk_size=p1.CHUNK_SIZE):
        chunk["od_station_id"] = chunk["od_station_id"].astype(str).astype(station_cat_dtype)
        chunks.append(p1.downcast_memory(chunk))
    df = pd.concat(chunks, ignore_index=True)
    return p1.downcast_memory(df)


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 메모리 절감: test(대개 valid/train보다 훨씬 큼)는 모델 학습이 끝난 뒤 평가 직전에
    # 로드한다 — train+valid+test를 동시에 들고 있다가 historical profile merge에서
    # OOM kill 당하는 문제(Phase 2.5, 10-horizon 대용량 데이터) 때문에 순서를 바꿨다.
    # station_code dtype은 train∪valid∪test 전체 station id로 만든다 — 처음엔
    # train∪valid만으로 만들었었는데(top300은 Phase 0에서 train=valid=test station
    # 집합 동일이 확인돼 있어 그걸로 충분했음), stratified300에서 test에만 있는 station이
    # 있어 apply_station_code() assert가 실패하는 걸 실측으로 확인함(03m/stratified300).
    # test를 통째로 메모리에 올리지 않고 station id 컬럼만 청크 스캔해서(scan_station_ids)
    # dtype 구성 범위에 포함시킨다 — 메모리 절감 설계는 그대로 유지된다.
    print("split 로드 (train/valid)...")
    train_df = read_split_with_targets(
        data_dir, "train", args.file_tag, resolve_split_path(args, "train")
    )
    valid_df = read_split_with_targets(
        data_dir, "valid", args.file_tag, resolve_split_path(args, "valid")
    )
    test_paths = resolve_split_path(args, "test") or [
        data_dir / f"test_netflow_q3_mapped_{args.file_tag}.csv.gz"
    ]
    print("test station id 스캔 (dtype 구성용, 전체 로드 아님)...")
    test_station_ids = p1.scan_station_ids(test_paths)
    station_dtype = p1.build_station_dtype(train_df, valid_df, test_station_ids)
    p1.apply_station_code(train_df, station_dtype, "train")
    p1.apply_station_code(valid_df, station_dtype, "valid")
    station_categories = list(station_dtype.categories)

    print("historical profile fit (train만 사용)...")
    profile = HistoricalProfileBuilder()
    profile.fit(train_df)
    train_df = profile.transform(train_df)
    valid_df = profile.transform(valid_df)

    print(
        f"Rows: train={len(train_df):,}, valid={len(valid_df):,}, "
        f"stations={len(station_categories):,}, feature수={len(MODEL_FEATURE_COLS)}"
    )

    # 로딩~프로파일 merge 과정에서 나온 중간 객체(청크 리스트, merge 이전 프레임 등)가
    # 참조 해제됐어도 GC 사이클이 안 돌면 메모리에 남아있을 수 있음 — XGBoost가 자체
    # DMatrix를 만들며 학습 데이터 크기만큼 추가로 할당하는 시점 직전이라 미리 정리한다.
    gc.collect()

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

    # 학습 끝났으니 train_df/valid_df는 더 필요 없음 — test 청크 평가 전에 메모리 확보
    train_rows = len(train_df)
    valid_rows = len(valid_df)
    del train_df, valid_df
    gc.collect()

    fitted_models = {r.name: r.model for r in fit_results if not r.skipped_reason}
    skipped = {r.name: r.skipped_reason for r in fit_results if r.skipped_reason}
    for name, reason in skipped.items():
        print(f"Skipping {name}: {reason}")
    importance_rows = []
    for r in fit_results:
        if not r.skipped_reason:
            importance_rows.extend(p1.feature_importance_rows(r.name, r.model))

    print("test 청크 단위 평가...")
    test_usecols = ["od_station_id", *BASE_COLS, TARGET_COL]
    comparison, by_horizon, fallback_tally = p1.evaluate_test_chunked(
        fit_results,
        test_paths,
        test_usecols,
        station_dtype,
        transform_fn=profile.transform,
        tally_col="historical_profile_fallback_level",
    )
    test_rows = sum(fallback_tally.values())
    fallback_dist = {str(k): v / test_rows for k, v in fallback_tally.items()} if test_rows else {}
    print(f"test rows={test_rows:,}, fallback level 분포: {fallback_dist}")

    feature_importance = pd.DataFrame(importance_rows)
    if not feature_importance.empty:
        feature_importance = feature_importance.sort_values(
            ["model", "importance"], ascending=[True, False]
        )

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
            "train": int(train_rows),
            "valid": int(valid_rows),
            "test": int(test_rows),
            "station_categories": len(station_categories),
        },
        "test_fallback_level_distribution": {k: float(v) for k, v in fallback_dist.items()},
        "comparison": comparison.to_dict(orient="records"),
        "by_horizon": by_horizon.to_dict(orient="records"),
    }
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Best model: {best_model_name} (Phase 2 통과 여부: {passed})")
    print(best_reason)
    print(comparison.to_string(index=False))


if __name__ == "__main__":
    main()
