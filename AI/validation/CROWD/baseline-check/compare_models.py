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
    python validation/CROWD/baseline-check/compare_models.py [feature_set]
    (feature_set 생략 시 "weather_events" — features.FEATURE_SETS 참고)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from baseline import DayTypeLookupBaseline, regression_metrics, residuals
from dataset import load_panel, time_split
from features import FEATURE_SETS, build_matrix
from models import CANDIDATES, fit_predict


def compare(feature_set: str = "weather_events") -> pd.DataFrame:
    panel = load_panel(with_events=True)
    train, test = time_split(panel)

    lookup = DayTypeLookupBaseline().fit(train)
    train_resid = residuals(lookup, train)
    test_resid = residuals(lookup, test)

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
        for name in CANDIDATES:
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
            print(f"[{name}/{target}] {elapsed:.1f}s")

    result = pd.DataFrame(rows)
    base_rmse = result[result["model"] == "lookup_baseline"].set_index("target")["rmse"]
    result["RMSE_개선율_%"] = result.apply(
        lambda r: round((1 - r["rmse"] / base_rmse[r["target"]]) * 100, 2), axis=1
    )
    return result


if __name__ == "__main__":
    feature_set = sys.argv[1] if len(sys.argv) > 1 else "weather_events"
    print(f"[feature_set] {feature_set} = {FEATURE_SETS[feature_set]}\n")
    out = compare(feature_set)
    print()
    print(out.round(2).to_string(index=False))
