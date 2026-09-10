"""Phase 1 — B안 최소 배포 가능 feature baseline.

recent-OD 없이 station_id + 현재 재고 상태 + 시간/주기성만으로 target_net_flow를
예측할 수 있는지 확인한다. Naive_Profile(station x 요일 x 시간대 과거 평균) vs
RandomForest/XGBoost/LightGBM을 비교한다.

실행 예:
    python phase1_baseline.py
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, mean_squared_error, r2_score

FEATURE_COLS = [
    "horizon_min",
    "stock_anchor_hour",
    "stock_ratio_hour",
    "minutes_since_stock_anchor",
    "is_empty_anchor",
    "is_full_anchor",
    "hour",
    "minute",
    "day_of_week",
    "is_weekend",
    "month",
    "sin_hour",
    "cos_hour",
    "sin_slot",
    "cos_slot",
]
MODEL_FEATURE_COLS = FEATURE_COLS + ["station_code"]
TARGET_COL = "target_net_flow"
SHORTAGE_THRESHOLD = 2
HORIZONS = [5, 10, 15, 30]
PROFILE_KEYS_FULL = ["od_station_id", "day_of_week", "hour", "horizon_min"]
PROFILE_KEYS_STATION_HORIZON = ["od_station_id", "horizon_min"]
PROFILE_KEYS_GLOBAL = ["horizon_min"]


@dataclass
class FitResult:
    name: str
    model: Any
    train_time_sec: float
    skipped_reason: str | None = None


class NaiveProfileModel:
    """station x 요일 x 시간대 과거 평균 net_flow. train 기간으로만 fit한다.

    표본이 없는 (station, dow, hour, horizon) 조합은 (station, horizon) 평균으로,
    그것도 없으면 horizon 전체 평균으로 순서대로 fallback한다.
    """

    def __init__(self) -> None:
        self.profile_full: pd.DataFrame | None = None
        self.profile_station_horizon: pd.DataFrame | None = None
        self.profile_global: pd.DataFrame | None = None

    def fit(self, df: pd.DataFrame) -> None:
        self.profile_full = (
            df.groupby(PROFILE_KEYS_FULL)[TARGET_COL].mean().reset_index().rename(columns={TARGET_COL: "_pred"})
        )
        self.profile_station_horizon = (
            df.groupby(PROFILE_KEYS_STATION_HORIZON)[TARGET_COL]
            .mean()
            .reset_index()
            .rename(columns={TARGET_COL: "_pred_sh"})
        )
        self.profile_global = (
            df.groupby(PROFILE_KEYS_GLOBAL)[TARGET_COL].mean().reset_index().rename(columns={TARGET_COL: "_pred_g"})
        )

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        merged = df.merge(self.profile_full, on=PROFILE_KEYS_FULL, how="left")
        missing = merged["_pred"].isna()
        if missing.any():
            fallback = merged.loc[missing, PROFILE_KEYS_STATION_HORIZON].merge(
                self.profile_station_horizon, on=PROFILE_KEYS_STATION_HORIZON, how="left"
            )
            merged.loc[missing, "_pred"] = fallback["_pred_sh"].to_numpy()
        still_missing = merged["_pred"].isna()
        if still_missing.any():
            fallback = merged.loc[still_missing, PROFILE_KEYS_GLOBAL].merge(
                self.profile_global, on=PROFILE_KEYS_GLOBAL, how="left"
            )
            merged.loc[still_missing, "_pred"] = fallback["_pred_g"].to_numpy()
        return merged["_pred"].fillna(0.0).to_numpy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 1 B안 최소 feature baseline 비교.")
    script_dir = Path(__file__).resolve()
    ai_dir = script_dir.parents[4]
    default_data_dir = ai_dir / "data" / "processed" / "BYC" / "stock_q3_mapped_netflow_v5"
    default_output_dir = script_dir.parents[1] / "outputs" / "phase1"
    parser.add_argument("--data-dir", default=str(default_data_dir))
    parser.add_argument("--output-dir", default=str(default_output_dir))
    parser.add_argument("--train-path", help="train CSV 경로. 지정하면 --data-dir/--file-tag보다 우선한다.")
    parser.add_argument("--valid-path", help="valid CSV 경로. 지정하면 --data-dir/--file-tag보다 우선한다.")
    parser.add_argument("--test-path", help="test CSV 경로. 지정하면 --data-dir/--file-tag보다 우선한다.")
    parser.add_argument("--rf-max-rows", type=int, default=2_000_000)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument(
        "--file-tag",
        default="top300",
        help="파일명 접미사 (예: top300, stratified300) — {split}_netflow_q3_mapped_{tag}.csv.gz",
    )
    return parser.parse_args()


def resolve_split_path(args: argparse.Namespace, split: str) -> Path:
    explicit = getattr(args, f"{split}_path", None)
    if explicit:
        return Path(explicit)
    return Path(args.data_dir) / f"{split}_netflow_q3_mapped_{args.file_tag}.csv.gz"


def read_split(data_dir: Path, split: str, file_tag: str = "top300", path: Path | None = None) -> pd.DataFrame:
    path = path or data_dir / f"{split}_netflow_q3_mapped_{file_tag}.csv.gz"
    usecols = ["od_station_id", *FEATURE_COLS, TARGET_COL]
    df = pd.read_csv(path, usecols=usecols)
    df["od_station_id"] = df["od_station_id"].astype(str)
    return df


def add_station_code(
    train: pd.DataFrame, valid: pd.DataFrame, test: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    categories = sorted(
        set(train["od_station_id"]) | set(valid["od_station_id"]) | set(test["od_station_id"])
    )
    dtype = pd.CategoricalDtype(categories=categories)
    for df in (train, valid, test):
        df["station_code"] = df["od_station_id"].astype(dtype).cat.codes
    return train, valid, test, categories


def make_xy(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    return df[MODEL_FEATURE_COLS].fillna(0), df[TARGET_COL].fillna(0)


def fit_random_forest(train_df: pd.DataFrame, rf_max_rows: int, random_state: int) -> FitResult:
    fit_df = train_df.sample(n=rf_max_rows, random_state=random_state) if len(train_df) > rf_max_rows else train_df
    x_train, y_train = make_xy(fit_df)
    model = RandomForestRegressor(
        n_estimators=150, max_depth=18, min_samples_leaf=3, n_jobs=-1, random_state=random_state
    )
    started_at = time.perf_counter()
    model.fit(x_train, y_train)
    return FitResult("RandomForest", model, time.perf_counter() - started_at)


def fit_xgboost(train_df: pd.DataFrame, valid_df: pd.DataFrame, random_state: int) -> FitResult:
    try:
        from xgboost import XGBRegressor
    except ImportError as exc:
        return FitResult("XGBoost", None, 0.0, f"xgboost import failed: {exc}")

    x_train, y_train = make_xy(train_df)
    x_valid, y_valid = make_xy(valid_df)
    model = XGBRegressor(
        n_estimators=500,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        objective="reg:squarederror",
        tree_method="hist",
        random_state=random_state,
        n_jobs=-1,
    )
    started_at = time.perf_counter()
    try:
        model.fit(x_train, y_train, eval_set=[(x_valid, y_valid)], verbose=False, early_stopping_rounds=30)
    except TypeError:
        model.fit(x_train, y_train)
    return FitResult("XGBoost", model, time.perf_counter() - started_at)


def fit_lightgbm(train_df: pd.DataFrame, valid_df: pd.DataFrame, random_state: int) -> FitResult:
    try:
        from lightgbm import LGBMRegressor, early_stopping, log_evaluation
    except ImportError as exc:
        return FitResult("LightGBM", None, 0.0, f"lightgbm import failed: {exc}")

    x_train, y_train = make_xy(train_df)
    x_valid, y_valid = make_xy(valid_df)
    model = LGBMRegressor(
        n_estimators=500,
        learning_rate=0.05,
        num_leaves=63,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=random_state,
        n_jobs=-1,
    )
    started_at = time.perf_counter()
    try:
        model.fit(
            x_train,
            y_train,
            eval_set=[(x_valid, y_valid)],
            callbacks=[early_stopping(30), log_evaluation(0)],
        )
    except TypeError:
        model.fit(x_train, y_train)
    return FitResult("LightGBM", model, time.perf_counter() - started_at)


def rmse(y_true, y_pred) -> float:
    return math.sqrt(mean_squared_error(y_true, y_pred))


def wape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    denom = np.sum(np.abs(y_true))
    return float(np.sum(np.abs(y_true - y_pred)) / denom) if denom else float("nan")


def direction_class(values: np.ndarray) -> np.ndarray:
    return np.where(values < 0, "decrease", np.where(values > 0, "increase", "stable"))


def direction_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float]:
    true_c = direction_class(y_true)
    pred_c = direction_class(y_pred)
    acc = accuracy_score(true_c, pred_c)
    macro_f1 = f1_score(true_c, pred_c, average="macro", labels=["decrease", "stable", "increase"], zero_division=0)
    return float(acc), float(macro_f1)


def decrease_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    true_dec = y_true < 0
    pred_dec = y_pred < 0
    tp = int(np.logical_and(true_dec, pred_dec).sum())
    fp = int(np.logical_and(~true_dec, pred_dec).sum())
    fn = int(np.logical_and(true_dec, ~pred_dec).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"decrease_precision": precision, "decrease_recall": recall, "decrease_f1": f1}


def shortage_metrics(pred_stock: np.ndarray, true_stock: np.ndarray) -> dict[str, float]:
    pred_shortage = pred_stock <= SHORTAGE_THRESHOLD
    true_shortage = true_stock <= SHORTAGE_THRESHOLD
    tp = int(np.logical_and(pred_shortage, true_shortage).sum())
    fp = int(np.logical_and(pred_shortage, ~true_shortage).sum())
    fn = int(np.logical_and(~pred_shortage, true_shortage).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"shortage_precision": precision, "shortage_recall": recall, "shortage_f1": f1}


def predict_model(model: Any, df: pd.DataFrame) -> np.ndarray:
    if isinstance(model, NaiveProfileModel):
        return model.predict(df)
    x, _ = make_xy(df)
    return model.predict(x)


def evaluate_predictions(
    model_name: str, df: pd.DataFrame, pred: np.ndarray, train_time_sec: float, infer_time_sec: float
) -> dict[str, Any]:
    y_true = df[TARGET_COL].fillna(0).to_numpy()
    true_stock = df["stock_anchor_hour"].fillna(0).to_numpy() + y_true
    pred_stock = df["stock_anchor_hour"].fillna(0).to_numpy() + pred

    direction_acc, direction_f1 = direction_metrics(y_true, pred)

    metrics: dict[str, Any] = {
        "model": model_name,
        "mae": mean_absolute_error(y_true, pred),
        "rmse": rmse(y_true, pred),
        "wape": wape(y_true, pred),
        "r2": r2_score(y_true, pred),
        "direction_accuracy": direction_acc,
        "direction_macro_f1": direction_f1,
        "train_time_sec": train_time_sec,
        "infer_time_sec": infer_time_sec,
        "infer_rows_per_sec": len(df) / infer_time_sec if infer_time_sec > 0 else float("inf"),
    }
    metrics.update(decrease_metrics(y_true, pred))
    metrics.update(shortage_metrics(pred_stock, true_stock))
    return metrics


def evaluate_model(model_name: str, model: Any, df: pd.DataFrame, train_time_sec: float) -> dict[str, Any]:
    started_at = time.perf_counter()
    pred = predict_model(model, df)
    infer_time_sec = time.perf_counter() - started_at
    return evaluate_predictions(model_name, df, pred, train_time_sec, infer_time_sec)


def evaluate_by_horizon(model_name: str, model: Any, df: pd.DataFrame, train_time_sec: float) -> list[dict[str, Any]]:
    rows = []
    for horizon in HORIZONS:
        sub = df[df["horizon_min"] == horizon]
        if sub.empty:
            continue
        metrics = evaluate_model(model_name, model, sub, train_time_sec)
        metrics["horizon_min"] = horizon
        rows.append(metrics)
    return rows


def feature_importance_rows(model_name: str, model: Any) -> list[dict[str, Any]]:
    importances = getattr(model, "feature_importances_", None)
    if importances is None:
        return []
    total = float(np.sum(importances))
    rows = []
    for feature, importance in zip(MODEL_FEATURE_COLS, importances, strict=True):
        rows.append(
            {
                "model": model_name,
                "feature": feature,
                "importance": float(importance),
                "importance_normalized": float(importance / total) if total else 0.0,
            }
        )
    return rows


def select_best(comparison: pd.DataFrame) -> tuple[str, str]:
    naive_mae = comparison.loc[comparison["model"] == "Naive_Profile", "mae"].min()
    eligible = comparison[(comparison["model"] != "Naive_Profile") & (comparison["mae"] < naive_mae)].copy()

    if eligible.empty:
        fallback = comparison.sort_values(
            ["mae", "decrease_recall", "infer_time_sec"], ascending=[True, False, True]
        ).iloc[0]
        return str(fallback["model"]), "Naive_Profile을 이긴 모델이 없음. 전체 중 최선을 저장(Phase 2 필요성의 근거)."

    eligible["mae_rank_key"] = eligible["mae"].round(4)
    best = eligible.sort_values(["mae_rank_key", "decrease_recall", "infer_time_sec"], ascending=[True, False, True]).iloc[0]
    return str(best["model"]), "Naive_Profile을 이긴 모델 중 최선을 선택."


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("split 로드...")
    train_df = read_split(data_dir, "train", args.file_tag, resolve_split_path(args, "train"))
    valid_df = read_split(data_dir, "valid", args.file_tag, resolve_split_path(args, "valid"))
    test_df = read_split(data_dir, "test", args.file_tag, resolve_split_path(args, "test"))
    train_df, valid_df, test_df, station_categories = add_station_code(train_df, valid_df, test_df)

    print(
        f"Rows: train={len(train_df):,}, valid={len(valid_df):,}, test={len(test_df):,}, "
        f"stations={len(station_categories):,}"
    )

    print("Naive_Profile fit...")
    naive_model = NaiveProfileModel()
    naive_model.fit(train_df)

    fit_results: list[FitResult] = [FitResult("Naive_Profile", naive_model, 0.0)]

    print("RandomForest 학습...")
    fit_results.append(fit_random_forest(train_df, args.rf_max_rows, args.random_state))

    print("XGBoost 학습...")
    fit_results.append(fit_xgboost(train_df, valid_df, args.random_state))

    print("LightGBM 학습...")
    fit_results.append(fit_lightgbm(train_df, valid_df, args.random_state))

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
        comparison_rows.append(evaluate_model(result.name, result.model, test_df, result.train_time_sec))
        horizon_rows.extend(evaluate_by_horizon(result.name, result.model, test_df, result.train_time_sec))
        importance_rows.extend(feature_importance_rows(result.name, result.model))

    comparison = pd.DataFrame(comparison_rows).sort_values("mae")
    by_horizon = pd.DataFrame(horizon_rows).sort_values(["horizon_min", "mae"])
    feature_importance = pd.DataFrame(importance_rows)
    if not feature_importance.empty:
        feature_importance = feature_importance.sort_values(["model", "importance"], ascending=[True, False])

    best_model_name, best_reason = select_best(comparison)
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
            "shortage_threshold": SHORTAGE_THRESHOLD,
        },
        output_dir / "best_model.pkl",
    )

    metrics = {
        "best_model": best_model_name,
        "best_reason": best_reason,
        "skipped_models": skipped,
        "row_counts": {
            "train": int(len(train_df)),
            "valid": int(len(valid_df)),
            "test": int(len(test_df)),
            "station_categories": int(len(station_categories)),
        },
        "comparison": comparison.to_dict(orient="records"),
        "by_horizon": by_horizon.to_dict(orient="records"),
    }
    (output_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Best model: {best_model_name}")
    print(best_reason)
    print(comparison.to_string(index=False))


if __name__ == "__main__":
    main()
