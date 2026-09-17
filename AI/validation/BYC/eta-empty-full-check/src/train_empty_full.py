"""BIKE 빈 재고(`p_empty`)/만차(`p_full`) 확률 — 이진분류 검증 (S15P21A104-160 Phase 6).

`predictor_eta.py`가 서빙하는 anchor+horizon 회귀 모델(v4_weather)과 같은 피처·같은
train/valid/test 분할을 쓴다. 새 데이터는 필요 없다 — 패널에 이미 있는
`stock_anchor_hour`(anchor 시점 재고)와 `target_net_flow`(horizon까지 실측 순증감)로
도착 시점 재고(`arrival_stock`)를 계산하고, 거기서 바로 이진 타깃을 유도한다.

    arrival_stock = stock_anchor_hour + target_net_flow
    is_empty = arrival_stock <= 0
    is_full  = arrival_stock >= rack_count   (rack_count는 역 단위 정적값, dataset.load_station_static)

회귀(MAE/RMSE/R²)가 아니라 분류·확률 문제라 logloss·AUC·Brier score(보정)로 판단한다
(AI/CLAUDE.md 규칙은 회귀 비교 조건에 관한 것이고, 여기엔 그대로 적용되지 않는다 —
다만 "동일 조건에서만 비교" 원칙 자체는 그대로 지킨다: v4_weather와 같은 분할·같은 피처).

실행 (스모크):
    cd AI
    python validation/BYC/eta-empty-full-check/src/train_empty_full.py \
        --train-months 202401 202402 --valid-months 202412 --test-months 202507 --tag smoke
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(AI_ROOT))

from app.BIKE.pipeline.calendar import load_holidays  # noqa: E402
from app.BIKE.pipeline.dataset import (  # noqa: E402
    load_paths,
    monthly_paths,
    scan_station_ids,
)
from app.BIKE.pipeline.external_features import attach_weather, load_weather  # noqa: E402
from app.BIKE.pipeline.features import (  # noqa: E402
    BASE_FEATURE_COLS,
    MODEL_FEATURE_COLS_V4_WEATHER,
    TARGET_COL,
    HistoricalProfileBuilder,
    apply_station_code,
    build_station_dtype,
)
from app.BIKE.pipeline.train import _attach_holiday_flag  # noqa: E402

BASE_READ_COLS = ["od_station_id", "date", *BASE_FEATURE_COLS, TARGET_COL]
TRAIN_READ_COLS = [*BASE_READ_COLS, "target_rent_count", "target_return_count"]
RESULTS_PATH = AI_ROOT / "validation" / "BYC" / "eta-empty-full-check" / "RESULTS.md"
# train 첫 달 파일만 훑는 dataset.load_station_static()은 train 이후 신설된 역의
# rack_count가 빠진다(smoke 테스트에서 valid/test 결측이 급증하는 걸로 발견) — 대신
# anchor-horizon-feature-check/src/build_station_master.py가 전체 파일을 훑어 만든
# station_master.parquet(실시간 서빙에도 쓰는 것과 동일 파일)을 쓴다.
STATION_MASTER_PATH = (
    AI_ROOT / "data" / "EXTERNAL" / "station" / "processed" / "station_master.parquet"
)


def attach_rack_count(df: pd.DataFrame, station_static: pd.DataFrame) -> pd.DataFrame:
    merged = df.merge(
        station_static[["od_station_id", "rack_count"]], on="od_station_id", how="left"
    )
    missing = int(merged["rack_count"].isna().sum())
    if missing:
        print(f"  rack_count 결측 {missing:,}행 — 이 행은 is_full 계산에서 제외(NaN 유지)")
    return merged


def attach_empty_full_targets(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    arrival_stock = df["stock_anchor_hour"] + df[TARGET_COL]
    df["is_empty"] = (arrival_stock <= 0).astype(int)
    df["is_full"] = (arrival_stock >= df["rack_count"]).astype(int)
    df.loc[df["rack_count"].isna(), "is_full"] = np.nan
    return df


def make_xy_binary(
    df: pd.DataFrame, target_col: str, feature_cols: list[str] = MODEL_FEATURE_COLS_V4_WEATHER
) -> tuple[pd.DataFrame, pd.Series]:
    rows = df.dropna(subset=[target_col])
    return rows[feature_cols].fillna(0), rows[target_col].astype(int)


def fit_binary(train_df, valid_df, target_col: str, random_state: int = 42):
    from lightgbm import LGBMClassifier, early_stopping, log_evaluation

    x_train, y_train = make_xy_binary(train_df, target_col)
    x_valid, y_valid = make_xy_binary(valid_df, target_col)
    pos_rate = y_train.mean()
    print(f"  [{target_col}] train 양성비율 {pos_rate:.4%} ({int(y_train.sum()):,}/{len(y_train):,})")

    model = LGBMClassifier(
        objective="binary",
        n_estimators=1500,
        learning_rate=0.02,
        num_leaves=127,
        subsample=0.8,
        colsample_bytree=0.8,
        is_unbalance=True,
        n_jobs=-1,
        random_state=random_state,
    )
    t0 = time.time()
    model.fit(
        x_train,
        y_train,
        eval_set=[(x_valid, y_valid)],
        eval_metric="binary_logloss",
        callbacks=[early_stopping(60), log_evaluation(0)],
    )
    return model, time.time() - t0


def evaluate_binary(model, df: pd.DataFrame, label: str, target_col: str) -> dict:
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

    x, y = make_xy_binary(df, target_col)
    proba = model.predict_proba(x)[:, 1]
    pos_rate = float(y.mean())
    result = {
        "split": label,
        "target": target_col,
        "rows": len(df),
        "pos_rate": pos_rate,
        "logloss": float(log_loss(y, proba, labels=[0, 1])),
        "brier": float(brier_score_loss(y, proba)),
    }
    # AUC는 양성/음성이 둘 다 있어야 정의된다 — 한쪽만 있으면(작은 test 조각에서 가능) None.
    result["auc"] = float(roc_auc_score(y, proba)) if y.nunique() == 2 else None
    return result


def run(
    train_months: list[str] | None,
    valid_months: list[str] | None,
    test_months: list[str] | None,
    tag: str,
    random_state: int = 42,
) -> list[dict]:
    train_paths = monthly_paths("train", train_months)
    valid_paths = monthly_paths("valid", valid_months)
    test_paths = monthly_paths("test", test_months)
    holidays = load_holidays()
    station_static = pd.read_parquet(STATION_MASTER_PATH)

    print("[weather] ASOS 로딩...")
    weather = load_weather()

    station_ids = (
        scan_station_ids(train_paths) | scan_station_ids(valid_paths) | scan_station_ids(test_paths)
    )
    station_dtype = build_station_dtype(station_ids)

    def prep(paths: list[Path], label: str, fit_profile: HistoricalProfileBuilder | None):
        read_cols = TRAIN_READ_COLS if fit_profile is None else BASE_READ_COLS
        df = load_paths(paths, read_cols, TARGET_COL)
        df = _attach_holiday_flag(df, holidays)
        df = attach_weather(df, weather, date_col="date", hour_col="hour")
        df = attach_rack_count(df, station_static)
        df = attach_empty_full_targets(df)
        profile = fit_profile or HistoricalProfileBuilder().fit(df)
        df = profile.transform(df)
        apply_station_code(df, station_dtype, label)
        return df, profile

    train_df, profile = prep(train_paths, "train", None)
    valid_df, _ = prep(valid_paths, "valid", profile)

    reports = []
    models = {}
    for target_col in ("is_empty", "is_full"):
        print(f"[{target_col}] 학습...")
        model, train_time_sec = fit_binary(train_df, valid_df, target_col, random_state)
        models[target_col] = model
        r = evaluate_binary(model, valid_df, "valid", target_col)
        r["train_time_sec"] = train_time_sec
        reports.append(r)
        print(f"  valid: {r}")

    del train_df, valid_df

    for p in test_paths:
        test_df, _ = prep([p], f"test:{p.stem}", profile)
        for target_col in ("is_empty", "is_full"):
            r = evaluate_binary(models[target_col], test_df, f"test:{p.stem[-6:]}", target_col)
            reports.append(r)
            print(f"  {r['split']}: {r}")
        del test_df

    return reports


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--train-months", nargs="+", default=None)
    ap.add_argument("--valid-months", nargs="+", default=None)
    ap.add_argument("--test-months", nargs="+", default=None)
    ap.add_argument("--tag", default="smoke")
    ap.add_argument("--random-state", type=int, default=42)
    args = ap.parse_args(argv)
    run(args.train_months, args.valid_months, args.test_months, args.tag, args.random_state)


if __name__ == "__main__":
    main(sys.argv[1:])
