"""날짜축 멀티소스 모델(B4-2) 학습 → 아티팩트 저장. `train.py`(anchor+horizon v3)와는
별개 진입점이다 — 옛 구조는 지우지 않고 나란히 둔다(나중에 "실시간 근시간 예측"용으로
쓸 수도 있어서).

    models/BIKE/<tag>_<YYYYMMDD-HHMM>/
      model_exp_bikes.txt         LightGBM(잔차 회귀) — exp_bikes 본체
      model_q10.txt, model_q50.txt, model_q90.txt   quantile 3개 — p_empty/p_full 재료
      isotonic_empty.pkl, isotonic_full.pkl          quantile → 확률 보정기
      historical_profile.parquet  station×dow_type×time_slot 평균/표준편차(avg와 동일 그룹핑)
      lag_lookup.parquet          D-1/D-7 조회용, 배치 시점에도 재사용
      station_categories.json     station_code 복원용 카테고리 목록
      meta.json                  피처·하이퍼파라미터·평가 지표

**anchor 없음** — "지금 재고"를 안 물어보고, 그 시점의 맥락(시간·요일·날씨·공휴일·KBO)과
D-1/D-7 실측 lag만으로 절대 재고를 직접 예측한다(`validation/BYC/lightgbm-stock-conversion-check
/RESULTS.md`에서 검증 완료: exp_bikes -11.6%, p_full -12.4%, p_empty -1.8%, 전부 avg를 넘김).

예측 방식은 "잔차 학습" — `target_stock`을 바로 맞히지 않고 `target_stock - hist_mean`만
예측한다. hist_mean(avg와 동일 그룹핑)을 다른 약한 피처들(날씨 등) 사이에서 중요도가
희석되지 않게 하려는 것 — 그냥 절댓값으로 학습하면 avg를 못 이겼다(원인 진단 기록,
RESULTS.md).

무거운 의존성(lightgbm, sklearn.isotonic)은 함수 안에서 지연 import한다(`AI/CLAUDE.md`).

실행 (스모크 — 며칠치로 먼저 확인, validation 스크립트와 동일 결과 재현되는지 대조):
    cd AI
    python -m app.BIKE.pipeline.train_multisource --train-months 202401 202402 --valid-months 202412 --test-months 202507 --tag smoke

전체 실행(검증 완료 하이퍼파라미터):
    python -m app.BIKE.pipeline.train_multisource --n-estimators 1500 --learning-rate 0.02 --num-leaves 127 --early-stopping-rounds 60 --tag multisource-v1
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from app.BIKE.pipeline.calendar import load_holidays
from app.BIKE.pipeline.dataset import monthly_paths
from app.BIKE.pipeline.external_features import (
    attach_external,
    jamsil_nearby_stations,
    load_jamsil_game_dates,
    load_weather,
)
from app.BIKE.pipeline.features import (
    MULTISOURCE_FEATURE_COLS,
    MULTISOURCE_TARGET_COL,
    add_future_stock_labels,
    attach_multisource_profile,
    compute_target_time_features,
    fill_lag_fallback,
    fit_station_dow_time_slot_profile,
)
from app.BIKE.pipeline.lag_features import attach_lag, build_lag_lookup

AI_ROOT = Path(__file__).resolve().parents[3]
MODELS_DIR = AI_ROOT / "models" / "BIKE"

READ_COLS = [
    "od_station_id",
    "rack_count",
    "lat_stock",
    "lon_stock",
    "date",
    "hour",
    "base_time",
    "horizon_min",
    "stock_anchor_hour",
    "target_net_flow",
]

QUANTILES = [0.1, 0.5, 0.9]
Z_90 = 1.2816

DEFAULT_PARAMS = {
    "n_estimators": 500,
    "learning_rate": 0.05,
    "num_leaves": 63,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "n_jobs": -1,
}


def _load_split(
    months: list[str] | None,
    holidays: pd.DataFrame,
    weather: pd.DataFrame,
    jamsil_dates: set,
    jamsil_stations: set,
    lag_lookup: pd.DataFrame,
) -> pd.DataFrame:
    """raw netflow(horizon_min==30) → 라벨·시간피처·외부피처·D-1/D-7 lag까지 다 붙인 프레임."""
    frames = []
    for prefix in ("train", "valid", "test"):
        try:
            paths = monthly_paths(prefix, months)
        except FileNotFoundError:
            continue
        for p in paths:
            df = pd.read_parquet(p, columns=READ_COLS)
            df = df[df["horizon_min"] == 30].dropna(subset=["stock_anchor_hour", "target_net_flow"])
            frames.append(df)
    df = pd.concat(frames, ignore_index=True)

    df = add_future_stock_labels(df)
    # attach_external을 target-시각 계산보다 먼저 부른다 — compute_target_time_features가
    # "date"를 target 기준으로 덮어쓰기 때문에, 순서를 바꾸면 날씨·공휴일·KBO 조인이
    # anchor 기준이 아니라 target 기준으로 바뀐다(검증된 동작과 달라짐 — RESULTS.md는
    # anchor 기준 조인으로 검증됨, 30분 이내 근사).
    df = attach_external(df, weather, holidays, jamsil_dates, jamsil_stations)
    df = compute_target_time_features(df, holidays)
    df = attach_lag(df, lag_lookup, 1, "lag1d_stock")
    df = attach_lag(df, lag_lookup, 7, "lag7d_stock")
    return df


def _normal_cdf(x, mu, sigma):
    from scipy.stats import norm

    sigma = np.where(sigma <= 1e-6, 1e-6, sigma)
    return norm.cdf(x, loc=mu, scale=sigma)


def run(
    train_months: list[str] | None = None,
    valid_months: list[str] | None = None,
    test_months: list[str] | None = None,
    params: dict | None = None,
    early_stopping_rounds: int = 60,
    tag: str = "multisource",
    out_root: Path = MODELS_DIR,
) -> Path:
    from lightgbm import LGBMRegressor, early_stopping, log_evaluation
    from sklearn.isotonic import IsotonicRegression

    params = {**DEFAULT_PARAMS, **(params or {})}
    holidays = load_holidays()
    weather = load_weather()
    jamsil_dates = load_jamsil_game_dates()

    print("[학습] D-1/D-7 lag lookup 생성(전체 기간)...")
    t0 = time.time()
    lag_lookup = build_lag_lookup()
    print(f"[학습] lag lookup {len(lag_lookup):,}행, {time.time() - t0:.1f}초")

    # 잠실 인근 역은 좌표 있는 파일 하나로만 구한다(월마다 좌표는 동일).
    sample_path = monthly_paths("train", train_months)[0]
    coords = pd.read_parquet(sample_path, columns=["od_station_id", "lat_stock", "lon_stock"])
    jamsil_stations = jamsil_nearby_stations(coords)

    print("[학습] train 로딩...")
    train_df = _load_split(
        train_months, holidays, weather, jamsil_dates, jamsil_stations, lag_lookup
    )
    print(
        f"[학습] train {len(train_df):,}행, lag1d 가용률 {train_df['lag1d_stock_available'].mean():.1%}, "
        f"lag7d 가용률 {train_df['lag7d_stock_available'].mean():.1%}"
    )

    profile = fit_station_dow_time_slot_profile(train_df)
    global_mean = float(train_df[MULTISOURCE_TARGET_COL].mean())
    train_df = attach_multisource_profile(train_df, profile, global_mean)
    train_df = fill_lag_fallback(train_df)

    station_dtype = pd.CategoricalDtype(categories=sorted(train_df["od_station_id"].unique()))
    train_df["station_code"] = train_df["od_station_id"].astype(station_dtype).cat.codes

    x_train = train_df[MULTISOURCE_FEATURE_COLS].fillna(0)
    y_train_residual = train_df[MULTISOURCE_TARGET_COL] - train_df["hist_mean"]
    cat_kwargs = {"categorical_feature": ["station_code"]}

    valid_df = None
    if valid_months:
        valid_df = _load_split(
            valid_months, holidays, weather, jamsil_dates, jamsil_stations, lag_lookup
        )
        valid_df = attach_multisource_profile(valid_df, profile, global_mean)
        valid_df = fill_lag_fallback(valid_df)
        valid_df["station_code"] = valid_df["od_station_id"].astype(station_dtype).cat.codes

    def _fit(objective_kwargs: dict, y):
        model = LGBMRegressor(**params, **objective_kwargs)
        if valid_df is not None:
            x_valid = valid_df[MULTISOURCE_FEATURE_COLS].fillna(0)
            y_valid = valid_df[MULTISOURCE_TARGET_COL] - valid_df["hist_mean"]
            model.fit(
                x_train,
                y,
                eval_set=[(x_valid, y_valid)],
                callbacks=[early_stopping(early_stopping_rounds), log_evaluation(0)],
                **cat_kwargs,
            )
        else:
            model.fit(x_train, y, **cat_kwargs)
        return model

    print("[학습] exp_bikes 모델(잔차 회귀) 학습...")
    t0 = time.time()
    exp_bikes_model = _fit({}, y_train_residual)
    exp_bikes_train_sec = time.time() - t0
    print(f"[학습] 완료 {exp_bikes_train_sec:.1f}초")

    print("[학습] quantile 3개 학습...")
    t0 = time.time()
    quantile_models = {
        q: _fit({"objective": "quantile", "alpha": q}, y_train_residual) for q in QUANTILES
    }
    quantile_train_sec = time.time() - t0
    print(f"[학습] 완료 {quantile_train_sec:.1f}초")

    # ── isotonic 보정기: valid로 fit(없으면 train으로 — 권장하지 않지만 스모크용 허용) ──
    calib_df = valid_df if valid_df is not None else train_df
    x_calib = calib_df[MULTISOURCE_FEATURE_COLS].fillna(0)
    hist_mean_calib = calib_df["hist_mean"].to_numpy()
    q10 = hist_mean_calib + quantile_models[0.1].predict(x_calib)
    q50 = hist_mean_calib + quantile_models[0.5].predict(x_calib)
    q90 = hist_mean_calib + quantile_models[0.9].predict(x_calib)
    sigma = (q90 - q10) / (2 * Z_90)
    p_empty_raw = _normal_cdf(0.0, q50, sigma)
    p_full_raw = 1 - _normal_cdf(calib_df["rack_count"].to_numpy(), q50, sigma)

    iso_empty = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso_empty.fit(p_empty_raw, calib_df["is_empty_future"].to_numpy())
    iso_full = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso_full.fit(p_full_raw, calib_df["is_full_future"].to_numpy())

    # ── 평가(테스트가 있으면) ──
    reports = []
    if test_months:
        test_df = _load_split(
            test_months, holidays, weather, jamsil_dates, jamsil_stations, lag_lookup
        )
        test_df = attach_multisource_profile(test_df, profile, global_mean)
        test_df = fill_lag_fallback(test_df)
        test_df["station_code"] = test_df["od_station_id"].astype(station_dtype).cat.codes
        x_test = test_df[MULTISOURCE_FEATURE_COLS].fillna(0)
        hist_mean_test = test_df["hist_mean"].to_numpy()

        exp_bikes_pred = hist_mean_test + exp_bikes_model.predict(x_test)
        mae_exp_bikes = float((exp_bikes_pred - test_df[MULTISOURCE_TARGET_COL]).abs().mean())

        q10t = hist_mean_test + quantile_models[0.1].predict(x_test)
        q50t = hist_mean_test + quantile_models[0.5].predict(x_test)
        q90t = hist_mean_test + quantile_models[0.9].predict(x_test)
        sigma_t = (q90t - q10t) / (2 * Z_90)
        p_empty_test = iso_empty.predict(_normal_cdf(0.0, q50t, sigma_t))
        p_full_test = iso_full.predict(
            1 - _normal_cdf(test_df["rack_count"].to_numpy(), q50t, sigma_t)
        )
        brier_empty = float(np.mean((p_empty_test - test_df["is_empty_future"].to_numpy()) ** 2))
        brier_full = float(np.mean((p_full_test - test_df["is_full_future"].to_numpy()) ** 2))

        reports.append(
            {
                "split": "test",
                "rows": len(test_df),
                "mae_exp_bikes": mae_exp_bikes,
                "brier_p_empty": brier_empty,
                "brier_p_full": brier_full,
            }
        )
        print(
            f"[평가] test: MAE(exp_bikes)={mae_exp_bikes:.3f}, Brier(p_empty)={brier_empty:.4f}, "
            f"Brier(p_full)={brier_full:.4f}"
        )

    # ── 아티팩트 저장 ──
    stamp = datetime.now(UTC).astimezone().strftime("%Y%m%d-%H%M")
    out_dir = Path(out_root) / f"{tag}_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    exp_bikes_model.booster_.save_model(str(out_dir / "model_exp_bikes.txt"))
    for q, m in quantile_models.items():
        m.booster_.save_model(str(out_dir / f"model_q{int(q * 100)}.txt"))
    with (out_dir / "isotonic_empty.pkl").open("wb") as f:
        pickle.dump(iso_empty, f)
    with (out_dir / "isotonic_full.pkl").open("wb") as f:
        pickle.dump(iso_full, f)
    profile.to_parquet(out_dir / "historical_profile.parquet", index=False)
    lag_lookup.to_parquet(out_dir / "lag_lookup.parquet", index=False)
    (out_dir / "station_categories.json").write_text(
        json.dumps(list(station_dtype.categories), ensure_ascii=False), encoding="utf-8"
    )

    meta = {
        "tag": tag,
        "train_months": train_months,
        "valid_months": valid_months,
        "test_months": test_months,
        "feature_cols": MULTISOURCE_FEATURE_COLS,
        "quantiles": QUANTILES,
        "params": params,
        "early_stopping_rounds": early_stopping_rounds,
        "global_mean": global_mean,
        "jamsil_stations": len(jamsil_stations),
        "exp_bikes_train_sec": exp_bikes_train_sec,
        "quantile_train_sec": quantile_train_sec,
        "eval": reports,
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    print(f"[학습] 저장: {out_dir}")
    return out_dir


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--train-months", nargs="+", default=None)
    ap.add_argument("--valid-months", nargs="+", default=None)
    ap.add_argument("--test-months", nargs="+", default=None)
    ap.add_argument("--n-estimators", type=int, default=DEFAULT_PARAMS["n_estimators"])
    ap.add_argument("--learning-rate", type=float, default=DEFAULT_PARAMS["learning_rate"])
    ap.add_argument("--num-leaves", type=int, default=DEFAULT_PARAMS["num_leaves"])
    ap.add_argument("--early-stopping-rounds", type=int, default=60)
    ap.add_argument("--tag", default="multisource")
    args = ap.parse_args(argv)

    params = {
        "n_estimators": args.n_estimators,
        "learning_rate": args.learning_rate,
        "num_leaves": args.num_leaves,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "n_jobs": -1,
    }
    run(
        args.train_months,
        args.valid_months,
        args.test_months,
        params,
        args.early_stopping_rounds,
        args.tag,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
