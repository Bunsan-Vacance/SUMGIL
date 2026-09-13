"""전체 대여소 LightGBM 재학습 v2 — Phase 2 historical profile feature 추가.

v1(`train_lightgbm_full.py`)이 avg baseline보다 MAE·RMSE·R² **전부** 못한 결과가
나왔는데, v1은 `phase1_baseline.py`의 **최소 feature셋**(historical profile 없음)만
썼다 — top300 실험에서도 Phase 1(최소셋)은 Naive_Profile을 못 이겼고, Phase 2(과거
프로파일 feature 추가)에서야 MAE/R²를 안정적으로 이겼다. 그 단계를 빼먹은 채로
"LightGBM이 전체 스케일에서 진 것"으로 결론 내리면 안 된다 — Phase 2를 먼저 붙여보고
다시 비교한다.

`phase2_historical_profile.py`의 `HistoricalProfileBuilder`(station×dow×hour×horizon
과거 평균/표준편차·rent/return 평균, train만으로 fit, station×horizon→horizon 전체
순으로 fallback)를 그대로 재사용한다. 그 모듈을 import하면 `phase1_baseline`의
`FEATURE_COLS`/`MODEL_FEATURE_COLS`가 Phase 2 세트로 patch되는 부작용이 있어(같은
파일 안에서 일어남), `make_xy`/`fit_lightgbm`/`apply_station_code`는 자동으로 확장된
feature를 쓰게 된다 — 이 스크립트에서 따로 맞출 필요 없음.

실행:
    python train_lightgbm_full_v2.py --sample-frac 0.45 --tag v2-full
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_full_station_netflow import PeakMemoryTracker

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "q3-seasonal-dataset-check" / "src"))
import phase1_baseline as p1
import phase2_historical_profile as p2
from sklearn.metrics import mean_absolute_error, r2_score

DATA_DIR = Path(__file__).resolve().parents[1] / "outputs" / "full-run"
AI_DIR = Path(__file__).resolve().parents[4]
MODELS_DIR = AI_DIR / "models" / "BIKE"
HOLIDAY_PATH = AI_DIR / "data" / "EXTERNAL" / "holiday" / "interim" / "holiday_calendar.parquet"

TARGET_COL = p1.TARGET_COL
BASE_READ_COLS = ["od_station_id", "date", *p2.BASE_COLS, TARGET_COL]
TRAIN_READ_COLS = [*BASE_READ_COLS, "target_rent_count", "target_return_count"]


def apply_feature_cols(use_holiday: bool) -> list[str]:
    """is_holiday 포함 여부에 따라 p1의 전역 FEATURE_COLS/MODEL_FEATURE_COLS를 맞춘다.

    재튜닝 1순위(사용자 지시) — 원래 day_of_week/is_weekend만으로는 평일에 낀 공휴일
    (신정·삼일절·추석 등)을 못 잡았다. 사립학교교직원연금공단 공휴일 캘린더는 토요일도
    함께 Y로 잡는 최신 5일제 기준이라(1980년대 자료는 토 N, 확인됨 — 이 파일은 그 시기별
    변화를 그대로 반영), day_of_week로 토요일을 이미 구분하는 우리 feature와 겹쳐도
    문제없다(공휴일 자체가 새 정보를 주는 게 핵심). --no-holiday로 A/B 비교 가능.
    """
    p1.FEATURE_COLS = p2.FEATURE_COLS + (["is_holiday"] if use_holiday else [])
    p1.MODEL_FEATURE_COLS = p1.FEATURE_COLS + ["station_code"]
    return p1.MODEL_FEATURE_COLS


def load_holiday_calendar() -> pd.DataFrame:
    if not HOLIDAY_PATH.exists():
        raise FileNotFoundError(f"{HOLIDAY_PATH} 없음 — holiday_calendar.parquet 먼저 준비")
    hol = pd.read_parquet(HOLIDAY_PATH)[["date", "is_holiday"]]
    hol["date"] = pd.to_datetime(hol["date"]).dt.normalize()
    return hol


def attach_holiday(df: pd.DataFrame, holidays: pd.DataFrame) -> pd.DataFrame:
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    merged = df.merge(holidays, on="date", how="left")
    merged["is_holiday"] = merged["is_holiday"].fillna(False).astype("int8")
    return merged


def _monthly_paths(prefix: str, months: list[str] | None = None) -> list[Path]:
    paths = sorted(DATA_DIR.glob(f"{prefix}_netflow_q3_mapped_full_*.parquet"))
    if not paths:
        raise FileNotFoundError(f"{DATA_DIR}에 {prefix}_netflow_q3_mapped_full_*.parquet 없음")
    if months:
        paths = [p for p in paths if any(m in p.stem for m in months)]
    return paths


def load_paths(
    paths: list[Path], cols: list[str], sample_frac: float | None = None, random_state: int = 42
) -> pd.DataFrame:
    """여러 parquet을 필요한 컬럼만 읽어 합치고, NaN target을 제외한다.

    sample_frac은 파일별로 적용한다(로딩 도중 피크 메모리도 같이 줄이려고 — train_lightgbm_full.py와 동일 이유).
    """
    frames = []
    for p in paths:
        df = pd.read_parquet(p, columns=cols)
        if sample_frac is not None:
            df = df.sample(frac=sample_frac, random_state=random_state)
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["od_station_id"] = df["od_station_id"].astype(str)
    before = len(df)
    df = df.dropna(subset=[TARGET_COL]).reset_index(drop=True)
    dropped = before - len(df)
    if dropped:
        print(f"  target_net_flow NaN {dropped:,}행 제외 (월 경계 rolling window 부작용)")
    return p1.downcast_memory(df)


def scan_station_ids_parquet(paths: list[Path]) -> set[str]:
    ids: set[str] = set()
    for p in paths:
        col = pq.ParquetFile(p).read(columns=["od_station_id"])["od_station_id"]
        ids |= set(col.to_pylist())
    return ids


def evaluate(model, df: pd.DataFrame, label: str) -> dict:
    x, y = p1.make_xy(df)
    pred = model.predict(x)
    acc, macro_f1 = p1.direction_metrics(y.to_numpy(), pred)
    return {
        "split": label,
        "rows": len(df),
        "mae": float(mean_absolute_error(y, pred)),
        "rmse": float(p1.rmse(y, pred)),
        "r2": float(r2_score(y, pred)),
        "wape": float(p1.wape(y.to_numpy(), pred)),
        "direction_accuracy": float(acc),
        "direction_macro_f1": float(macro_f1),
    }


def fit_lightgbm_tuned(
    train_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    random_state: int,
    n_estimators: int,
    learning_rate: float,
    num_leaves: int,
    early_stopping_rounds: int,
):
    """p1.fit_lightgbm과 같은 구조지만 하이퍼파라미터를 CLI로 받는다.

    조기종료가 25~33라운드에서 걸린 것(기본 learning_rate=0.05, 500라운드 중)이
    이 스케일엔 너무 높다는 신호일 수 있어 재튜닝 대상으로 삼았다 — n_estimators를
    늘리고 patience(early_stopping_rounds)도 같이 늘려야 learning_rate를 낮춘
    효과를 볼 수 있다.
    """
    from lightgbm import LGBMRegressor, early_stopping, log_evaluation

    x_train, y_train = p1.make_xy(train_df)
    x_valid, y_valid = p1.make_xy(valid_df)
    model = LGBMRegressor(
        n_estimators=n_estimators,
        learning_rate=learning_rate,
        num_leaves=num_leaves,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=random_state,
        n_jobs=-1,
    )
    started_at = time.time()
    model.fit(
        x_train,
        y_train,
        eval_set=[(x_valid, y_valid)],
        callbacks=[early_stopping(early_stopping_rounds), log_evaluation(0)],
    )
    return p1.FitResult("LightGBM", model, time.time() - started_at)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--train-months", nargs="+", default=None)
    p.add_argument("--valid-months", nargs="+", default=None)
    p.add_argument("--test-months", nargs="+", default=None)
    p.add_argument("--random-state", type=int, default=42)
    p.add_argument(
        "--sample-frac", type=float, default=None, help="train만 파일별 샘플링(예: 0.45)"
    )
    p.add_argument("--n-estimators", type=int, default=500)
    p.add_argument("--learning-rate", type=float, default=0.05)
    p.add_argument("--num-leaves", type=int, default=63)
    p.add_argument("--early-stopping-rounds", type=int, default=30)
    p.add_argument("--no-holiday", action="store_true", help="is_holiday feature 끄기(비교용)")
    p.add_argument("--tag", default="v2-full")
    p.add_argument(
        "--out-dir", default=str(Path(__file__).resolve().parents[1] / "outputs" / "lightgbm-full")
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    use_holiday = not args.no_holiday
    apply_feature_cols(use_holiday)
    holidays = load_holiday_calendar()

    train_paths = _monthly_paths("train", args.train_months)
    valid_paths = _monthly_paths("valid", args.valid_months)
    test_paths = _monthly_paths("test", args.test_months)
    print(
        f"train {len(train_paths)}개 파일, valid {len(valid_paths)}개, test {len(test_paths)}개, is_holiday={use_holiday}"
    )

    with PeakMemoryTracker() as mem:
        t0 = time.time()
        station_ids = (
            scan_station_ids_parquet(train_paths)
            | scan_station_ids_parquet(valid_paths)
            | scan_station_ids_parquet(test_paths)
        )
        station_dtype = p1.build_station_dtype(station_ids)
        print(
            f"station dtype: {len(station_dtype.categories):,}개 ({time.time() - t0:.1f}초, {mem.peak_mb}MB)"
        )

        t0 = time.time()
        train_df = load_paths(train_paths, TRAIN_READ_COLS, args.sample_frac, args.random_state)
        train_df = attach_holiday(train_df, holidays)
        print(f"train 로드: {len(train_df):,}행 ({time.time() - t0:.1f}초, {mem.peak_mb}MB)")

        t0 = time.time()
        profile = p2.HistoricalProfileBuilder()
        profile.fit(train_df)  # train 기간으로만 fit — leakage 방지
        train_df = profile.transform(train_df)
        p1.apply_station_code(train_df, station_dtype, "train")
        print(f"historical profile fit+transform(train): {time.time() - t0:.1f}초, {mem.peak_mb}MB")

        t0 = time.time()
        valid_df = load_paths(valid_paths, BASE_READ_COLS)
        valid_df = attach_holiday(valid_df, holidays)
        valid_df = profile.transform(valid_df)
        p1.apply_station_code(valid_df, station_dtype, "valid")
        print(
            f"valid 로드+transform: {len(valid_df):,}행 ({time.time() - t0:.1f}초, {mem.peak_mb}MB)"
        )

        t0 = time.time()
        result = fit_lightgbm_tuned(
            train_df,
            valid_df,
            args.random_state,
            args.n_estimators,
            args.learning_rate,
            args.num_leaves,
            args.early_stopping_rounds,
        )
        if result.model is None:
            raise RuntimeError(result.skipped_reason)
        print(f"LightGBM 학습 완료: {time.time() - t0:.1f}초, {mem.peak_mb}MB")

        reports = [evaluate(result.model, valid_df, "valid")]
        del train_df, valid_df

        for p in test_paths:
            t0 = time.time()
            test_df = load_paths([p], BASE_READ_COLS)
            test_df = attach_holiday(test_df, holidays)
            test_df = profile.transform(test_df)
            p1.apply_station_code(test_df, station_dtype, f"test:{p.stem}")
            r = evaluate(result.model, test_df, f"test:{p.stem[-6:]}")
            r["elapsed_sec"] = round(time.time() - t0, 1)
            reports.append(r)
            print(
                f"[{r['split']}] rows={r['rows']:,} mae={r['mae']:.4f} rmse={r['rmse']:.4f} "
                f"r2={r['r2']:.4f} wape={r['wape']:.4f} dir_acc={r['direction_accuracy']:.4f} "
                f"({r['elapsed_sec']}초, {mem.peak_mb}MB)"
            )
            del test_df

    print(f"\n전체 피크 메모리: {mem.peak_mb}MB")
    report_df = pd.DataFrame(reports)
    report_df["peak_memory_mb"] = mem.peak_mb
    report_df.to_csv(out_dir / f"eval_report_{args.tag}.csv", index=False)

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    artifact_dir = MODELS_DIR / f"{args.tag}_{stamp}"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    result.model.booster_.save_model(str(artifact_dir / "model.txt"))
    profile.full.to_parquet(artifact_dir / "profile_full.parquet", index=False)
    profile.station_horizon.to_parquet(
        artifact_dir / "profile_station_horizon.parquet", index=False
    )
    profile.global_.to_parquet(artifact_dir / "profile_global.parquet", index=False)
    meta = {
        "tag": args.tag,
        "train_months": [p.stem[-6:] for p in train_paths],
        "valid_months": [p.stem[-6:] for p in valid_paths],
        "test_months": [p.stem[-6:] for p in test_paths],
        "model_feature_cols": p1.MODEL_FEATURE_COLS,
        "use_holiday": use_holiday,
        "n_estimators": args.n_estimators,
        "learning_rate": args.learning_rate,
        "num_leaves": args.num_leaves,
        "early_stopping_rounds": args.early_stopping_rounds,
        "station_categories": len(station_dtype.categories),
        "sample_frac": args.sample_frac,
        "train_time_sec": result.train_time_sec,
        "peak_memory_mb": mem.peak_mb,
        "eval": reports,
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
    }
    (artifact_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    print(f"\n아티팩트 저장: {artifact_dir}")


if __name__ == "__main__":
    main()
