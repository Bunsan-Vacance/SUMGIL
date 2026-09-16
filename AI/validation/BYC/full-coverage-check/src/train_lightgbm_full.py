"""전체 대여소 LightGBM 재학습 — `build_full_station_netflow.py` 산출물(월별 parquet) 대상.

`q3-seasonal-dataset-check/src/phase1_baseline.py`의 feature 정의·station dtype 처리·
LightGBM 하이퍼파라미터·평가 지표(MAE/RMSE/R²/direction_accuracy)를 그대로 재사용하고,
데이터 로딩만 우리 parquet 산출물에 맞게 새로 짠다.

**먼저 소규모로 검증한다** — `--train-months`로 2~3개월만 골라 시간·메모리를 재고,
그 결과를 보고 전체(11개월, 186.8M행)를 그대로 태울지/샘플링할지/월별 warm-start로
갈지 정한다(AI/CLAUDE.md: 표본으로 먼저 끝까지 도는지 확인한 뒤 전체를 돌린다).

target_net_flow가 NaN인 행(월 경계 forward rolling 부작용, avg_baseline_full.py에서도
확인됨)은 make_xy()의 fillna(0)에 맡기지 않고 **명시적으로 제외**한다 — 0으로 채우면
"그 시점엔 순증감이 0이었다"는 잘못된 신호를 모델에 준다.

실행 예 (소규모 검증):
    python train_lightgbm_full.py --train-months 202401 202402 --tag smoke

전체 실행:
    python train_lightgbm_full.py --tag full
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
from phase1_baseline import (
    FEATURE_COLS,
    MODEL_FEATURE_COLS,
    TARGET_COL,
    apply_station_code,
    build_station_dtype,
    direction_metrics,
    downcast_memory,
    fit_lightgbm,
    make_xy,
    rmse,
    wape,
)
from sklearn.metrics import mean_absolute_error, r2_score

DATA_DIR = Path(__file__).resolve().parents[1] / "outputs" / "full-run"
AI_DIR = Path(__file__).resolve().parents[4]
MODELS_DIR = AI_DIR / "models" / "BIKE"
READ_COLS = ["od_station_id", *FEATURE_COLS, TARGET_COL]


def _monthly_paths(prefix: str, months: list[str] | None = None) -> list[Path]:
    paths = sorted(DATA_DIR.glob(f"{prefix}_netflow_q3_mapped_full_*.parquet"))
    if not paths:
        raise FileNotFoundError(f"{DATA_DIR}에 {prefix}_netflow_q3_mapped_full_*.parquet 없음")
    if months:
        paths = [p for p in paths if any(m in p.stem for m in months)]
    return paths


def load_paths(
    paths: list[Path], sample_frac: float | None = None, random_state: int = 42
) -> pd.DataFrame:
    """여러 parquet을 필요한 컬럼만 읽어 합치고, NaN target을 제외한다.

    sample_frac이 있으면 **파일별로** 그 비율만큼 샘플링한 뒤 concat한다 — 파일 단위로
    샘플링해야 로딩 도중 피크 메모리도 같이 줄어든다(다 합친 뒤 샘플링하면 합치는
    순간엔 여전히 전체가 메모리에 있어야 함). 12개월 계절성은 그대로 유지된다
    (달마다 있는 그대로에서 비율만 줄이는 것 — 특정 달을 통째로 빼지 않음).
    """
    frames = []
    for p in paths:
        df = pd.read_parquet(p, columns=READ_COLS)
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
    return downcast_memory(df)


def scan_station_ids_parquet(paths: list[Path]) -> set[str]:
    """od_station_id 컬럼만 훑어서 station id 집합을 얻는다(전체 로드 없이)."""
    ids: set[str] = set()
    for p in paths:
        col = pq.ParquetFile(p).read(columns=["od_station_id"])["od_station_id"]
        ids |= set(col.to_pylist())
    return ids


def evaluate(model, df: pd.DataFrame, label: str) -> dict:
    x, y = make_xy(df)
    pred = model.predict(x)
    acc, macro_f1 = direction_metrics(y.to_numpy(), pred)
    return {
        "split": label,
        "rows": len(df),
        "mae": float(mean_absolute_error(y, pred)),
        "rmse": float(rmse(y, pred)),
        "r2": float(r2_score(y, pred)),
        "wape": float(wape(y.to_numpy(), pred)),
        "direction_accuracy": float(acc),
        "direction_macro_f1": float(macro_f1),
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--train-months", nargs="+", default=None, help="예: 202401 202402 (생략 시 전체 11개월)"
    )
    p.add_argument("--valid-months", nargs="+", default=None, help="생략 시 전체(2024-12)")
    p.add_argument("--test-months", nargs="+", default=None, help="생략 시 전체(2025 Q3 3개월)")
    p.add_argument("--random-state", type=int, default=42)
    p.add_argument(
        "--sample-frac",
        type=float,
        default=None,
        help="train만 파일별로 이 비율만큼 샘플링(예: 0.45) — 11개월 전체(186.8M행)는 "
        "메모리 역산 ~47GB라 그대로 못 태움(5개월/77.3M행 실측 19.7GB). 12개월 계절성은 "
        "유지한 채 밀도만 줄인다.",
    )
    p.add_argument(
        "--tag", default="full", help="아티팩트 디렉터리 태그: models/BIKE/<tag>_<시각>/"
    )
    p.add_argument(
        "--out-dir", default=str(Path(__file__).resolve().parents[1] / "outputs" / "lightgbm-full")
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    train_paths = _monthly_paths("train", args.train_months)
    valid_paths = _monthly_paths("valid", args.valid_months)
    test_paths = _monthly_paths("test", args.test_months)
    print(f"train {len(train_paths)}개 파일, valid {len(valid_paths)}개, test {len(test_paths)}개")

    with PeakMemoryTracker() as mem:
        t0 = time.time()
        # station dtype은 이번 실행에 실제로 쓰는 파일들(train/valid/test) 전체를 훑어서
        # 만든다 — Phase 2.5에서 train∩valid만으로 만들었다가 test에서 unknown 나던
        # 문제(stratified300)를 다시 겪지 않으려고 처음부터 합집합으로 간다.
        station_ids = (
            scan_station_ids_parquet(train_paths)
            | scan_station_ids_parquet(valid_paths)
            | scan_station_ids_parquet(test_paths)
        )
        station_dtype = build_station_dtype(station_ids)
        print(
            f"station dtype 구성: {len(station_dtype.categories):,}개 station "
            f"({time.time() - t0:.1f}초, 피크메모리 {mem.peak_mb}MB)"
        )

        t0 = time.time()
        train_df = load_paths(
            train_paths, sample_frac=args.sample_frac, random_state=args.random_state
        )
        apply_station_code(train_df, station_dtype, "train")
        frac_note = f", sample_frac={args.sample_frac}" if args.sample_frac else ""
        print(
            f"train 로드: {len(train_df):,}행 ({time.time() - t0:.1f}초, 피크메모리 {mem.peak_mb}MB{frac_note})"
        )

        t0 = time.time()
        valid_df = load_paths(valid_paths)
        apply_station_code(valid_df, station_dtype, "valid")
        print(
            f"valid 로드: {len(valid_df):,}행 ({time.time() - t0:.1f}초, 피크메모리 {mem.peak_mb}MB)"
        )

        t0 = time.time()
        result = fit_lightgbm(train_df, valid_df, args.random_state)
        if result.model is None:
            raise RuntimeError(result.skipped_reason)
        print(f"LightGBM 학습 완료: {time.time() - t0:.1f}초, 피크메모리 {mem.peak_mb}MB")

        reports = [evaluate(result.model, valid_df, "valid")]
        del train_df, valid_df

        for p in test_paths:
            t0 = time.time()
            test_df = load_paths([p])
            apply_station_code(test_df, station_dtype, f"test:{p.stem}")
            r = evaluate(result.model, test_df, f"test:{p.stem[-6:]}")
            r["elapsed_sec"] = round(time.time() - t0, 1)
            reports.append(r)
            print(
                f"[{r['split']}] rows={r['rows']:,} mae={r['mae']:.4f} rmse={r['rmse']:.4f} "
                f"r2={r['r2']:.4f} wape={r['wape']:.4f} dir_acc={r['direction_accuracy']:.4f} "
                f"({r['elapsed_sec']}초, 피크메모리 {mem.peak_mb}MB)"
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
    meta = {
        "tag": args.tag,
        "train_months": [p.stem[-6:] for p in train_paths],
        "valid_months": [p.stem[-6:] for p in valid_paths],
        "test_months": [p.stem[-6:] for p in test_paths],
        "model_feature_cols": MODEL_FEATURE_COLS,
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
