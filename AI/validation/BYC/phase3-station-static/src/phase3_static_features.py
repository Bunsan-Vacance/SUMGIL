"""Phase 3 — station 정적 feature(district/rack_count/lat/lon/지하철거리/버스거리) 추가.

Phase 2(historical profile)까지의 feature에 station 정적 feature 6개를 추가했을 때
Phase 2 대비 성능이 개선되는지 측정한다.

⚠️ 결론 scope 제한: 버스정류장 데이터가 2026-09-02 시점 스냅샷이라, 이 실험은
"2026년 9월 기준 대중교통 접근성 proxy 추가 효과"를 측정하는 것이지 "2024년 실측
접근성 효과"가 아니다. (station_distance_report.md 참고)

⚠️ 전역 FEATURE_COLS 갱신 타이밍 주의: read_split_with_targets()가 호출 시점의
p1.FEATURE_COLS로 원본 CSV의 usecols를 정하기 때문에, static feature를 아직 CSV에
없는 컬럼으로 FEATURE_COLS에 먼저 넣어버리면 read가 깨진다. 그래서 이 스크립트는
"데이터 로드 -> historical profile -> static feature merge" 이후, 모델 학습 직전에
딱 한 번만 전역을 갱신한다.

실행 예:
    python phase3_static_features.py --file-tag top300
    python phase3_static_features.py --file-tag stratified300
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "q3-seasonal-dataset-check" / "src"))
import phase2_historical_profile as p2

STATIC_FEATURE_COLS = ["district_code", "rack_count", "lat", "lon", "dist_subway_m", "dist_bus_m"]

STATION_DISTANCE_FEATURES_PATH = (
    Path(__file__).resolve().parents[4]
    / "data"
    / "EXTERNAL"
    / "station"
    / "processed"
    / "station_distance_features.csv"
)

# Phase 2 baseline 경로 (검증 완료: AI/validation/BYC/q3-seasonal-dataset-check/outputs)
PHASE2_OUTPUTS_DIR = Path(__file__).resolve().parents[2] / "q3-seasonal-dataset-check" / "outputs"
PHASE2_METRICS = {
    "top300": PHASE2_OUTPUTS_DIR / "top300" / "phase2" / "metrics.json",
    # key는 sample 이름 규칙("stratified300") 그대로, 폴더명만 "stratified"(300 없음) — 의도된 매핑
    "stratified300": PHASE2_OUTPUTS_DIR / "stratified" / "phase2" / "metrics.json",
}

CAVEATS = [
    (
        "버스정류장 위치 데이터는 2026-09-02 시점 스냅샷으로, 예측 대상 기간(2023Q4~2025Q3)보다 "
        "미래 인프라 정보다. '2026년 9월 기준 대중교통 접근성 proxy'로만 해석해야 하며, "
        "'2024년 당시 실제 접근성 효과'로 해석하지 않는다."
    ),
    (
        "지하철 역사마스터 데이터는 정확한 스냅샷 날짜를 확인할 수 없다. GTX-A(운정 포함)·9호선 "
        "연장·별내선·진접선이 포함돼 있어 '최소 2024년 이후 인프라'라는 하한선만 추정 가능하다."
    ),
    (
        "rack_count는 station_distance_features.csv 값을 사용한다. top300/stratified300 모두 "
        "2024/2025 static값이 동일함을 1단계에서 확인했으므로 시점별 선택 로직은 불필요하다."
    ),
    (
        "district_code는 기존 station_code와 동일한 deterministic ID encoding(train∪valid∪test "
        "합집합 카테고리 + 공유 CategoricalDtype)이다."
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 3 station 정적 feature 추가 비교.")
    script_dir = Path(__file__).resolve()
    ai_dir = script_dir.parents[4]
    parser.add_argument(
        "--data-dir", default=None, help="지정 안 하면 --file-tag에 맞는 폴더를 자동 선택"
    )
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--train-path", nargs="+")
    parser.add_argument("--valid-path", nargs="+")
    parser.add_argument("--test-path", nargs="+")
    parser.add_argument("--rf-max-rows", type=int, default=2_000_000)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--file-tag", default="top300", choices=["top300", "stratified300"])
    parser.add_argument("--perm-max-rows-per-horizon", type=int, default=50_000)
    args = parser.parse_args()

    if args.data_dir is None:
        # top300과 stratified300은 서로 다른 폴더에 있다 — file-tag로 자동 선택
        data_dir_name = (
            "stock_q3_mapped_netflow_v5"
            if args.file_tag == "top300"
            else "stock_q3_mapped_netflow_stratified300"
        )
        args.data_dir = str(ai_dir / "data" / "processed" / "BYC" / data_dir_name)
    if args.output_dir is None:
        out_tag = "top300" if args.file_tag == "top300" else "stratified"
        args.output_dir = str(script_dir.parents[1] / "outputs" / out_tag / "phase3")
    return args


def add_district_code(train: pd.DataFrame, valid: pd.DataFrame, test: pd.DataFrame) -> list[str]:
    """station_code와 동일한 패턴: train∪valid∪test 합집합 카테고리 + 공유 CategoricalDtype."""
    categories = sorted(set(train["district"]) | set(valid["district"]) | set(test["district"]))
    dtype = pd.CategoricalDtype(categories=categories)
    for df in (train, valid, test):
        df["district_code"] = df["district"].astype(dtype).cat.codes
    return categories


def merge_static_features(
    df: pd.DataFrame, station_features: pd.DataFrame, split_name: str
) -> pd.DataFrame:
    before_len = len(df)
    merged = df.merge(
        station_features[
            ["od_station_id", "district", "rack_count", "lat", "lon", "dist_subway_m", "dist_bus_m"]
        ],
        on="od_station_id",
        how="left",
    )
    assert (
        len(merged) == before_len
    ), f"{split_name}: merge 전후 row 수 불일치 ({before_len} -> {len(merged)})"
    return merged


def stratified_sample_by_horizon(
    df: pd.DataFrame, cap_per_horizon: int, random_state: int
) -> pd.DataFrame:
    parts = []
    for horizon in p2.HORIZONS:
        sub = df[df["horizon_min"] == horizon]
        if len(sub) > cap_per_horizon:
            sub = sub.sample(n=cap_per_horizon, random_state=random_state)
        parts.append(sub)
    return pd.concat(parts, ignore_index=True)


def compute_permutation_importance(
    model_name: str, model, sample_df: pd.DataFrame, random_state: int, n_repeats: int = 5
) -> list[dict]:
    """static feature 6개에 대해서만 직접 permutation importance를 계산한다.

    feature별 permutation importance는 다른 feature와 독립적으로 계산되므로(그 컬럼
    하나만 섞고 나머지는 그대로 둔 채 재예측), sklearn.permutation_importance로 전체
    feature를 다 돌리고 6개만 추리는 것과 결과가 수학적으로 동일하다 — 여기선 처음부터
    static 6개만 돌려서 연산량을 4.5배(27->6 feature) 줄인다.
    """
    x, y = p2.p1.make_xy(sample_df)
    rng = np.random.default_rng(random_state)
    baseline_mae = mean_absolute_error(y, model.predict(x))

    rows = []
    for feature in STATIC_FEATURE_COLS:
        increases = []
        for _ in range(n_repeats):
            x_shuffled = x.copy()
            x_shuffled[feature] = rng.permutation(x_shuffled[feature].to_numpy())
            increases.append(mean_absolute_error(y, model.predict(x_shuffled)) - baseline_mae)
        rows.append(
            {
                "model": model_name,
                "feature": feature,
                "mae_increase_mean": float(np.mean(increases)),
                "mae_increase_std": float(np.std(increases)),
            }
        )
    return rows


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    assert PHASE2_METRICS[
        args.file_tag
    ].exists(), f"Phase 2 baseline metrics 없음: {PHASE2_METRICS[args.file_tag]}"
    assert (
        STATION_DISTANCE_FEATURES_PATH.exists()
    ), f"station 거리 feature 없음: {STATION_DISTANCE_FEATURES_PATH}"

    # === 1~3. 기존 Phase 2 흐름 그대로 (static feature 개입 전) ===
    print("split 로드...")
    train_df = p2.read_split_with_targets(
        data_dir, "train", args.file_tag, p2.resolve_split_path(args, "train")
    )
    valid_df = p2.read_split_with_targets(
        data_dir, "valid", args.file_tag, p2.resolve_split_path(args, "valid")
    )
    test_df = p2.read_split_with_targets(
        data_dir, "test", args.file_tag, p2.resolve_split_path(args, "test")
    )
    train_df, valid_df, test_df, station_categories = p2.p1.add_station_code(
        train_df, valid_df, test_df
    )

    print("historical profile fit (train만 사용)...")
    profile = p2.HistoricalProfileBuilder()
    profile.fit(train_df)
    train_df = profile.transform(train_df)
    valid_df = profile.transform(valid_df)
    test_df = profile.transform(test_df)

    # === 4. static feature merge ===
    print("station 정적 feature merge...")
    station_features = pd.read_csv(STATION_DISTANCE_FEATURES_PATH)
    assert station_features[
        "od_station_id"
    ].is_unique, "station_distance_features.csv od_station_id 중복"

    union_ids = set(station_features["od_station_id"])
    for name, df in [("train", train_df), ("valid", valid_df), ("test", test_df)]:
        missing = set(df["od_station_id"]) - union_ids
        assert not missing, f"{name}: station_distance_features.csv에 없는 station {len(missing)}개"

    train_df = merge_static_features(train_df, station_features, "train")
    valid_df = merge_static_features(valid_df, station_features, "valid")
    test_df = merge_static_features(test_df, station_features, "test")

    # === 5. district_code 생성 ===
    district_categories = add_district_code(train_df, valid_df, test_df)

    for name, df in [("train", train_df), ("valid", valid_df), ("test", test_df)]:
        na_counts = df[STATIC_FEATURE_COLS].isna().sum()
        assert na_counts.sum() == 0, f"{name}: static feature 결측 발견\n{na_counts}"
        assert (df["district_code"] == -1).sum() == 0, f"{name}: district_code unknown(-1) 존재"

    # === 여기서만 전역 갱신 (모델 학습 직전, 데이터 로드 다 끝난 뒤) ===
    FEATURE_COLS = p2.FEATURE_COLS + STATIC_FEATURE_COLS
    assert len(FEATURE_COLS) == len(
        set(FEATURE_COLS)
    ), "FEATURE_COLS 중복 — p2.FEATURE_COLS와 static 6개가 겹침"
    MODEL_FEATURE_COLS = FEATURE_COLS + ["station_code"]
    assert len(MODEL_FEATURE_COLS) == len(set(MODEL_FEATURE_COLS)), "MODEL_FEATURE_COLS 중복"
    assert MODEL_FEATURE_COLS.count("station_code") == 1
    assert all(c in MODEL_FEATURE_COLS for c in STATIC_FEATURE_COLS)
    p2.p1.FEATURE_COLS = FEATURE_COLS
    p2.p1.MODEL_FEATURE_COLS = MODEL_FEATURE_COLS

    print(
        f"Rows: train={len(train_df):,}, valid={len(valid_df):,}, test={len(test_df):,}, "
        f"stations={len(station_categories):,}, districts={len(district_categories)}, "
        f"feature수={len(MODEL_FEATURE_COLS)}"
    )

    # === 6. Naive_Profile + 3모델 학습 ===
    print("Naive_Profile fit...")
    naive_model = p2.p1.NaiveProfileModel()
    naive_model.fit(train_df)
    fit_results: list = [p2.p1.FitResult("Naive_Profile", naive_model, 0.0)]

    print("RandomForest 학습...")
    fit_results.append(p2.p1.fit_random_forest(train_df, args.rf_max_rows, args.random_state))
    print("XGBoost 학습...")
    fit_results.append(p2.p1.fit_xgboost(train_df, valid_df, args.random_state))
    print("LightGBM 학습...")
    fit_results.append(p2.p1.fit_lightgbm(train_df, valid_df, args.random_state))

    comparison_rows, horizon_rows, importance_rows, perm_rows = [], [], [], []
    fitted_models, skipped = {}, {}

    perm_sample = stratified_sample_by_horizon(
        valid_df, args.perm_max_rows_per_horizon, args.random_state
    )

    for result in fit_results:
        if result.skipped_reason:
            print(f"Skipping {result.name}: {result.skipped_reason}")
            skipped[result.name] = result.skipped_reason
            continue
        print(f"Evaluating {result.name} (test)...")
        fitted_models[result.name] = result.model
        comparison_rows.append(
            p2.p1.evaluate_model(result.name, result.model, test_df, result.train_time_sec)
        )
        horizon_rows.extend(
            p2.p1.evaluate_by_horizon(result.name, result.model, test_df, result.train_time_sec)
        )
        importance_rows.extend(p2.p1.feature_importance_rows(result.name, result.model))

        if result.name != "Naive_Profile":
            print(f"Permutation importance ({result.name})...")
            perm_rows.extend(
                compute_permutation_importance(
                    result.name, result.model, perm_sample, args.random_state
                )
            )

    comparison = pd.DataFrame(comparison_rows).sort_values("mae")
    by_horizon = pd.DataFrame(horizon_rows).sort_values(["horizon_min", "mae"])
    feature_importance = pd.DataFrame(importance_rows)
    if not feature_importance.empty:
        feature_importance = feature_importance.sort_values(
            ["model", "importance"], ascending=[True, False]
        )
    permutation_importance_df = pd.DataFrame(perm_rows).sort_values(
        ["model", "mae_increase_mean"], ascending=[True, False]
    )

    best_model_name, best_reason = p2.p1.select_best(comparison)
    best_model = fitted_models[best_model_name]

    comparison.to_csv(output_dir / "model_comparison.csv", index=False)
    by_horizon.to_csv(output_dir / "model_comparison_by_horizon.csv", index=False)
    feature_importance.to_csv(output_dir / "feature_importance.csv", index=False)
    permutation_importance_df.to_csv(output_dir / "permutation_importance.csv", index=False)
    joblib.dump(
        {
            "model_name": best_model_name,
            "model": best_model,
            "feature_cols": FEATURE_COLS,
            "model_feature_cols": MODEL_FEATURE_COLS,
            "station_categories": station_categories,
            "district_categories": district_categories,
            "shortage_threshold": p2.p1.SHORTAGE_THRESHOLD,
        },
        output_dir / "best_model.pkl",
    )

    # === Phase 2 baseline과 비교 ===
    phase2_metrics = json.loads(PHASE2_METRICS[args.file_tag].read_text(encoding="utf-8"))
    phase2_naive = next(r for r in phase2_metrics["comparison"] if r["model"] == "Naive_Profile")
    phase3_naive = comparison[comparison["model"] == "Naive_Profile"].iloc[0]
    naive_consistency_ok = bool(abs(phase3_naive["mae"] - phase2_naive["mae"]) < 1e-6)

    metrics = {
        "best_model": best_model_name,
        "best_reason": best_reason,
        "skipped_models": skipped,
        "row_counts": {
            "train": len(train_df),
            "valid": len(valid_df),
            "test": len(test_df),
            "station_categories": len(station_categories),
            "district_categories": len(district_categories),
        },
        "model_feature_cols": MODEL_FEATURE_COLS,
        "static_feature_cols": STATIC_FEATURE_COLS,
        "phase2_metrics_path": str(PHASE2_METRICS[args.file_tag]),
        "naive_profile_consistency_check": {
            "phase2_mae": phase2_naive["mae"],
            "phase3_mae": float(phase3_naive["mae"]),
            "consistent": naive_consistency_ok,
        },
        "comparison": comparison.to_dict(orient="records"),
        "by_horizon": by_horizon.to_dict(orient="records"),
        "caveats": CAVEATS,
    }
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\nBest model: {best_model_name}")
    print(best_reason)
    print(f"Naive_Profile 정합성(Phase2 vs Phase3 MAE 일치): {naive_consistency_ok}")
    print(comparison.to_string(index=False))
    print("\n=== Phase 2 baseline (참고) ===")
    print(pd.DataFrame(phase2_metrics["comparison"]).to_string(index=False))


if __name__ == "__main__":
    main()
