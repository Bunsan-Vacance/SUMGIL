"""6단계(결정 게이트 마무리) — D-1/D-7 lag 포함 피처로 p_empty/p_full까지 avg 대비 확인.

`train_multisource_lightgbm.py`에서 exp_bikes(target_stock)는 이미 avg를 이겼다(MAE 7.217
vs 8.160, RESULTS.md). 근데 서빙 표엔 exp_bikes/p_empty/p_full 셋이 다 있어야 해서, 이제
같은 피처(날씨·공휴일·KBO·D-1/D-7 lag)로 확률 쪼(quantile 0.1/0.5/0.9 + isotonic, B2에서
검증된 방식)도 avg를 이기는지 확인한다.

**avg 쪽 p_empty/p_full**: `StockProfileBaseline`이 이미 station×dow_type×time_slot별로
`is_empty_future`/`is_full_future` 실측 비율을 낸다 — 이게 avg baseline의 확률 예측이다.

로딩·라벨·피처 계산은 `train_multisource_lightgbm.py`를 그대로 재사용한다(같은 계산을 두 번
하지 않음, `AI/CLAUDE.md`) — 파일명에 하이픈이 있는 폴더라 일반 import가 안 돼서
`importlib`로 파일 경로 기준 로딩한다.

실행 (소규모 먼저):
    cd AI
    PYTHONPATH=. PYTHONIOENCODING=utf-8 python validation/BYC/lightgbm-stock-conversion-check/src/train_multisource_quantile.py --train-months 202401 202402 --valid-months 202412 --test-months 202507
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_BASE_PATH = Path(__file__).with_name("train_multisource_lightgbm.py")
_spec = importlib.util.spec_from_file_location("train_multisource_lightgbm", _BASE_PATH)
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

QUANTILES = [0.1, 0.5, 0.9]
Z_90 = 1.2816


def normal_cdf(x, mu, sigma):
    from scipy.stats import norm

    sigma = np.where(sigma <= 1e-6, 1e-6, sigma)
    return norm.cdf(x, loc=mu, scale=sigma)


def fit_avg_probability_baseline(train_df: pd.DataFrame) -> pd.DataFrame:
    """avg 쪽 p_empty/p_full — station×dow_type×time_slot 실측 비율(그대로 서빙 중인 방식)."""
    return (
        train_df.groupby(["od_station_id", "dow_type", "time_slot"])
        .agg(avg_p_empty=("is_empty_future", "mean"), avg_p_full=("is_full_future", "mean"))
        .reset_index()
    )


def brier(p, actual) -> float:
    return float(np.mean((p - actual) ** 2))


def main(argv: list[str] | None = None) -> None:
    from lightgbm import LGBMRegressor, early_stopping, log_evaluation
    from sklearn.isotonic import IsotonicRegression

    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--train-months", nargs="+", required=True)
    ap.add_argument("--valid-months", nargs="+", required=True, help="isotonic 보정기 fit용")
    ap.add_argument("--test-months", nargs="+", required=True)
    ap.add_argument("--n-estimators", type=int, default=500)
    ap.add_argument("--learning-rate", type=float, default=0.05)
    ap.add_argument("--num-leaves", type=int, default=63)
    ap.add_argument("--early-stopping-rounds", type=int, default=60)
    args = ap.parse_args(argv)

    holidays = base.load_holidays()
    print("[quantile] D-1/D-7 lag lookup 생성...")
    lag_lookup = base.build_lag_lookup()

    def prep(months):
        df = base.load_and_prepare(months, holidays)
        df = base.attach_lag(df, lag_lookup, 1, "lag1d_stock")
        df = base.attach_lag(df, lag_lookup, 7, "lag7d_stock")
        return df

    print("[quantile] train/valid/test 로딩...")
    train_df = prep(args.train_months)
    profile = base.fit_station_dow_hour_profile(train_df)
    global_mean = float(train_df["target_stock"].mean())
    train_df = base.attach_profile(train_df, profile, global_mean)
    train_df = base.fill_lag_fallback(train_df)

    valid_df = prep(args.valid_months)
    valid_df = base.attach_profile(valid_df, profile, global_mean)
    valid_df = base.fill_lag_fallback(valid_df)

    test_df = prep(args.test_months)
    test_df = base.attach_profile(test_df, profile, global_mean)
    test_df = base.fill_lag_fallback(test_df)
    print(f"[quantile] train {len(train_df):,} / valid {len(valid_df):,} / test {len(test_df):,}")

    station_dtype = pd.CategoricalDtype(categories=sorted(train_df["od_station_id"].unique()))
    for d in (train_df, valid_df, test_df):
        d["station_code"] = d["od_station_id"].astype(station_dtype).cat.codes

    avg_prob = fit_avg_probability_baseline(train_df)

    x_train = train_df[base.MODEL_FEATURE_COLS].fillna(0)
    y_train = train_df["target_stock"] - train_df["hist_mean"]  # 잔차(mean 회귀와 동일 이유)
    x_valid = valid_df[base.MODEL_FEATURE_COLS].fillna(0)
    y_valid = valid_df["target_stock"] - valid_df["hist_mean"]

    cat_kwargs = {"categorical_feature": ["station_code"]}
    models = {}
    t0 = time.time()
    for q in QUANTILES:
        m = LGBMRegressor(
            objective="quantile",
            alpha=q,
            n_estimators=args.n_estimators,
            learning_rate=args.learning_rate,
            num_leaves=args.num_leaves,
            subsample=0.8,
            colsample_bytree=0.8,
            n_jobs=-1,
            verbose=-1,
        )
        m.fit(
            x_train,
            y_train,
            eval_set=[(x_valid, y_valid)],
            callbacks=[early_stopping(args.early_stopping_rounds), log_evaluation(0)],
            **cat_kwargs,
        )
        models[q] = m
    print(f"[quantile] quantile 3개 학습 {time.time() - t0:.1f}초")

    def predict_quantiles(df):
        x = df[base.MODEL_FEATURE_COLS].fillna(0)
        hist_mean = df["hist_mean"].to_numpy()
        return {q: hist_mean + models[q].predict(x) for q in QUANTILES}

    def raw_probs(df, preds):
        q10, q50, q90 = preds[0.1], preds[0.5], preds[0.9]
        mu, sigma = q50, (q90 - q10) / (2 * Z_90)
        p_empty = normal_cdf(0.0, mu, sigma)
        p_full = 1 - normal_cdf(df["rack_count"].to_numpy(), mu, sigma)
        return p_empty, p_full

    # ── valid에서 isotonic 보정기 fit ──
    p_empty_valid, p_full_valid = raw_probs(valid_df, predict_quantiles(valid_df))
    iso_empty = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso_empty.fit(p_empty_valid, valid_df["is_empty_future"].to_numpy())
    iso_full = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso_full.fit(p_full_valid, valid_df["is_full_future"].to_numpy())

    # ── test(처음 보는 데이터)에서 avg vs model 비교 ──
    p_empty_test, p_full_test = raw_probs(test_df, predict_quantiles(test_df))
    p_empty_cal = iso_empty.predict(p_empty_test)
    p_full_cal = iso_full.predict(p_full_test)

    merged = test_df.merge(avg_prob, on=["od_station_id", "dow_type", "time_slot"], how="left")
    actual_empty = merged["is_empty_future"].to_numpy()
    actual_full = merged["is_full_future"].to_numpy()

    print("\n=== p_empty ===")
    print(
        f"  avg               Brier={brier(merged['avg_p_empty'].fillna(0).to_numpy(), actual_empty):.4f}"
    )
    print(f"  model(보정 전)     Brier={brier(p_empty_test, actual_empty):.4f}")
    print(f"  model(isotonic후) Brier={brier(p_empty_cal, actual_empty):.4f}")

    print("\n=== p_full ===")
    print(
        f"  avg               Brier={brier(merged['avg_p_full'].fillna(0).to_numpy(), actual_full):.4f}"
    )
    print(f"  model(보정 전)     Brier={brier(p_full_test, actual_full):.4f}")
    print(f"  model(isotonic후) Brier={brier(p_full_cal, actual_full):.4f}")


if __name__ == "__main__":
    main(sys.argv[1:])
