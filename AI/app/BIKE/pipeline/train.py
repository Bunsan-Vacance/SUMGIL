"""학습 → 아티팩트 저장. avg 소스(StockProfileBaseline)와 LightGBM(target_net_flow, v3)을
한 아티팩트 디렉터리에 같이 저장한다.

    models/BIKE/<tag>_<YYYYMMDD-HHMM>/
      stock_profile_avg.parquet          station×dow_type×time_slot 재고·확률 평균(avg 소스 본체)
      historical_profile_full.parquet    LightGBM feature용 historical profile 3종
      historical_profile_station_horizon.parquet
      historical_profile_global.parquet
      model.txt                          LightGBM booster(target_net_flow, 아직 avg 소스 변환 전)
      meta.json                          feature·하이퍼파라미터·평가 지표

LightGBM은 `target_net_flow`를 예측하는 모델이고, **avg 소스(exp_bikes/p_empty/p_full)
로의 변환은 아직 안 붙어 있다**(B4 model 소스, `predictor.py` docstring 참고) — 지금은
`predict_all()`이 avg만 지원한다. 이 학습이 LightGBM도 같이 만드는 이유는 target_net_flow
예측 자체는 이미 검증됐고(avg baseline 대비 우위, `RESULTS.md`), 나중에 변환 방법이
정해지면 이 아티팩트를 그대로 쓸 수 있게 하기 위해서다.

무거운 의존성(lightgbm)은 함수 안에서 지연 import한다(`AI/CLAUDE.md`).

실행 (스모크 — 며칠치로 먼저 확인):
    cd AI
    python -m app.BIKE.pipeline.train --train-months 202401 202402 --tag smoke

전체 실행 (11개월 train, 45% 샘플링 — 메모리 실측 근거는 RESULTS.md):
    python -m app.BIKE.pipeline.train --sample-frac 0.45 --tag v3
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from sklearn.metrics import mean_absolute_error, r2_score

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
from app.BIKE.pipeline.lookup import StockProfileBaseline

AI_ROOT = Path(__file__).resolve().parents[3]
MODELS_DIR = AI_ROOT / "models" / "BIKE"

BASE_READ_COLS = ["od_station_id", "date", *BASE_FEATURE_COLS, TARGET_COL]
TRAIN_READ_COLS = [*BASE_READ_COLS, "target_rent_count", "target_return_count"]

DEFAULT_PARAMS = {
    "n_estimators": 1500,
    "learning_rate": 0.02,
    "num_leaves": 127,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "n_jobs": -1,
}
EARLY_STOPPING_ROUNDS = 60


def _direction_metrics(y_true, y_pred) -> tuple[float, float]:
    from sklearn.metrics import accuracy_score, f1_score

    def _class(values):
        import numpy as np

        return np.where(values < 0, "decrease", np.where(values > 0, "increase", "stable"))

    true_c, pred_c = _class(y_true), _class(y_pred)
    return accuracy_score(true_c, pred_c), f1_score(true_c, pred_c, average="macro")


def _rmse(y_true, y_pred) -> float:
    from sklearn.metrics import mean_squared_error

    return mean_squared_error(y_true, y_pred) ** 0.5


def fit_lightgbm(
    train_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    random_state: int = 42,
    params: dict | None = None,
):
    from lightgbm import LGBMRegressor, early_stopping, log_evaluation

    x_train, y_train = make_xy(train_df)
    x_valid, y_valid = make_xy(valid_df)
    model = LGBMRegressor(**{**DEFAULT_PARAMS, **(params or {})}, random_state=random_state)
    t0 = time.time()
    model.fit(
        x_train,
        y_train,
        eval_set=[(x_valid, y_valid)],
        callbacks=[early_stopping(EARLY_STOPPING_ROUNDS), log_evaluation(0)],
    )
    return model, time.time() - t0


def evaluate_lightgbm(model, df: pd.DataFrame, label: str) -> dict:
    x, y = make_xy(df)
    pred = model.predict(x)
    acc, macro_f1 = _direction_metrics(y.to_numpy(), pred)
    return {
        "split": label,
        "rows": len(df),
        "mae": float(mean_absolute_error(y, pred)),
        "rmse": float(_rmse(y, pred)),
        "r2": float(r2_score(y, pred)),
        "direction_accuracy": float(acc),
        "direction_macro_f1": float(macro_f1),
    }


def run(
    train_months: list[str] | None = None,
    valid_months: list[str] | None = None,
    test_months: list[str] | None = None,
    sample_frac: float | None = None,
    random_state: int = 42,
    tag: str = "v3",
    out_root: Path = MODELS_DIR,
) -> Path:
    train_paths = monthly_paths("train", train_months)
    valid_paths = monthly_paths("valid", valid_months)
    test_paths = monthly_paths("test", test_months)
    holidays = load_holidays()

    # ── avg 소스: StockProfileBaseline(재고·확률) — train만으로 fit ──
    print(f"[avg] train {len(train_paths)}개 파일 스트리밍 집계...")
    avg_baseline = StockProfileBaseline().fit_streaming(train_paths, holidays)
    print(f"[avg] station×dow_type×time_slot {len(avg_baseline.table_):,}행")

    # ── LightGBM: target_net_flow (historical profile + 공휴일 feature) ──
    station_ids = (
        scan_station_ids(train_paths) | scan_station_ids(valid_paths) | scan_station_ids(test_paths)
    )
    station_dtype = build_station_dtype(station_ids)

    train_df = load_paths(train_paths, TRAIN_READ_COLS, TARGET_COL, sample_frac, random_state)
    train_df = _attach_holiday_flag(train_df, holidays)
    profile = HistoricalProfileBuilder().fit(train_df)
    train_df = profile.transform(train_df)
    apply_station_code(train_df, station_dtype, "train")

    valid_df = load_paths(valid_paths, BASE_READ_COLS, TARGET_COL)
    valid_df = _attach_holiday_flag(valid_df, holidays)
    valid_df = profile.transform(valid_df)
    apply_station_code(valid_df, station_dtype, "valid")

    model, train_time_sec = fit_lightgbm(train_df, valid_df, random_state)
    reports = [evaluate_lightgbm(model, valid_df, "valid")]
    del train_df, valid_df

    for p in test_paths:
        test_df = load_paths([p], BASE_READ_COLS, TARGET_COL)
        test_df = _attach_holiday_flag(test_df, holidays)
        test_df = profile.transform(test_df)
        apply_station_code(test_df, station_dtype, f"test:{p.stem}")
        reports.append(evaluate_lightgbm(model, test_df, f"test:{p.stem[-6:]}"))
        del test_df

    # ── 아티팩트 저장 ──
    stamp = datetime.now(UTC).astimezone().strftime("%Y%m%d-%H%M")
    out_dir = Path(out_root) / f"{tag}_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    avg_baseline.save(out_dir / "stock_profile_avg.parquet")
    profile.save(out_dir)
    model.booster_.save_model(str(out_dir / "model.txt"))
    meta = {
        "tag": tag,
        "train_months": [p.stem[-6:] for p in train_paths],
        "valid_months": [p.stem[-6:] for p in valid_paths],
        "test_months": [p.stem[-6:] for p in test_paths],
        "model_feature_cols": [*BASE_FEATURE_COLS, "station_code"],
        "station_categories": len(station_dtype.categories),
        "sample_frac": sample_frac,
        "train_time_sec": train_time_sec,
        "lightgbm_eval": reports,
        "avg_profile_rows": len(avg_baseline.table_),
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    print(f"[학습] 저장: {out_dir}")
    return out_dir


def _attach_holiday_flag(df: pd.DataFrame, holidays: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    merged = df.merge(holidays, on="date", how="left")
    merged["is_holiday"] = merged["is_holiday"].fillna(False).astype("int8")
    return merged


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--train-months", nargs="+", default=None)
    ap.add_argument("--valid-months", nargs="+", default=None)
    ap.add_argument("--test-months", nargs="+", default=None)
    ap.add_argument("--sample-frac", type=float, default=None)
    ap.add_argument("--random-state", type=int, default=42)
    ap.add_argument("--tag", default="v3")
    args = ap.parse_args(argv)
    run(
        args.train_months,
        args.valid_months,
        args.test_months,
        args.sample_frac,
        args.random_state,
        args.tag,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
