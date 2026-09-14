"""4~5단계 — 날짜축 멀티소스 LightGBM 학습 + avg 2종 baseline과 비교.

**anchor 없이, 미래 시점(target_datetime) 자체의 맥락만으로 절대 재고(target_stock)를
직접 예측**하는 모델이다(A1에서 실패한 "anchor+net_flow 보정" 방식이 아님 — 계획서 4단계
참고). `horizon_min == 30`인 행만 써서, 각 5분 anchor마다 "그로부터 30분 뒤"를 타깃으로
삼는다 — 이러면 하루 전체 시계열을 30분 간격으로 재구성한 것과 같다.

**시간 피처는 anchor가 아니라 target_datetime 기준으로 다시 계산한다**(anchor 기준 hour를
그대로 쓰면 최대 30분 어긋남 — 이 스크립트의 핵심 수정 사항). 날씨/공휴일/KBO는 anchor
기준 join을 그대로 쓴다(30분 이내로는 거의 안 바뀌는 근사, 계획서에 명시된 단순화).

비교 대상:
    baseline1: 기존 avg(station × dow_type × time_slot, train 전체)
    baseline2: station × month × dow_type × time_slot(train 전체, "최근 rolling"이 아니라
               전체 이력 기준 — RESULTS.md에서 recent rolling은 이미 기각됨)
    model:     LightGBM target_stock 직접 회귀(anchor 의존 피처 없음)

실행 (소규모 먼저):
    cd AI
    PYTHONPATH=. PYTHONIOENCODING=utf-8 python validation/BYC/lightgbm-stock-conversion-check/src/train_multisource_lightgbm.py --train-months 202401 202402 --test-months 202507
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from app.BIKE.pipeline.calendar import attach_dow_type, load_holidays

AI_ROOT = Path(__file__).resolve().parents[4]
INTERIM_DIR = AI_ROOT / "data" / "BIKE" / "interim"

READ_COLS = [
    "od_station_id", "rack_count", "date", "base_time", "horizon_min",
    "stock_anchor_hour", "target_net_flow",
    "is_holiday", "is_rain", "temp", "is_kbo_game_jamsil",
]

MODEL_FEATURE_COLS = [
    "target_hour", "target_minute", "target_dow", "target_is_weekend", "target_month",
    "target_sin_hour", "target_cos_hour",
    "is_holiday", "is_rain", "temp", "is_kbo_game_jamsil",
    "hist_mean", "hist_std", "station_code",
    "lag1d_stock", "lag1d_stock_available", "lag7d_stock", "lag7d_stock_available",
]

# lag lookup은 train/valid/test 경계를 넘어서 조인해야 한다(예: valid 12월 1일의 D-1은
# train 11월 30일에 있음) — 그래서 항상 전체 기간으로 한 번만 만든다.
ALL_MONTHS = [
    "202401", "202402", "202403", "202404", "202405", "202406",
    "202407", "202408", "202409", "202410", "202411", "202412",
    "202507", "202508", "202509",
]


def month_path(month: str) -> Path:
    p = INTERIM_DIR / f"lightgbm_multisource_{month}.parquet"
    if not p.exists():
        raise FileNotFoundError(f"{p} 없음 — join_multisource_features.py 먼저 실행")
    return p


def load_and_prepare(months: list[str], holidays: pd.DataFrame) -> pd.DataFrame:
    """horizon_min==30만 필터링하고, target_datetime 기준 시간 피처·라벨을 계산한다."""
    frames = []
    for m in months:
        df = pd.read_parquet(month_path(m), columns=READ_COLS)
        df = df[df["horizon_min"] == 30]
        df = df.dropna(subset=["stock_anchor_hour", "target_net_flow"])
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)

    df["base_time"] = pd.to_datetime(df["base_time"])
    target_dt = df["base_time"] + pd.Timedelta(minutes=30)
    df["target_hour"] = target_dt.dt.hour
    df["target_minute"] = target_dt.dt.minute
    df["target_dow"] = target_dt.dt.dayofweek
    df["target_is_weekend"] = (df["target_dow"] >= 5).astype("int8")
    df["target_month"] = target_dt.dt.month
    df["target_sin_hour"] = np.sin(2 * np.pi * df["target_hour"] / 24)
    df["target_cos_hour"] = np.cos(2 * np.pi * df["target_hour"] / 24)

    df["target_stock"] = df["stock_anchor_hour"] + df["target_net_flow"]
    df["target_stock_ratio"] = df["target_stock"] / df["rack_count"].replace(0, np.nan)
    df["is_empty_future"] = df["target_stock"] <= 0
    df["is_full_future"] = df["target_stock"] >= df["rack_count"]

    # dow_type: 서빙 중인 avg와 완전히 같은 규칙(calendar.attach_dow_type)을 그대로 재사용
    # 해야 공정 비교가 된다 — 손으로 다시 짜면 공휴일→일요일 취급 규칙을 빠뜨리기 쉽다.
    df["date"] = target_dt.dt.normalize()  # target 시점 기준(자정 넘어가는 극소수 행 보정)
    df = attach_dow_type(df, holidays)
    df["time_slot"] = df["target_hour"] * 2 + (df["target_minute"] >= 30).astype(int)

    return df


def build_lag_lookup() -> pd.DataFrame:
    """CROWD가 avg를 이긴 핵심 피처(D-1/D-7 자기 역 실측 lag)를 BIKE에도 적용한다
    (전체 기간 한 번만 만들어서 모든 split의 lag 조인에 재사용 — train/valid/test 경계를
    넘어서 조인해야 하므로).

    실시간 anchor(5분 전 데이터)와 다르다 — "하루 전체 지난 날"은 배치를 도는 시점엔
    항상 이미 확정된 데이터라, 정적 배치 설계와 충돌하지 않는다.

    **분(minute) 단위가 아니라 time_slot(30분) 단위로 집계한다.** 원본이 5분 "고정
    그리드"가 아니라 실제 대여·반납이 일어난 시점만 기록된 이벤트성 데이터라(역당
    하루 288슬롯 중 실제로는 50~60개뿐), 분까지 정확히 맞춰 조인하면 매칭률이
    30% 밑으로 떨어진다(실측 확인) — 30분 단위로 묶어 그 구간 평균을 대표값으로 쓴다."""
    frames = []
    for m in ALL_MONTHS:
        df = pd.read_parquet(
            month_path(m),
            columns=["od_station_id", "base_time", "horizon_min", "stock_anchor_hour", "target_net_flow"],
        )
        df = df[df["horizon_min"] == 30].dropna(subset=["stock_anchor_hour", "target_net_flow"])
        target_dt = pd.to_datetime(df["base_time"]) + pd.Timedelta(minutes=30)
        lag_time_slot = target_dt.dt.hour * 2 + (target_dt.dt.minute >= 30).astype(int)
        frames.append(
            pd.DataFrame(
                {
                    "od_station_id": df["od_station_id"].to_numpy(),
                    "lag_date": target_dt.dt.normalize(),
                    "lag_time_slot": lag_time_slot.to_numpy(),
                    "lag_stock": (df["stock_anchor_hour"] + df["target_net_flow"]).to_numpy(),
                }
            )
        )
    combined = pd.concat(frames, ignore_index=True)
    return (
        combined.groupby(["od_station_id", "lag_date", "lag_time_slot"])["lag_stock"]
        .mean().reset_index()
    )


def attach_lag(df: pd.DataFrame, lookup: pd.DataFrame, days: int, out_col: str) -> pd.DataFrame:
    """`days`일 전 같은 역·같은 30분 슬롯의 실측 평균을 `out_col`(값)과
    `{out_col}_available`(있었는지 여부, 0/1)로 붙인다. 없으면 값은 NaN으로 남기고
    (원칙 8), 나중에 hist_mean으로 fallback한다(main()에서, CROWD의 "이력 없으면
    lookup 대체"와 동일)."""
    key = df[["od_station_id", "time_slot"]].copy()
    key["lag_date"] = df["date"] - pd.Timedelta(days=days)
    key["lag_time_slot"] = df["time_slot"]
    merged = key.merge(
        lookup, on=["od_station_id", "lag_date", "lag_time_slot"], how="left"
    )
    df[out_col] = merged["lag_stock"].to_numpy()
    df[f"{out_col}_available"] = df[out_col].notna().astype("int8")
    return df


def fit_station_dow_hour_profile(train_df: pd.DataFrame) -> pd.DataFrame:
    """LightGBM 입력용 historical profile — **avg baseline1과 완전히 같은 그룹핑**
    (station×dow_type×time_slot, 평일 5일 묶음)으로 계산한다. 이전엔 target_dow(0~6,
    요일 안 묶음)×target_hour로 계산해서 avg보다 표본이 5분의 1로 쪼개져 노이즈가 컸다
    (원인 분석 후 수정) — 모델의 기준점 자체가 avg보다 부정확하면 그 위에 뭘 얹어도
    avg를 이기기 어렵다."""
    return (
        train_df.groupby(["od_station_id", "dow_type", "time_slot"])["target_stock"]
        .agg(hist_mean="mean", hist_std="std")
        .reset_index()
    )


def attach_profile(df: pd.DataFrame, profile: pd.DataFrame, global_mean: float) -> pd.DataFrame:
    merged = df.merge(profile, on=["od_station_id", "dow_type", "time_slot"], how="left")
    merged["hist_mean"] = merged["hist_mean"].fillna(global_mean)
    merged["hist_std"] = merged["hist_std"].fillna(0.0)
    return merged


def fill_lag_fallback(df: pd.DataFrame) -> pd.DataFrame:
    """lag1d_stock/lag7d_stock 결측(데이터 경계라 그 날이 없는 경우)을 hist_mean으로
    채운다 — CROWD가 "이력이 전혀 없으면 lookup으로 대체"하는 것과 같은 관례.
    `{col}_available` 플래그는 그대로 둬서 모델이 "이 값이 진짜 실측인지 대체값인지"를
    구분할 수 있게 한다."""
    for col in ("lag1d_stock", "lag7d_stock"):
        df[col] = df[col].fillna(df["hist_mean"])
    return df


def fit_baselines(train_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    b1 = (
        train_df.groupby(["od_station_id", "dow_type", "time_slot"])["target_stock"]
        .mean().reset_index().rename(columns={"target_stock": "b1_pred"})
    )
    b2 = (
        train_df.groupby(["od_station_id", "target_month", "dow_type", "time_slot"])["target_stock"]
        .mean().reset_index().rename(columns={"target_stock": "b2_pred"})
    )
    return b1, b2


def evaluate(test_df: pd.DataFrame, b1: pd.DataFrame, b2: pd.DataFrame, model, station_dtype) -> pd.DataFrame:
    df = test_df.merge(b1, on=["od_station_id", "dow_type", "time_slot"], how="left")
    df = df.merge(b2, on=["od_station_id", "target_month", "dow_type", "time_slot"], how="left")

    x = df.copy()
    x["station_code"] = x["od_station_id"].astype(station_dtype).cat.codes
    x = x[MODEL_FEATURE_COLS].fillna(0)
    # 모델은 잔차(hist_mean 대비 벗어난 정도)만 예측했으므로 hist_mean을 다시 더한다.
    df["model_pred"] = df["hist_mean"].to_numpy() + model.predict(x)

    rows = []
    for col, name in [("b1_pred", "baseline1_avg"), ("b2_pred", "baseline2_month"), ("model_pred", "lightgbm")]:
        valid = df.dropna(subset=[col])
        mae = (valid[col] - valid["target_stock"]).abs().mean()
        rows.append({"source": name, "n": len(valid), "mae": mae})
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> None:
    from lightgbm import LGBMRegressor

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train-months", nargs="+", required=True)
    ap.add_argument("--valid-months", nargs="+", default=None, help="early stopping용(생략 시 미사용)")
    ap.add_argument("--test-months", nargs="+", required=True)
    ap.add_argument("--n-estimators", type=int, default=500)
    ap.add_argument("--learning-rate", type=float, default=0.05)
    ap.add_argument("--num-leaves", type=int, default=63)
    ap.add_argument("--early-stopping-rounds", type=int, default=60)
    args = ap.parse_args(argv)

    holidays = load_holidays()

    print("[학습] D-1/D-7 lag lookup 생성(전체 기간)...")
    t_lag0 = time.time()
    lag_lookup = build_lag_lookup()
    print(f"[학습] lag lookup {len(lag_lookup):,}행, {time.time() - t_lag0:.1f}초")

    print("[학습] train 로딩...")
    train_df = load_and_prepare(args.train_months, holidays)
    train_df = attach_lag(train_df, lag_lookup, 1, "lag1d_stock")
    train_df = attach_lag(train_df, lag_lookup, 7, "lag7d_stock")
    print(f"[학습] train {len(train_df):,}행, "
          f"lag1d 가용률 {train_df['lag1d_stock_available'].mean():.1%}, "
          f"lag7d 가용률 {train_df['lag7d_stock_available'].mean():.1%}")

    profile = fit_station_dow_hour_profile(train_df)
    global_mean = float(train_df["target_stock"].mean())
    train_df = attach_profile(train_df, profile, global_mean)
    train_df = fill_lag_fallback(train_df)

    b1, b2 = fit_baselines(train_df)

    # station_code는 정수 대신 **명시적 카테고리형**으로 준다 — 정수로 주면 LightGBM이
    # 순서가 있는 숫자로 취급해서(역 500번과 501번이 비슷하다고 착각) 역 구분력이
    # 떨어진다. target_net_flow(작은 변화량)와 달리 절대 재고값은 역마다 규모가
    # 천차만별이라 이 구분력이 훨씬 중요하다(원인 분석).
    station_dtype = pd.CategoricalDtype(categories=sorted(train_df["od_station_id"].unique()))
    train_df["station_code"] = train_df["od_station_id"].astype(station_dtype).cat.codes

    x_train = train_df[MODEL_FEATURE_COLS].fillna(0)
    # target_stock을 바로 맞히지 않고 **hist_mean(=baseline1과 동일 기준)에서 얼마나
    # 벗어나는지(잔차)만** 학습한다 — 이러면 모델의 출발점이 avg와 똑같아지고, 날씨·
    # 공휴일·KBO 같은 약한 피처는 "그 위에 얹는 보정"만 담당하게 돼서 학습이 훨씬 쉬워진다
    # (hist_mean이 다른 약한 피처들 사이에서 중요도가 희석되는 문제 회피).
    y_train = train_df["target_stock"] - train_df["hist_mean"]
    # LightGBM에 station_code가 순서 있는 숫자가 아니라 카테고리(역 구분)임을 명시적으로
    # 알려준다 — pandas category dtype 자동 감지에 의존하지 않고 직접 지정(더 확실함).
    cat_kwargs = {"categorical_feature": ["station_code"]}

    print("[학습] LightGBM 학습...")
    t0 = time.time()
    model = LGBMRegressor(
        n_estimators=args.n_estimators, learning_rate=args.learning_rate,
        num_leaves=args.num_leaves, subsample=0.8, colsample_bytree=0.8,
        n_jobs=-1, verbose=-1,
    )
    if args.valid_months:
        from lightgbm import early_stopping, log_evaluation

        valid_df = load_and_prepare(args.valid_months, holidays)
        valid_df = attach_lag(valid_df, lag_lookup, 1, "lag1d_stock")
        valid_df = attach_lag(valid_df, lag_lookup, 7, "lag7d_stock")
        valid_df = attach_profile(valid_df, profile, global_mean)
        valid_df = fill_lag_fallback(valid_df)
        valid_df["station_code"] = valid_df["od_station_id"].astype(station_dtype).cat.codes
        x_valid = valid_df[MODEL_FEATURE_COLS].fillna(0)
        y_valid = valid_df["target_stock"] - valid_df["hist_mean"]
        model.fit(
            x_train, y_train, eval_set=[(x_valid, y_valid)],
            callbacks=[early_stopping(args.early_stopping_rounds), log_evaluation(0)],
            **cat_kwargs,
        )
    else:
        model.fit(x_train, y_train, **cat_kwargs)
    print(f"[학습] 완료 {time.time() - t0:.1f}초")

    print("[평가] test 로딩...")
    test_df = load_and_prepare(args.test_months, holidays)
    test_df = attach_lag(test_df, lag_lookup, 1, "lag1d_stock")
    test_df = attach_lag(test_df, lag_lookup, 7, "lag7d_stock")
    test_df = attach_profile(test_df, profile, global_mean)
    test_df = fill_lag_fallback(test_df)
    print(f"[평가] test {len(test_df):,}행, "
          f"lag1d 가용률 {test_df['lag1d_stock_available'].mean():.1%}, "
          f"lag7d 가용률 {test_df['lag7d_stock_available'].mean():.1%}")

    report = evaluate(test_df, b1, b2, model, station_dtype)
    print("\n[결과] MAE 비교 (트랙 B, target_stock 기준)")
    print(report.to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1:])
