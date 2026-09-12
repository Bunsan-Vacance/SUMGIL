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
    parser.add_argument("--train-path", nargs="+", help="train CSV 경로. 여러 개 지정하면 순서대로 합쳐 읽는다.")
    parser.add_argument("--valid-path", nargs="+", help="valid CSV 경로. 지정하면 --data-dir/--file-tag보다 우선한다.")
    parser.add_argument("--test-path", nargs="+", help="test CSV 경로. 지정하면 --data-dir/--file-tag보다 우선한다.")
    parser.add_argument("--rf-max-rows", type=int, default=2_000_000)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument(
        "--file-tag",
        default="top300",
        help="파일명 접미사 (예: top300, stratified300) — {split}_netflow_q3_mapped_{tag}.csv.gz",
    )
    return parser.parse_args()


def resolve_split_path(args: argparse.Namespace, split: str) -> list[Path]:
    explicit = getattr(args, f"{split}_path", None)
    if explicit:
        return [Path(path) for path in explicit]
    return [Path(args.data_dir) / f"{split}_netflow_q3_mapped_{args.file_tag}.csv.gz"]


def downcast_memory(df: pd.DataFrame) -> pd.DataFrame:
    """메모리 절감 — float64->float32, int64는 저정밀 정수로 다운캐스트.

    Phase 2.5(10-horizon, 스케일 큰 train/valid/test)에서 phase2 스크립트가
    historical profile merge 도중 메모리 부족으로 강제 종료되는 문제 때문에 추가함.
    """
    for col in df.columns:
        if df[col].dtype == "float64":
            df[col] = df[col].astype("float32")
        elif df[col].dtype == "int64":
            df[col] = pd.to_numeric(df[col], downcast="integer")
    return df


def read_split(
    data_dir: Path, split: str, file_tag: str = "top300", path: Path | list[Path] | None = None
) -> pd.DataFrame:
    paths = path or [data_dir / f"{split}_netflow_q3_mapped_{file_tag}.csv.gz"]
    if isinstance(paths, Path):
        paths = [paths]
    usecols = ["od_station_id", *FEATURE_COLS, TARGET_COL]
    # pyarrow 엔진 — chunksize 없는 전체 로드에서만 사용 가능(청크 읽기와는 비호환).
    # gzip CSV 파싱이 병목이라 여기서 속도 이득이 큼.
    df = pd.concat((pd.read_csv(p, usecols=usecols, engine="pyarrow") for p in paths), ignore_index=True)
    df["od_station_id"] = df["od_station_id"].astype(str)
    return downcast_memory(df)


def build_station_dtype(*sources: pd.DataFrame | set[str]) -> pd.CategoricalDtype:
    """DataFrame과 station id set을 섞어서 받아 합집합으로 dtype을 만든다.

    큰 파일(test 등)은 DataFrame 전체 대신 scan_station_ids()로 뽑은 set을 넘기면
    전체를 메모리에 올리지 않고도 dtype 구성 범위에 포함시킬 수 있다.
    """
    ids: set[str] = set()
    for src in sources:
        if isinstance(src, pd.DataFrame):
            ids |= set(src["od_station_id"])
        else:
            ids |= set(src)
    return pd.CategoricalDtype(categories=sorted(ids))


def apply_station_code(df: pd.DataFrame, dtype: pd.CategoricalDtype, label: str = "df") -> pd.DataFrame:
    codes = df["od_station_id"].astype(dtype).cat.codes
    unknown = int((codes == -1).sum())
    assert unknown == 0, f"{label}: station_code 매핑 안 된 station {unknown}건 — dtype 구성 범위 확인 필요"
    df["station_code"] = codes
    return df


def add_station_code(
    train: pd.DataFrame, valid: pd.DataFrame, test: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    dtype = build_station_dtype(train, valid, test)
    for df, label in ((train, "train"), (valid, "valid"), (test, "test")):
        apply_station_code(df, dtype, label)
    return train, valid, test, list(dtype.categories)


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
        # GPU(device="cuda") 비활성화 — 06m(121M행, feature matrix 약 9.7GB)에서
        # VRAM(6GB) 초과로 GPU<->CPU thrashing 발생, 학습시간이 15배(159s->2449s)로
        # 폭증하는 걸 실측 확인함. 09m/12m은 더 커서 위험이 더 큼 — CPU로 되돌림.
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


CHUNK_SIZE = 2_000_000


class ChunkedMetricAccumulator:
    """test를 청크 단위로 순회하며 지표를 계산하기 위한 누적기.

    Phase 2.5(10-horizon, test 최대 7,900만행)에서 test 전체를 한 번에 메모리에
    올리다가 스왑 thrashing으로 5시간 넘게 멈추는 문제가 있어서 도입했다.
    MAE/RMSE/WAPE/R²/direction/decrease/shortage 전부 sufficient statistics로
    누적 가능한 형태라, 청크로 나눠 계산해도 전체를 한 번에 계산한 것과
    수학적으로 동일한 결과가 나온다(근사 아님).
    """

    def __init__(self) -> None:
        self.n = 0
        self.sum_abs_err = 0.0
        self.sum_sq_err = 0.0
        self.sum_y = 0.0
        self.sum_y2 = 0.0
        self.sum_abs_y = 0.0
        self.dir_counts: dict[tuple[str, str], int] = {}
        self.decrease_tp = self.decrease_fp = self.decrease_fn = 0
        self.shortage_tp = self.shortage_fp = self.shortage_fn = 0
        self.infer_time_sec = 0.0

    def update(self, y_true: np.ndarray, y_pred: np.ndarray, stock_anchor: np.ndarray, infer_time_sec: float) -> None:
        if len(y_true) == 0:
            return
        err = y_true - y_pred
        self.n += len(y_true)
        self.sum_abs_err += float(np.sum(np.abs(err)))
        self.sum_sq_err += float(np.sum(err**2))
        self.sum_y += float(np.sum(y_true))
        self.sum_y2 += float(np.sum(y_true**2))
        self.sum_abs_y += float(np.sum(np.abs(y_true)))
        self.infer_time_sec += infer_time_sec

        true_c = direction_class(y_true)
        pred_c = direction_class(y_pred)
        for tc, pc in zip(true_c, pred_c):
            key = (tc, pc)
            self.dir_counts[key] = self.dir_counts.get(key, 0) + 1

        true_dec = y_true < 0
        pred_dec = y_pred < 0
        self.decrease_tp += int(np.sum(true_dec & pred_dec))
        self.decrease_fp += int(np.sum(~true_dec & pred_dec))
        self.decrease_fn += int(np.sum(true_dec & ~pred_dec))

        true_stock = stock_anchor + y_true
        pred_stock = stock_anchor + y_pred
        true_short = true_stock <= SHORTAGE_THRESHOLD
        pred_short = pred_stock <= SHORTAGE_THRESHOLD
        self.shortage_tp += int(np.sum(true_short & pred_short))
        self.shortage_fp += int(np.sum(pred_short & ~true_short))
        self.shortage_fn += int(np.sum(~pred_short & true_short))

    @staticmethod
    def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return precision, recall, f1

    def finalize(self, model_name: str, train_time_sec: float) -> dict[str, Any]:
        mae = self.sum_abs_err / self.n if self.n else float("nan")
        rmse = math.sqrt(self.sum_sq_err / self.n) if self.n else float("nan")
        wape = self.sum_abs_err / self.sum_abs_y if self.sum_abs_y else float("nan")
        ss_tot = self.sum_y2 - (self.sum_y**2) / self.n if self.n else 0.0
        r2 = 1 - self.sum_sq_err / ss_tot if ss_tot else float("nan")

        labels = ["decrease", "stable", "increase"]
        correct = sum(self.dir_counts.get((c, c), 0) for c in labels)
        direction_accuracy = correct / self.n if self.n else float("nan")
        f1s = []
        for c in labels:
            tp = self.dir_counts.get((c, c), 0)
            fp = sum(v for (t, p), v in self.dir_counts.items() if p == c and t != c)
            fn = sum(v for (t, p), v in self.dir_counts.items() if t == c and p != c)
            f1s.append(self._prf(tp, fp, fn)[2])
        direction_macro_f1 = float(np.mean(f1s))

        decrease_precision, decrease_recall, decrease_f1 = self._prf(self.decrease_tp, self.decrease_fp, self.decrease_fn)
        shortage_precision, shortage_recall, shortage_f1 = self._prf(self.shortage_tp, self.shortage_fp, self.shortage_fn)

        return {
            "model": model_name,
            "mae": mae,
            "rmse": rmse,
            "wape": wape,
            "r2": r2,
            "direction_accuracy": direction_accuracy,
            "direction_macro_f1": direction_macro_f1,
            "train_time_sec": train_time_sec,
            "infer_time_sec": self.infer_time_sec,
            "infer_rows_per_sec": self.n / self.infer_time_sec if self.infer_time_sec > 0 else float("inf"),
            "decrease_precision": decrease_precision,
            "decrease_recall": decrease_recall,
            "decrease_f1": decrease_f1,
            "shortage_precision": shortage_precision,
            "shortage_recall": shortage_recall,
            "shortage_f1": shortage_f1,
        }


def iter_csv_chunks(paths: list[Path], usecols: list[str], chunk_size: int = CHUNK_SIZE):
    for p in paths:
        for chunk in pd.read_csv(p, usecols=usecols, chunksize=chunk_size):
            yield chunk


def scan_station_ids(paths: list[Path], chunk_size: int = CHUNK_SIZE) -> set[str]:
    """od_station_id 컬럼만 청크로 훑어서 고유 station id 집합을 반환한다.

    train∪valid만으로 station dtype을 만들면 stratified300처럼 train/valid 기간에
    등장하지 않는 station이 test에만 있는 경우 apply_station_code()가 unknown으로
    실패한다(top300은 Phase 0에서 train=valid=test station 집합 동일이 확인됐지만,
    stratified300은 그 전제가 깨짐 — 06m/stratified300 이전 단계에서 실측 확인됨).
    test 전체를 메모리에 올리지 않고도 dtype 구성 범위를 test까지 포함하도록 이 함수로
    1개 컬럼만 청크 스캔한다.
    """
    ids: set[str] = set()
    for chunk in iter_csv_chunks(paths, ["od_station_id"], chunk_size):
        ids |= set(chunk["od_station_id"].astype(str))
    return ids


def evaluate_test_chunked(
    fit_results: list[FitResult],
    test_paths: list[Path],
    usecols: list[str],
    station_dtype: pd.CategoricalDtype,
    transform_fn=lambda df: df,
    chunk_size: int = CHUNK_SIZE,
    tally_col: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[Any, int]]:
    """test를 청크로 순회하며 comparison/by_horizon을 한 번에 계산한다.

    기존 evaluate_model+evaluate_by_horizon을 test 전체 로드 없이 대체한다.
    predict()도 청크당 1회만 호출하고 horizon별로는 배열을 슬라이싱만 해서
    (원래 evaluate_by_horizon처럼 horizon마다 다시 predict하지 않음) 오히려
    더 효율적이다.
    """
    active = [r for r in fit_results if not r.skipped_reason]
    accs = {r.name: ChunkedMetricAccumulator() for r in active}
    accs_by_horizon: dict[str, dict[int, ChunkedMetricAccumulator]] = {r.name: {} for r in active}

    tally: dict[Any, int] = {}
    n_seen = 0
    for chunk in iter_csv_chunks(test_paths, usecols, chunk_size):
        chunk["od_station_id"] = chunk["od_station_id"].astype(str)
        chunk = downcast_memory(chunk)
        apply_station_code(chunk, station_dtype, "test-chunk")
        chunk = transform_fn(chunk)

        if tally_col is not None:
            for k, v in chunk[tally_col].value_counts().items():
                tally[k] = tally.get(k, 0) + int(v)

        y_true = chunk[TARGET_COL].fillna(0).to_numpy()
        stock_anchor = chunk["stock_anchor_hour"].fillna(0).to_numpy()
        horizon_values = chunk["horizon_min"].to_numpy()
        n_seen += len(chunk)

        for result in active:
            started = time.perf_counter()
            pred = predict_model(result.model, chunk)
            infer_time = time.perf_counter() - started
            accs[result.name].update(y_true, pred, stock_anchor, infer_time)
            for h in np.unique(horizon_values):
                mask = horizon_values == h
                bucket = accs_by_horizon[result.name].setdefault(int(h), ChunkedMetricAccumulator())
                bucket.update(y_true[mask], pred[mask], stock_anchor[mask], 0.0)
        del chunk
    print(f"  (chunked eval: 총 {n_seen:,}행 처리)")

    comparison = pd.DataFrame([accs[r.name].finalize(r.name, r.train_time_sec) for r in active]).sort_values("mae")
    horizon_rows = []
    for r in active:
        for h, acc in sorted(accs_by_horizon[r.name].items()):
            row = acc.finalize(r.name, r.train_time_sec)
            row["horizon_min"] = h
            horizon_rows.append(row)
    by_horizon = pd.DataFrame(horizon_rows).sort_values(["horizon_min", "mae"])
    return comparison, by_horizon, tally


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
