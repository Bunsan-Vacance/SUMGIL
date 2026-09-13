"""전체 대여소 avg(Naive_Profile) baseline — station×요일×시간×horizon 과거 평균.

`build_full_station_netflow.py`가 만든 월별 parquet(11개 train + 1개 valid + 3개 test,
250.7M행)을 대상으로 한다. train 전체를 한 번에 메모리에 올리지 않고, 파일마다 필요한
5개 컬럼만 읽어 그룹별 **부분합(sum·count)**을 누적한 뒤 나눠서 평균을 낸다 —
sum/count를 파일 단위로 합산하면 전체를 한 번에 읽은 것과 수학적으로 동일한 평균이
나온다(MapReduce의 mean과 같은 원리).

그룹 키·fallback 순서(station×dow×hour×horizon → station×horizon → horizon 전체)는
`q3-seasonal-dataset-check/src/phase1_baseline.py`의 `NaiveProfileModel`과 동일하게
맞춘다 — fit()만 스트리밍으로 새로 구현하고, predict()는 그 클래스를 그대로 재사용한다.

실행:
    python avg_baseline_full.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "q3-seasonal-dataset-check" / "src")
)
from phase1_baseline import (  # noqa: E402
    PROFILE_KEYS_FULL,
    PROFILE_KEYS_GLOBAL,
    PROFILE_KEYS_STATION_HORIZON,
    TARGET_COL,
    NaiveProfileModel,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "outputs" / "full-run"
OUT_DIR = Path(__file__).resolve().parents[1] / "outputs" / "avg-baseline"
NEEDED_COLS = ["od_station_id", "day_of_week", "hour", "horizon_min", TARGET_COL]


def _monthly_paths(prefix: str) -> list[Path]:
    paths = sorted(DATA_DIR.glob(f"{prefix}_netflow_q3_mapped_full_*.parquet"))
    if not paths:
        raise FileNotFoundError(f"{DATA_DIR}에 {prefix}_netflow_q3_mapped_full_*.parquet 없음")
    return paths


def _partial_agg(paths: list[Path], keys: list[str]) -> pd.DataFrame:
    """여러 parquet을 순회하며 그룹별 (sum, count) 부분합을 누적한다."""
    total = None
    for p in paths:
        df = pd.read_parquet(p, columns=NEEDED_COLS)
        g = df.groupby(keys)[TARGET_COL].agg(["sum", "count"])
        total = g if total is None else total.add(g, fill_value=0)
        del df
    return total


def fit_naive_profile_streaming(train_paths: list[Path]) -> NaiveProfileModel:
    """NaiveProfileModel.fit()과 동일한 3단 profile을 스트리밍 부분합으로 만든다."""
    model = NaiveProfileModel()

    agg_full = _partial_agg(train_paths, PROFILE_KEYS_FULL)
    model.profile_full = (agg_full["sum"] / agg_full["count"]).rename("_pred").reset_index()

    agg_sh = _partial_agg(train_paths, PROFILE_KEYS_STATION_HORIZON)
    model.profile_station_horizon = (
        (agg_sh["sum"] / agg_sh["count"]).rename("_pred_sh").reset_index()
    )

    agg_g = _partial_agg(train_paths, PROFILE_KEYS_GLOBAL)
    model.profile_global = (agg_g["sum"] / agg_g["count"]).rename("_pred_g").reset_index()
    return model


def evaluate(model: NaiveProfileModel, paths: list[Path], label: str) -> dict:
    """valid/test 평가 — 파일별로 predict한 뒤 오차 누적(전체를 한 번에 안 올림).

    R²에 필요한 분산도 2-pass 없이 1-pass로: Var(y) = E[y^2] - E[y]^2.

    target_net_flow가 NaN인 행이 소수 섞여 있다(월 단위로 끊어 처리한 부작용 —
    각 달 마지막 몇 슬롯은 forward rolling window가 그 달 파일 안에서 미래 데이터를
    못 찾아 NaN이 됨, station당 월말 6슬롯 정도, 전체의 0.1% 미만). numpy sum은
    NaN 하나만 있어도 전체를 NaN으로 만들어서 반드시 걸러내야 한다 — 값을 채우지
    않고 그 행만 평가에서 제외한다(원칙 8: 표본 부족 구간에 값을 채우지 않는다).
    """
    abs_err_sum = 0.0
    sq_err_sum = 0.0
    y_sum = 0.0
    y_sq_sum = 0.0
    n = 0
    n_dropped_nan = 0
    classes = ["decrease", "stable", "increase"]
    # macro-F1을 스트리밍으로 내려고 클래스별 TP/FP/FN을 파일마다 누적한다
    # (phase1_baseline.direction_class와 동일 기준: <0 decrease, >0 increase, ==0 stable).
    tp = dict.fromkeys(classes, 0)
    fp = dict.fromkeys(classes, 0)
    fn = dict.fromkeys(classes, 0)
    correct = 0
    for p in paths:
        df = pd.read_parquet(p, columns=NEEDED_COLS)
        actual = df[TARGET_COL].to_numpy(dtype="float64")
        valid_mask = ~np.isnan(actual)
        n_dropped_nan += int((~valid_mask).sum())
        if not valid_mask.all():
            df = df.loc[valid_mask]
            actual = actual[valid_mask]
        pred = model.predict(df)
        abs_err_sum += np.abs(actual - pred).sum()
        sq_err_sum += ((actual - pred) ** 2).sum()
        y_sum += actual.sum()
        y_sq_sum += (actual**2).sum()
        n += len(df)

        actual_c = np.where(actual < 0, "decrease", np.where(actual > 0, "increase", "stable"))
        pred_c = np.where(pred < 0, "decrease", np.where(pred > 0, "increase", "stable"))
        correct += int((actual_c == pred_c).sum())
        for c in classes:
            tp[c] += int(((actual_c == c) & (pred_c == c)).sum())
            fp[c] += int(((actual_c != c) & (pred_c == c)).sum())
            fn[c] += int(((actual_c == c) & (pred_c != c)).sum())
        del df
    mae = abs_err_sum / n
    mse = sq_err_sum / n
    rmse = mse**0.5
    y_mean = y_sum / n
    direction_accuracy = correct / n
    f1_scores = []
    for c in classes:
        precision = tp[c] / (tp[c] + fp[c]) if (tp[c] + fp[c]) else 0.0
        recall = tp[c] / (tp[c] + fn[c]) if (tp[c] + fn[c]) else 0.0
        f1_scores.append(2 * precision * recall / (precision + recall) if (precision + recall) else 0.0)
    direction_macro_f1 = sum(f1_scores) / len(f1_scores)
    variance = y_sq_sum / n - y_mean**2
    r2 = 1 - mse / variance if variance > 0 else float("nan")
    return {
        "split": label,
        "rows": n,
        "rows_dropped_nan_target": n_dropped_nan,
        "mae": mae,
        "rmse": rmse,
        "r2": r2,
        "direction_accuracy": direction_accuracy,
        "direction_macro_f1": direction_macro_f1,
    }


def main() -> None:
    train_paths = _monthly_paths("train")
    valid_paths = _monthly_paths("valid")
    test_paths = _monthly_paths("test")
    print(f"train {len(train_paths)}개 파일, valid {len(valid_paths)}개, test {len(test_paths)}개")

    t0 = time.time()
    model = fit_naive_profile_streaming(train_paths)
    print(
        f"fit 완료: {time.time() - t0:.1f}초, "
        f"profile_full {len(model.profile_full):,}행, "
        f"profile_station_horizon {len(model.profile_station_horizon):,}행, "
        f"profile_global {len(model.profile_global):,}행"
    )

    results = []
    for paths, label in [(valid_paths, "valid"), (test_paths, "test")]:
        t0 = time.time()
        result = evaluate(model, paths, label)
        result["elapsed_sec"] = round(time.time() - t0, 1)
        results.append(result)
        print(
            f"[{label}] rows={result['rows']:,} mae={result['mae']:.4f} "
            f"rmse={result['rmse']:.4f} r2={result['r2']:.4f} "
            f"dir_acc={result['direction_accuracy']:.4f} "
            f"dir_f1={result['direction_macro_f1']:.4f} ({result['elapsed_sec']}초)"
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    model.profile_full.to_parquet(OUT_DIR / "profile_full.parquet", index=False)
    model.profile_station_horizon.to_parquet(OUT_DIR / "profile_station_horizon.parquet", index=False)
    model.profile_global.to_parquet(OUT_DIR / "profile_global.parquet", index=False)
    pd.DataFrame(results).to_csv(OUT_DIR / "eval_report.csv", index=False)
    print(f"\n저장 완료: {OUT_DIR}")


if __name__ == "__main__":
    main()
