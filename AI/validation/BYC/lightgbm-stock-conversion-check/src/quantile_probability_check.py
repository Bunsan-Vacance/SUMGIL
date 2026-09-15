"""B2 — "anchor(현재 재고)를 안다"고 가정한 상태에서, quantile(0.1/0.5/0.9) 예측으로 만든
p_empty/p_full이 실측과 맞는지(calibration)만 순수하게 확인한다.

A1(anchor를 어떻게 만들지)은 안 건드린다 — 여기서는 실제 데이터에 있는 진짜
`stock_anchor_hour`를 그대로 쓴다. 그래야 "확률 변환 공식 자체가 맞는가"만 따로 볼 수 있다
(B1/B2/A1 관계는 `validation/BYC/lightgbm-stock-conversion-check/`의 상위 계획 참고).

## 확률 변환 방법 (1차 시도 — 정규분포 근사)

quantile 3개(q10/q50/q90)만으로는 완전한 분포를 못 그리므로, 1차로 정규분포를 가정해서
q10·q90으로 표준편차를, q50으로 평균을 역산한다:

    mu    = q50
    sigma = (q90 - q10) / (2 * 1.2816)   (z_0.9 = 1.2816)

미래 재고(future_stock) = stock_anchor_hour + target_net_flow 이므로:

    p_empty = P(future_stock <= 0)         = CDF(-stock_anchor_hour; mu, sigma)
    p_full  = P(future_stock >= rack_count) = 1 - CDF(rack_count - stock_anchor_hour; mu, sigma)

## 실측(ground truth)

target_net_flow가 이미 "실제 대여·반납 이벤트로 관측된 순증감"이므로,
future_stock_actual = stock_anchor_hour + target_net_flow 를 실측으로 쓴다(근사가 아니라
정의상 정확한 값 — 원본에 별도 미래 재고 컬럼은 없음).

실행:
    cd AI
    PYTHONPATH=. python validation/BYC/lightgbm-stock-conversion-check/src/quantile_probability_check.py
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

EXTRA_COLS = ["rack_count"]  # stock_anchor_hour는 BASE_FEATURE_COLS에 이미 있음
READ_COLS = [
    "od_station_id",
    "date",
    *BASE_FEATURE_COLS,
    *EXTRA_COLS,
    TARGET_COL,
    "target_rent_count",
    "target_return_count",
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
    sigma = np.where(sigma <= 1e-6, 1e-6, sigma)  # 0분산 방지
    from scipy.stats import norm

    return norm.cdf(x, loc=mu, scale=sigma)


def calibration_table(
    predicted_p: np.ndarray, actual: np.ndarray, n_bins: int = N_BINS
) -> pd.DataFrame:
    """예측 확률을 n_bins개 구간으로 나눠, 구간별 평균 예측확률 vs 실제 발생률을 비교한다."""
    bins = pd.qcut(predicted_p, n_bins, duplicates="drop")
    df = pd.DataFrame({"bin": bins, "pred": predicted_p, "actual": actual})
    table = df.groupby("bin", observed=True).agg(
        n=("actual", "size"), mean_pred=("pred", "mean"), actual_rate=("actual", "mean")
    )
    return table.reset_index()


def brier_score(predicted_p: np.ndarray, actual: np.ndarray) -> float:
    return float(np.mean((predicted_p - actual) ** 2))


def main() -> None:
    from lightgbm import LGBMRegressor

    train_paths = monthly_paths("train", ["202401"])
    valid_paths = monthly_paths("valid", ["202412"])
    holidays = load_holidays()

    print("[B2] 데이터 로딩...")
    train_df = load_paths(
        train_paths, READ_COLS, TARGET_COL, sample_frac=SAMPLE_FRAC, random_state=42
    )
    valid_df = load_paths(
        valid_paths, READ_COLS, TARGET_COL, sample_frac=SAMPLE_FRAC, random_state=42
    )
    train_df = _attach_holiday_flag(train_df, holidays)
    valid_df = _attach_holiday_flag(valid_df, holidays)

    profile = HistoricalProfileBuilder().fit(train_df)
    train_df = profile.transform(train_df)
    valid_df = profile.transform(valid_df)

    station_ids = scan_station_ids(train_paths) | scan_station_ids(valid_paths)
    dtype = build_station_dtype(station_ids)
    apply_station_code(train_df, dtype, "train")
    apply_station_code(valid_df, dtype, "valid")

    x_train, y_train = make_xy(train_df)
    x_valid, y_valid = make_xy(valid_df)
    print(f"[B2] train {len(x_train):,}행, valid {len(x_valid):,}행")

    preds = {}
    t0 = time.time()
    for q in QUANTILES:
        model = LGBMRegressor(
            objective="quantile",
            alpha=q,
            n_estimators=300,
            learning_rate=0.05,
            num_leaves=63,
            n_jobs=-1,
            verbose=-1,
        )
        model.fit(x_train, y_train)
        preds[q] = model.predict(x_valid)
    print(f"[B2] quantile 3개 학습 {time.time() - t0:.1f}초")

    q10, q50, q90 = preds[0.1], preds[0.5], preds[0.9]

    # ── ① quantile 자체의 coverage 확인 (empty/full과 무관한 기본 sanity check) ──
    y_true = y_valid.to_numpy()
    cov10 = float((y_true <= q10).mean())
    cov50 = float((y_true <= q50).mean())
    cov90 = float((y_true <= q90).mean())
    print(
        f"[B2] coverage — q10 목표 10% 실제 {cov10:.1%} / q50 목표 50% 실제 {cov50:.1%} / "
        f"q90 목표 90% 실제 {cov90:.1%}"
    )

    # ── ② 정규분포 근사로 p_empty/p_full 계산 ──
    mu = q50
    sigma = (q90 - q10) / (2 * Z_90)
    stock_anchor = valid_df["stock_anchor_hour"].to_numpy()
    rack_count = valid_df["rack_count"].to_numpy()

    p_empty_pred = normal_cdf(-stock_anchor, mu, sigma)
    p_full_pred = 1 - normal_cdf(rack_count - stock_anchor, mu, sigma)

    # ── 실측: future_stock = anchor + 실제 net_flow ──
    future_stock_actual = stock_anchor + y_true
    actual_empty = (future_stock_actual <= 0).astype(float)
    actual_full = (future_stock_actual >= rack_count).astype(float)

    print(
        f"\n[B2] p_empty — 평균 예측 {p_empty_pred.mean():.3f} vs 실측 발생률 {actual_empty.mean():.3f}, "
        f"Brier={brier_score(p_empty_pred, actual_empty):.4f}"
    )
    print(calibration_table(p_empty_pred, actual_empty).to_string(index=False))

    print(
        f"\n[B2] p_full — 평균 예측 {p_full_pred.mean():.3f} vs 실측 발생률 {actual_full.mean():.3f}, "
        f"Brier={brier_score(p_full_pred, actual_full):.4f}"
    )
    print(calibration_table(p_full_pred, actual_full).to_string(index=False))


if __name__ == "__main__":
    main()
