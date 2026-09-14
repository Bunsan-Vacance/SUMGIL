"""B2-보정 — quantile 기반 p_empty/p_full에 isotonic regression 사후 보정을 얹었을 때
실제로 calibration이 개선되는지 확인한다.

3-way 분리로 검증한다(보정 자체가 valid에 과적합되지 않았는지 보려면 다른 데이터로 평가해야
함 — 안 그러면 "보정한 데이터로 보정이 잘 맞는지" 확인하는 순환 검증이 된다):

    train(202401)  → quantile(0.1/0.5/0.9) LightGBM 학습
    valid(202412)  → 정규분포 근사로 p_empty_raw/p_full_raw 계산 → isotonic 보정기 fit
    test(202507)   → 같은 보정기를 적용해서, 보정 전/후 calibration이 실제로 나아지는지 확인
                     (여기서 처음 보는 데이터라 "진짜 개선"인지 검증됨)

실행:
    cd AI
    PYTHONPATH=. PYTHONIOENCODING=utf-8 python validation/BYC/lightgbm-stock-conversion-check/src/quantile_isotonic_calibration.py
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from app.BIKE.pipeline.calendar import load_holidays
from app.BIKE.pipeline.dataset import load_paths, monthly_paths, scan_station_ids
from app.BIKE.pipeline.features import (
    BASE_FEATURE_COLS,
    TARGET_COL,
    HistoricalProfileBuilder,
    apply_station_code,
    build_station_dtype,
    make_xy,
)

EXTRA_COLS = ["rack_count"]
READ_COLS = [
    "od_station_id", "date", *BASE_FEATURE_COLS, *EXTRA_COLS,
    TARGET_COL, "target_rent_count", "target_return_count",
]

QUANTILES = [0.1, 0.5, 0.9]
Z_90 = 1.2816
SAMPLE_FRAC = 0.05
N_BINS = 10


def _attach_holiday_flag(df: pd.DataFrame, holidays: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    merged = df.merge(holidays, on="date", how="left")
    merged["is_holiday"] = merged["is_holiday"].fillna(False).astype("int8")
    return merged


def normal_cdf(x, mu, sigma):
    from scipy.stats import norm

    sigma = np.where(sigma <= 1e-6, 1e-6, sigma)
    return norm.cdf(x, loc=mu, scale=sigma)


def raw_probabilities(model_preds: dict, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """quantile 예측 -> (p_empty_raw, p_full_raw, actual_empty, actual_full)."""
    q10, q50, q90 = model_preds[0.1], model_preds[0.5], model_preds[0.9]
    mu, sigma = q50, (q90 - q10) / (2 * Z_90)
    stock_anchor = df["stock_anchor_hour"].to_numpy()
    rack_count = df["rack_count"].to_numpy()
    y_true = df[TARGET_COL].to_numpy()

    p_empty_raw = normal_cdf(-stock_anchor, mu, sigma)
    p_full_raw = 1 - normal_cdf(rack_count - stock_anchor, mu, sigma)

    future_stock_actual = stock_anchor + y_true
    actual_empty = (future_stock_actual <= 0).astype(float)
    actual_full = (future_stock_actual >= rack_count).astype(float)
    return p_empty_raw, p_full_raw, actual_empty, actual_full


def brier_score(p, actual) -> float:
    return float(np.mean((p - actual) ** 2))


def calibration_table(p, actual, n_bins=N_BINS) -> pd.DataFrame:
    bins = pd.qcut(p, n_bins, duplicates="drop")
    df = pd.DataFrame({"bin": bins, "pred": p, "actual": actual})
    return df.groupby("bin", observed=True).agg(
        n=("actual", "size"), mean_pred=("pred", "mean"), actual_rate=("actual", "mean")
    ).reset_index()


def main() -> None:
    from lightgbm import LGBMRegressor
    from sklearn.isotonic import IsotonicRegression

    train_paths = monthly_paths("train", ["202401"])
    valid_paths = monthly_paths("valid", ["202412"])
    test_paths = monthly_paths("test", ["202507"])
    holidays = load_holidays()

    print("[보정] 데이터 로딩(train/valid/test 3-way)...")
    train_df = load_paths(train_paths, READ_COLS, TARGET_COL, sample_frac=SAMPLE_FRAC, random_state=42)
    valid_df = load_paths(valid_paths, READ_COLS, TARGET_COL, sample_frac=SAMPLE_FRAC, random_state=42)
    test_df = load_paths(test_paths, READ_COLS, TARGET_COL, sample_frac=SAMPLE_FRAC, random_state=42)
    train_df = _attach_holiday_flag(train_df, holidays)
    valid_df = _attach_holiday_flag(valid_df, holidays)
    test_df = _attach_holiday_flag(test_df, holidays)

    profile = HistoricalProfileBuilder().fit(train_df)  # train만으로 fit — leakage 방지
    train_df = profile.transform(train_df)
    valid_df = profile.transform(valid_df)
    test_df = profile.transform(test_df)

    station_ids = scan_station_ids(train_paths) | scan_station_ids(valid_paths) | scan_station_ids(test_paths)
    dtype = build_station_dtype(station_ids)
    apply_station_code(train_df, dtype, "train")
    apply_station_code(valid_df, dtype, "valid")
    apply_station_code(test_df, dtype, "test")

    # stock_anchor_hour가 없는 행(소수)은 확률 계산 자체가 불가능하다 — 채우지 않고 제외한다(원칙 8).
    for name, df in (("valid", valid_df), ("test", test_df)):
        before = len(df)
        df.dropna(subset=["stock_anchor_hour"], inplace=True)
        df.reset_index(drop=True, inplace=True)
        if before != len(df):
            print(f"  {name}: stock_anchor_hour 결측 {before - len(df)}행 제외")

    x_train, y_train = make_xy(train_df)
    print(f"[보정] train {len(x_train):,}행, valid {len(valid_df):,}행, test {len(test_df):,}행")

    t0 = time.time()
    models = {}
    for q in QUANTILES:
        m = LGBMRegressor(
            objective="quantile", alpha=q, n_estimators=300, learning_rate=0.05,
            num_leaves=63, n_jobs=-1, verbose=-1,
        )
        m.fit(x_train, y_train)
        models[q] = m
    print(f"[보정] quantile 3개 학습 {time.time() - t0:.1f}초")

    def predict_all(df):
        x, _ = make_xy(df)
        return {q: models[q].predict(x) for q in QUANTILES}

    # ── valid에서 raw 확률 계산 + isotonic 보정기 fit ──
    valid_preds = predict_all(valid_df)
    p_empty_raw_valid, p_full_raw_valid, actual_empty_valid, actual_full_valid = raw_probabilities(
        valid_preds, valid_df
    )
    iso_empty = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso_empty.fit(p_empty_raw_valid, actual_empty_valid)
    iso_full = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso_full.fit(p_full_raw_valid, actual_full_valid)

    # ── test(처음 보는 데이터)에서 보정 전/후 비교 ──
    test_preds = predict_all(test_df)
    p_empty_raw_test, p_full_raw_test, actual_empty_test, actual_full_test = raw_probabilities(
        test_preds, test_df
    )
    p_empty_cal_test = iso_empty.predict(p_empty_raw_test)
    p_full_cal_test = iso_full.predict(p_full_raw_test)

    print("\n=== test(2025-07, 처음 보는 데이터)에서 평가 ===")
    print(
        f"[p_empty] 실측 발생률 {actual_empty_test.mean():.3f} | "
        f"보정 전 Brier={brier_score(p_empty_raw_test, actual_empty_test):.4f} "
        f"(평균예측 {p_empty_raw_test.mean():.3f}) -> "
        f"보정 후 Brier={brier_score(p_empty_cal_test, actual_empty_test):.4f} "
        f"(평균예측 {p_empty_cal_test.mean():.3f})"
    )
    print(
        f"[p_full]  실측 발생률 {actual_full_test.mean():.3f} | "
        f"보정 전 Brier={brier_score(p_full_raw_test, actual_full_test):.4f} "
        f"(평균예측 {p_full_raw_test.mean():.3f}) -> "
        f"보정 후 Brier={brier_score(p_full_cal_test, actual_full_test):.4f} "
        f"(평균예측 {p_full_cal_test.mean():.3f})"
    )

    print("\n[p_empty 보정 후 calibration table]")
    print(calibration_table(p_empty_cal_test, actual_empty_test).to_string(index=False))
    print("\n[p_full 보정 후 calibration table]")
    print(calibration_table(p_full_cal_test, actual_full_test).to_string(index=False))


if __name__ == "__main__":
    main()
