"""B1 — quantile LightGBM 학습이 실제로 되는지, 시간이 얼마나 드는지 소규모로 먼저 찍어본다.

A2(확률 산출) 3안 채택: net_flow의 quantile(0.1/0.5/0.9)을 각각 LightGBM으로 학습해서,
그 분포로 p_empty/p_full을 근사한다. 전체 스케일로 바로 안 가고(`AI/CLAUDE.md` 원칙),
1개월·작은 sample_frac으로 먼저 "① 학습이 되는가 ② quantile 순서가 지켜지는가
(q10<=q50<=q90) ③ 시간이 얼마나 드는가"만 확인한다.

app/BIKE/pipeline(이미 승격된 코드)을 그대로 재사용한다 — validation은 app을 import해도 되고
(app은 validation을 import 안 함, AI/CLAUDE.md 디렉터리 규약), 같은 계산을 두 번 만들지 않기 위해서다.

실행:
    cd AI
    python validation/BYC/lightgbm-stock-conversion-check/src/quantile_feasibility.py
"""

from __future__ import annotations

import time

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

READ_COLS = ["od_station_id", "date", *BASE_FEATURE_COLS, TARGET_COL, "target_rent_count", "target_return_count"]

QUANTILES = [0.1, 0.5, 0.9]
SAMPLE_FRAC = 0.05  # 소규모 — 1개월치의 5%


def _attach_holiday_flag(df, holidays):
    import pandas as pd

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    merged = df.merge(holidays, on="date", how="left")
    merged["is_holiday"] = merged["is_holiday"].fillna(False).astype("int8")
    return merged


def main() -> None:
    from lightgbm import LGBMRegressor

    train_paths = monthly_paths("train", ["202401"])  # 1개월만
    valid_paths = monthly_paths("valid", ["202412"])
    holidays = load_holidays()

    print(f"[B1] train 1개월, sample_frac={SAMPLE_FRAC} 로 로딩...")
    train_df = load_paths(train_paths, READ_COLS, TARGET_COL, sample_frac=SAMPLE_FRAC, random_state=42)
    valid_df = load_paths(valid_paths, READ_COLS, TARGET_COL, sample_frac=SAMPLE_FRAC, random_state=42)
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
    print(f"[B1] train {len(x_train):,}행, valid {len(x_valid):,}행")

    preds = {}
    total_t0 = time.time()
    for q in QUANTILES:
        t0 = time.time()
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
        print(f"  quantile={q}: 학습 {time.time() - t0:.1f}초")
    print(f"[B1] 총 학습 시간: {time.time() - total_t0:.1f}초")

    # ── 순서 검증: q10 <= q50 <= q90 이 지켜지는가 ──
    q10, q50, q90 = preds[0.1], preds[0.5], preds[0.9]
    violation_10_50 = (q10 > q50).sum()
    violation_50_90 = (q50 > q90).sum()
    n = len(q50)
    print(
        f"[B1] quantile crossing (순서 위반): "
        f"q10>q50 {violation_10_50}건({violation_10_50 / n:.1%}), "
        f"q50>q90 {violation_50_90}건({violation_50_90 / n:.1%}) / 전체 {n:,}행"
    )
    print(f"[B1] q10 범위 [{q10.min():.2f}, {q10.max():.2f}], "
          f"q50 범위 [{q50.min():.2f}, {q50.max():.2f}], "
          f"q90 범위 [{q90.min():.2f}, {q90.max():.2f}]")
    print(f"[B1] 실측(target_net_flow) 범위 [{y_valid.min():.2f}, {y_valid.max():.2f}], "
          f"평균 {y_valid.mean():.3f}, 표준편차 {y_valid.std():.3f}")


if __name__ == "__main__":
    main()
