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
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

FEATURE_COLS = [
    "horizon_min",
    "current_stock",
    "capacity_proxy",
    "stock_ratio_proxy",
    "rent_count_5m",
    "return_count_5m",
    "net_delta_5m",
    "rent_recent_15m",
    "return_recent_15m",
    "net_recent_15m",
    "net_recent_30m",
    "net_recent_60m",
    "stock_delta_prev_5m",
    "stock_delta_prev_15m",
    "stock_delta_prev_60m",
    "hour",
    "minute",
    "day_of_week",
    "is_weekend",
]
MODEL_FEATURE_COLS = FEATURE_COLS + ["station_code"]
TARGET_COL = "target_delta"
SHORTAGE_THRESHOLD = 2
HORIZONS = [5, 10, 15, 30]


@dataclass
class FitResult:
    name: str
    model: Any
    train_time_sec: float
    skipped_reason: str | None = None


class NaiveTrendModel:
    def __init__(self, window_min: int, source_col: str) -> None:
        self.window_min = window_min
        self.source_col = source_col

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return (frame[self.source_col].fillna(0).to_numpy() / self.window_min) * frame[
            "horizon_min"
        ].fillna(0).to_numpy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train and compare 5-minute stock delta baselines."
    )
    parser.add_argument(
        "--data-dir", required=True, help="Directory containing train/valid/test CSV files."
    )
    default_output_dir = Path(__file__).resolve().parents[1] / "outputs"
    parser.add_argument("--output-dir", default=str(default_output_dir))
    parser.add_argument("--sample-frac", type=float, default=1.0)
    parser.add_argument("--rf-max-rows", type=int, default=1_000_000)
    parser.add_argument("--random-state", type=int, default=42)
    return parser.parse_args()


def read_split(data_dir: Path, split: str) -> pd.DataFrame:
    path = data_dir / f"{split}_202509_top200.csv.gz"
    usecols = ["station_id", *FEATURE_COLS, TARGET_COL, "target_stock"]
    df = pd.read_csv(path, usecols=usecols)
    df["station_id"] = df["station_id"].astype(str)
    return df


def add_station_code(
    train: pd.DataFrame, valid: pd.DataFrame, test: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    categories = sorted(
        set(train["station_id"].dropna().astype(str))
        | set(valid["station_id"].dropna().astype(str))
        | set(test["station_id"].dropna().astype(str))
    )
    dtype = pd.CategoricalDtype(categories=categories)
    for df in (train, valid, test):
        df["station_code"] = df["station_id"].astype(str).astype(dtype).cat.codes
    return train, valid, test, categories


def make_xy(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    return df[MODEL_FEATURE_COLS].fillna(0), df[TARGET_COL].fillna(0)


def maybe_sample_train(df: pd.DataFrame, sample_frac: float, random_state: int) -> pd.DataFrame:
    if not 0 < sample_frac <= 1:
        raise ValueError("--sample-frac must be in the range (0, 1].")
    if sample_frac == 1.0:
        return df
    return df.sample(frac=sample_frac, random_state=random_state).sort_index()


def fit_random_forest(train_df: pd.DataFrame, rf_max_rows: int, random_state: int) -> FitResult:
    if len(train_df) > rf_max_rows:
        fit_df = train_df.sample(n=rf_max_rows, random_state=random_state)
    else:
        fit_df = train_df

    x_train, y_train = make_xy(fit_df)
    model = RandomForestRegressor(
        n_estimators=150,
        max_depth=18,
        min_samples_leaf=3,
        n_jobs=-1,
        random_state=random_state,
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
        model.fit(
            x_train,
            y_train,
            eval_set=[(x_valid, y_valid)],
            verbose=False,
            early_stopping_rounds=30,
        )
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


def rmse(y_true: np.ndarray | pd.Series, y_pred: np.ndarray) -> float:
    return math.sqrt(mean_squared_error(y_true, y_pred))


def shortage_metrics(pred_stock: np.ndarray, true_stock: pd.Series) -> dict[str, float]:
    pred_shortage = pred_stock <= SHORTAGE_THRESHOLD
    true_shortage = true_stock.to_numpy() <= SHORTAGE_THRESHOLD

    tp = int(np.logical_and(pred_shortage, true_shortage).sum())
    fp = int(np.logical_and(pred_shortage, ~true_shortage).sum())
    fn = int(np.logical_and(~pred_shortage, true_shortage).sum())

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "shortage_precision": precision,
        "shortage_recall": recall,
        "shortage_f1": f1,
    }


def evaluate_predictions(
    model_name: str,
    df: pd.DataFrame,
    pred_delta: np.ndarray,
    train_time_sec: float,
    infer_time_sec: float,
) -> dict[str, float | str]:
    true_delta = df[TARGET_COL].fillna(0)
    pred_stock = df["current_stock"].fillna(0).to_numpy() + pred_delta
    true_stock = df["target_stock"].fillna(0)

    metrics: dict[str, float | str] = {
        "model": model_name,
        "mae_delta": mean_absolute_error(true_delta, pred_delta),
        "rmse_delta": rmse(true_delta, pred_delta),
        "r2_delta": r2_score(true_delta, pred_delta),
        "mae_stock": mean_absolute_error(true_stock, pred_stock),
        "rmse_stock": rmse(true_stock, pred_stock),
        "train_time_sec": train_time_sec,
        "infer_time_sec": infer_time_sec,
        "infer_rows_per_sec": len(df) / infer_time_sec if infer_time_sec > 0 else float("inf"),
    }
    metrics.update(shortage_metrics(pred_stock, true_stock))
    return metrics


def predict_model(model: Any, df: pd.DataFrame) -> np.ndarray:
    if isinstance(model, NaiveTrendModel):
        return model.predict(df)
    x, _ = make_xy(df)
    return model.predict(x)


def evaluate_model(
    model_name: str, model: Any, df: pd.DataFrame, train_time_sec: float
) -> dict[str, Any]:
    started_at = time.perf_counter()
    pred_delta = predict_model(model, df)
    infer_time_sec = time.perf_counter() - started_at
    return evaluate_predictions(model_name, df, pred_delta, train_time_sec, infer_time_sec)


def evaluate_by_horizon(
    model_name: str, model: Any, test_df: pd.DataFrame, train_time_sec: float
) -> list[dict[str, Any]]:
    rows = []
    for horizon in HORIZONS:
        horizon_df = test_df[test_df["horizon_min"] == horizon]
        if horizon_df.empty:
            continue
        metrics = evaluate_model(model_name, model, horizon_df, train_time_sec)
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
    naive_best = comparison[comparison["model"].str.startswith("Naive_")]["mae_stock"].min()
    eligible = comparison[
        (~comparison["model"].str.startswith("Naive_")) & (comparison["mae_stock"] < naive_best)
    ].copy()

    if eligible.empty:
        fallback = comparison.sort_values(
            ["mae_stock", "shortage_recall", "infer_time_sec"],
            ascending=[True, False, True],
        ).iloc[0]
        return (
            str(fallback["model"]),
            "No ML model beat the best naive baseline; saved best overall.",
        )

    eligible["mae_rank_key"] = eligible["mae_stock"].round(4)
    best = eligible.sort_values(
        ["mae_rank_key", "shortage_recall", "infer_time_sec"],
        ascending=[True, False, True],
    ).iloc[0]
    return str(best["model"]), "Selected best ML model that beat the best naive baseline."


def save_schema(output_dir: Path, station_categories: list[str], best_model_name: str) -> None:
    schema = {
        "feature_cols": FEATURE_COLS,
        "model_feature_cols": MODEL_FEATURE_COLS,
        "target_col": TARGET_COL,
        "station_categories": station_categories,
        "station_code_unknown": -1,
        "best_model_name": best_model_name,
        "prediction_formula": "predicted_stock = realtime_current_stock + predicted_delta",
        "shortage_threshold": SHORTAGE_THRESHOLD,
    }
    (output_dir / "feature_schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Loading train/valid/test splits...")
    train_df = read_split(data_dir, "train")
    valid_df = read_split(data_dir, "valid")
    test_df = read_split(data_dir, "test")
    train_df, valid_df, test_df, station_categories = add_station_code(train_df, valid_df, test_df)
    train_df = maybe_sample_train(train_df, args.sample_frac, args.random_state)

    print(
        f"Rows: train={len(train_df):,}, valid={len(valid_df):,}, test={len(test_df):,}, "
        f"stations={len(station_categories):,}"
    )

    fit_results: list[FitResult] = [
        FitResult("Naive_15m_trend", NaiveTrendModel(15, "net_recent_15m"), 0.0),
        FitResult("Naive_60m_trend", NaiveTrendModel(60, "net_recent_60m"), 0.0),
    ]

    print("Training RandomForest...")
    fit_results.append(fit_random_forest(train_df, args.rf_max_rows, args.random_state))

    print("Training XGBoost if available...")
    fit_results.append(fit_xgboost(train_df, valid_df, args.random_state))

    print("Training LightGBM if available...")
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
        print(f"Evaluating {result.name}...")
        fitted_models[result.name] = result.model
        comparison_rows.append(
            evaluate_model(result.name, result.model, test_df, result.train_time_sec)
        )
        horizon_rows.extend(
            evaluate_by_horizon(result.name, result.model, test_df, result.train_time_sec)
        )
        importance_rows.extend(feature_importance_rows(result.name, result.model))

    comparison = pd.DataFrame(comparison_rows).sort_values("mae_stock")
    by_horizon = pd.DataFrame(horizon_rows).sort_values(["horizon_min", "mae_stock"])
    feature_importance = pd.DataFrame(importance_rows)
    if not feature_importance.empty:
        feature_importance = feature_importance.sort_values(
            ["model", "importance"], ascending=[True, False]
        )

    best_model_name, best_reason = select_best(comparison)
    best_model = fitted_models[best_model_name]

    comparison.to_csv(output_dir / "model_comparison.csv", index=False)
    by_horizon.to_csv(output_dir / "model_comparison_by_horizon.csv", index=False)
    feature_importance.to_csv(output_dir / "feature_importance.csv", index=False)
    save_schema(output_dir, station_categories, best_model_name)
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
            "train": len(train_df),
            "valid": len(valid_df),
            "test": len(test_df),
            "station_categories": len(station_categories),
        },
        "comparison": comparison.to_dict(orient="records"),
        "by_horizon": by_horizon.to_dict(orient="records"),
    }
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Best model: {best_model_name}")
    print(best_reason)
    print(comparison.to_string(index=False))


if __name__ == "__main__":
    main()
