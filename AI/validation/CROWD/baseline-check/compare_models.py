"""lookup 베이스라인 vs LightGBM·RandomForest·XGBoost 잔차 예측 비교.

87번(예측 알고리즘 후보 검증)의 핵심 산출물. **직접 승하차를 예측시키지 않는다** —
`day_type`·`station_no`·`time_slot` 원본 컬럼으로 트리 모델이 승하차를 직접 예측하게
했더니, 이 세 컬럼의 조합(약 2만 개)을 LightGBM의 근사 범주형 분할이 lookup 테이블(단순
groupby 평균)만큼 정확히 재현하지 못해 세 모델 다 베이스라인보다 나빴다(자세한 경위는
`features.py` 참고).

그래서 각 후보는 **베이스라인이 이미 설명한 몫을 건드리지 않고, 잔차(실측 − 베이스라인
예측)만 기상·이벤트로 예측**한다. 최종 예측은 `베이스라인 예측 + 모델이 맞춘 잔차`로
재구성해 실측과 비교한다 — 이러면 "베이스라인을 재현하는 능력"이 아니라 "베이스라인이
못 본 것을 추가로 잡아내는 능력"만 순수하게 측정된다.

실행:
    cd AI
    python validation/CROWD/baseline-check/compare_models.py [feature_set ...] [옵션]
    (feature_set 생략 시 "weather_events" — features.FEATURE_SETS 참고. 여러 세트를 나열하면
     데이터 로딩·lookup fit·파생 컬럼을 한 번만 하고 세트마다 학습만 반복한다.)
    옵션:
      --models=a,b      후보 지정. 기본은 models.DEFAULT_CANDIDATES(lightgbm,xgboost).
      --all-models      RandomForest까지 세 후보 전부(느리다 — 세트당 3~5분 추가).
      --rebuild-cache   파생 패널 캐시를 무시하고 다시 만든다(derived_features 참고).
      --save-results=path.parquet   세트별 결과 표를 feature_set 컬럼을 붙여 parquet로 저장
                        (136 그림 입력 — 수치를 그림 코드에 하드코딩하지 않기 위해).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from baseline import DayTypeLookupBaseline, regression_metrics, residuals
from dataset import load_panel, time_split
from derived_features import load_or_build_derived, needs_derived_columns, neighbor_maps_for
from features import FEATURE_SETS, build_matrix

from models import CANDIDATES, DEFAULT_CANDIDATES, fit_predict


def compare_many(
    feature_sets: list[str],
    models: list[str] | None = None,
    rebuild_cache: bool = False,
) -> dict[str, pd.DataFrame]:
    """여러 세트를 한 프로세스에서 비교한다 — 데이터 로딩·lookup fit·파생은 한 번만.

    세트 하나가 끝날 때마다 표를 바로 출력하므로 중간에 끊겨도 끝난 세트의 결과는 남는다.
    """
    models = models or DEFAULT_CANDIDATES
    panel = load_panel(with_events=True)
    train, test = time_split(panel)
    lookup = DayTypeLookupBaseline().fit(train)

    if any(needs_derived_columns(FEATURE_SETS[fs]) for fs in feature_sets):
        # 89번 파생 피처(인접역·환승 노드·시차) — 시차가 분할 경계를 넘어 참조해야 하므로
        # 전체 패널에 붙인 뒤 다시 나눈다. 잔차는 학습 구간 lookup 기준(타깃 잔차와 동일).
        _, _, gaps = neighbor_maps_for(panel)
        if len(gaps):
            print("[안내] 토폴로지에 있으나 패널에 없는 역(양옆 역이 인접으로 이어진다):")
            print(gaps.to_string(index=False))
        train, test = time_split(load_or_build_derived(panel, lookup, force=rebuild_cache))

    train_resid = residuals(lookup, train)
    test_resid = residuals(lookup, test)

    results: dict[str, pd.DataFrame] = {}
    for feature_set in feature_sets:
        print(f"\n[feature_set] {feature_set} = {FEATURE_SETS[feature_set]}", flush=True)
        result = _compare_split(feature_set, models, train, test, train_resid, test_resid, lookup)
        results[feature_set] = result
        print(result.round(2).to_string(index=False), flush=True)
    return results


def compare(feature_set: str = "weather_events", models: list[str] | None = None) -> pd.DataFrame:
    """세트 하나 비교 — `compare_many`의 단일 세트 편의 함수."""
    return compare_many([feature_set], models)[feature_set]


def _compare_split(
    feature_set: str,
    models: list[str],
    train: pd.DataFrame,
    test: pd.DataFrame,
    train_resid: pd.DataFrame,
    test_resid: pd.DataFrame,
    lookup: DayTypeLookupBaseline,
) -> pd.DataFrame:
    X_train = build_matrix(train, feature_set)
    X_test = build_matrix(test, feature_set)

    rows: list[dict] = []
    for target in lookup.targets:
        baseline_pred_test = test_resid[f"{target}_pred"]
        rows.append(
            {
                "model": "lookup_baseline",
                "target": target,
                **regression_metrics(test[target], baseline_pred_test),
            }
        )

        y_train_resid = train_resid[f"{target}_resid"]
        for name in models:
            t0 = time.time()
            pred_resid = fit_predict(name, X_train, y_train_resid, X_test)
            final_pred = baseline_pred_test.to_numpy() + pred_resid.to_numpy()
            elapsed = time.time() - t0
            rows.append(
                {
                    "model": name,
                    "target": target,
                    **regression_metrics(test[target], pd.Series(final_pred)),
                    "학습_초": round(elapsed, 1),
                }
            )
            print(f"[{name}/{target}] {elapsed:.1f}s", flush=True)

    return add_improvement_columns(pd.DataFrame(rows))


def add_improvement_columns(result: pd.DataFrame) -> pd.DataFrame:
    """베이스라인 대비 개선폭을 붙인다 — 상대(%)와 절대(명) 양쪽으로.

    RMSE·MAE는 낮을수록 좋아서 `1 − 모델/베이스라인`, R²는 높을수록 좋아서 차이(%p)로
    계산한다. **절대 열(`_개선_명`)을 같이 내는 이유**는 상대 개선율만으로는 실질적 의미를
    판단할 수 없기 때문이다 — "RMSE 1.5% 개선"이 시간대당 몇 명인지 보여야 서비스에서
    체감되는 차이인지 말할 수 있다(7단계 판단 기준).
    """
    base = result[result["model"] == "lookup_baseline"].set_index("target")

    def _rel(row: pd.Series, col: str) -> float:
        return round((1 - row[col] / base.loc[row["target"], col]) * 100, 2)

    result["RMSE_개선율_%"] = result.apply(lambda r: _rel(r, "rmse"), axis=1)
    result["MAE_개선율_%"] = result.apply(lambda r: _rel(r, "mae"), axis=1)
    result["R2_개선_%p"] = result.apply(
        lambda r: round((r["r2"] - base.loc[r["target"], "r2"]) * 100, 3), axis=1
    )
    result["RMSE_개선_명"] = result.apply(
        lambda r: round(base.loc[r["target"], "rmse"] - r["rmse"], 1), axis=1
    )
    result["MAE_개선_명"] = result.apply(
        lambda r: round(base.loc[r["target"], "mae"] - r["mae"], 1), axis=1
    )
    return result


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a[2:] for a in sys.argv[1:] if a.startswith("--") and "=" not in a}
    opts = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
    feature_sets = args or ["weather_events"]
    if "models" in opts:
        models = opts["models"].split(",")
    elif "all-models" in flags:
        models = list(CANDIDATES)
    else:
        models = list(DEFAULT_CANDIDATES)
    results = compare_many(feature_sets, models, rebuild_cache="rebuild-cache" in flags)
    if "save-results" in opts:
        out_path = Path(opts["save-results"])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pd.concat(
            [r.assign(feature_set=fs) for fs, r in results.items()], ignore_index=True
        ).to_parquet(out_path, index=False)
        print(f"\n[저장] {out_path}")
