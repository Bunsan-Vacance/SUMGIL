"""model_comparison.ipynb을 생성하는 1회성 스크립트. 노트북 파일 자체를 직접 편집하기보다
셀 목록을 코드로 관리하는 게 diff 리뷰에 낫다고 판단해 이렇게 만들었다. 노트북 생성 후에는
이 스크립트를 지워도 된다 — 노트북 자체가 산출물이다.
"""

import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = []

cells.append(nbf.v4.new_markdown_cell("""# 베이스라인 vs LightGBM · RandomForest · XGBoost 비교

**87번(예측 알고리즘 후보 검증)** — 요일유형×역×시간대 lookup 베이스라인이 이미 분산의
96%를 설명한다(`run_baseline.py`). 남은 4%를 기상·이벤트로 실제로 더 줄일 수 있는지,
세 트리 모델로 확인한다.

## 왜 잔차를 예측하는가

처음엔 `day_type`·`station_no`·`time_slot`을 원본 피처로 주고 승하차를 직접 예측시켰다.
그런데 LightGBM 학습 RMSE가 `num_leaves`를 63→2000, `n_estimators`를 300→1000으로 올려도
281.5에서 전혀 안 줄었다 — 용량 문제가 아니라, 이 세 컬럼의 조합(약 2만 개)을 LightGBM의
**근사 범주형 분할**이 lookup 테이블(단순 groupby 평균)만큼 정확히 재현하지 못한다는 뜻이다.
결과적으로 세 모델 다 베이스라인보다 11~47% 나빴다.

그래서 각 후보는 **베이스라인이 이미 설명한 몫을 건드리지 않고, 잔차(실측 − 베이스라인
예측)만 기상·이벤트로 예측**한다. 최종 예측은 `베이스라인 예측 + 모델이 맞춘 잔차`로
재구성한다 — "베이스라인을 재현하는 능력"이 아니라 "베이스라인이 못 본 것을 추가로 잡아내는
능력"만 순수하게 측정하기 위해서다. 실패했던 첫 시도는 2절에 그대로 재현해뒀다."""))

cells.append(nbf.v4.new_code_cell("""import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

import pandas as pd

from baseline import DayTypeLookupBaseline, regression_metrics, residuals
from dataset import load_panel, time_split
from features import FEATURE_SETS, build_matrix
from models import CANDIDATES, fit_predict

pd.set_option("display.width", 120)"""))

cells.append(nbf.v4.new_markdown_cell("## 1. 데이터 로드 · 베이스라인"))

cells.append(nbf.v4.new_code_cell("""panel = load_panel(with_events=True)
train, test = time_split(panel)
print(f"학습 {len(train):,}행 ({train['date'].min():%Y-%m-%d}~{train['date'].max():%Y-%m-%d})")
print(f"평가 {len(test):,}행 ({test['date'].min():%Y-%m-%d}~{test['date'].max():%Y-%m-%d})")

lookup = DayTypeLookupBaseline().fit(train)
train_resid = residuals(lookup, train)
test_resid = residuals(lookup, test)

baseline_rows = []
for target in lookup.targets:
    m = regression_metrics(test[target], test_resid[f"{target}_pred"])
    baseline_rows.append({"model": "lookup_baseline", "target": target, **m})
pd.DataFrame(baseline_rows).round(2)"""))

cells.append(nbf.v4.new_markdown_cell("""## 2. (참고) 실패한 첫 시도 — 원본 범주형 직접 예측

`day_type`·`station_no`·`time_slot`을 원본 그대로 피처로 주고 승하차를 직접 예측시키면
어떻게 되는지 재현한다. 세 모델 다 lookup 베이스라인보다 나빠야 정상이다 — 이 결과가
"잔차 예측" 설계로 바꾼 근거다."""))

cells.append(nbf.v4.new_code_cell("""cat_cols = ["day_type", "station_no", "time_slot"]
event_cols = ["game_count", "festival_count"]
direct_cols = cat_cols + event_cols

X_train_direct = train[direct_cols].copy()
X_test_direct = test[direct_cols].copy()
for c in cat_cols:
    X_train_direct[c] = X_train_direct[c].astype("category")
    X_test_direct[c] = X_test_direct[c].astype("category")

rows = []
for target in lookup.targets:
    rows.append(
        {"model": "lookup_baseline", "target": target,
         **regression_metrics(test[target], test_resid[f"{target}_pred"])}
    )
    for name in CANDIDATES:
        pred = fit_predict(name, X_train_direct, train[target], X_test_direct)
        rows.append({"model": name, "target": target, **regression_metrics(test[target], pred)})

first_try = pd.DataFrame(rows)
base_rmse = first_try[first_try["model"] == "lookup_baseline"].set_index("target")["rmse"]
first_try["RMSE_변화율_%"] = first_try.apply(
    lambda r: round((1 - r["rmse"] / base_rmse[r["target"]]) * 100, 2), axis=1
)
first_try.round(2)"""))

cells.append(nbf.v4.new_markdown_cell("""## 3. 후보 비교 (잔차 예측)

`feature_set`을 바꿔가며(`features.FEATURE_SETS`) 잔차를 무엇으로 설명시킬지 스왑한다."""))

cells.append(nbf.v4.new_code_cell("""def compare(feature_set: str) -> pd.DataFrame:
    X_train = build_matrix(train, feature_set)
    X_test = build_matrix(test, feature_set)

    rows = []
    for target in lookup.targets:
        baseline_pred_test = test_resid[f"{target}_pred"]
        rows.append(
            {"model": "lookup_baseline", "target": target,
             **regression_metrics(test[target], baseline_pred_test)}
        )
        y_train_resid = train_resid[f"{target}_resid"]
        for name in CANDIDATES:
            pred_resid = fit_predict(name, X_train, y_train_resid, X_test)
            final_pred = baseline_pred_test.to_numpy() + pred_resid.to_numpy()
            rows.append(
                {"model": name, "target": target,
                 **regression_metrics(test[target], pd.Series(final_pred))}
            )

    result = pd.DataFrame(rows)
    base_rmse = result[result["model"] == "lookup_baseline"].set_index("target")["rmse"]
    result["RMSE_개선율_%"] = result.apply(
        lambda r: round((1 - r["rmse"] / base_rmse[r["target"]]) * 100, 2), axis=1
    )
    return result"""))

cells.append(nbf.v4.new_markdown_cell("### 3.1 이벤트 피처만 (`game_count`, `festival_count`)"))
cells.append(nbf.v4.new_code_cell('events_result = compare("events")\nevents_result.round(2)'))

cells.append(
    nbf.v4.new_markdown_cell(
        "### 3.2 기상 + 이벤트 전부\n\n"
        "잔차-기상 상관이 이미 전부 `|0.09|` 미만으로 나왔던 것(`run_baseline.py`)과 "
        "일관되는지 확인한다 — 신호가 없는 피처를 더하면 트리 모델은 노이즈에 과적합해 "
        "오히려 손해를 볼 수 있다."
    )
)
cells.append(
    nbf.v4.new_code_cell(
        'weather_events_result = compare("weather_events")\nweather_events_result.round(2)'
    )
)

cells.append(nbf.v4.new_markdown_cell("""## 4. 이벤트 × 역 · 시간대 상호작용

이벤트 컬럼만으로는 개선이 미미했다(3.1절) — `game_count`가 희소한 이진성 변수라 트리가
배울 수 있는 조건부 평균이 몇 종류 안 됐기 때문이다. `diagnose_residuals.py`가 종합운동장·
잠실·월드컵경기장(성산) 같은 소수 역에 잔차가 몰려 있다고 짚었으니, `station_no`(그리고
`time_slot`)를 이벤트 컬럼과 같이 넣어 "어느 역·어느 시간대의 이벤트가 크게 작동하는지"를
모델이 직접 가르게 한다.

**2절과 무엇이 다른가**: 2절은 `station_no`를 유일한 정보원으로 삼아 요일유형×역×시간대
전체(약 2만 개 조합)를 트리가 재현하려다 실패했다. 여기서는 잔차(이미 그 큰 구조를 뺀 값)에
대해 `station_no`를 이벤트 컬럼과만 결합하므로, 외워야 할 조합의 종류가 훨씬 적다."""))
cells.append(
    nbf.v4.new_code_cell(
        'events_station_result = compare("events_station")\nevents_station_result.round(2)'
    )
)
cells.append(nbf.v4.new_markdown_cell("### 4.1 + `time_slot`까지"))
cells.append(
    nbf.v4.new_code_cell(
        'events_station_time_result = compare("events_station_time")\n'
        "events_station_time_result.round(2)"
    )
)

cells.append(nbf.v4.new_markdown_cell("""### 4.2 + 관중수 규모(`game_attendance`)

`game_count`는 경기 유무만 담아 "관중 1만 명"과 "관중 3만 명"을 구분 못 한다.
`game_attendance`(연속값)를 더하면 규모까지 반영되지만, 경기가 없는 날과 "경기는
있었는데 관중수를 못 구한 날"이 둘 다 NaN이라 `game_attendance_missing`을 같이 넣어야
구분된다(`features.py` 참고). RandomForest는 NaN을 못 받아 0으로 채우는데, 그러면
"경기 없음"과 "관중수 결측"이 다시 섞인다 — `models.py`가 그 절충을 문서화해뒀다."""))
cells.append(
    nbf.v4.new_code_cell(
        'events_attendance_result = compare("events_station_time_attendance")\n'
        "events_attendance_result.round(2)"
    )
)

cells.append(nbf.v4.new_markdown_cell("""## 5. 정리

- **원본 범주형 직접 예측(2절)**: 세 모델 다 베이스라인보다 나빴다(RMSE -11~-47%p) — 트리
  모델의 근사 범주형 분할이 lookup 테이블만큼 정확하지 않다는 뜻이라 폐기했다.
- **이벤트만(3.1절)**: 세 모델 다 베이스라인 대비 RMSE 소폭 개선(+0.1%대) — 방향은 맞지만
  절대 개선폭은 미미하다. `game_count`·`festival_count`가 극히 희소한 이진성 변수라(연
  10,200건/123,360건 vs 전체 199만건) 트리가 학습할 수 있는 조건부 평균이 몇 종류 안 된다.
- **기상까지 추가(3.2절)**: 오히려 악화(-0.3~4%p). 잔차와 상관이 없던 변수를 더하면 모델이
  노이즈에 과적합한다는 뜻 — `run_baseline.py`의 상관 분석 결과와 일관된다.
- **이벤트 × 역(4절)**: LightGBM·XGBoost가 +0.45~0.50%로 개선폭이 커졌다(RandomForest는
  -0.4%대로 오히려 나빠짐 — station_no를 서수 인코딩하는 방식이 고카디널리티에서 불리하기
  때문으로 보인다).
- **이벤트 × 역 × 시간대(4.1절)**: LightGBM·XGBoost가 +1.2~1.5%로 더 개선됐다 — 종합운동장·
  잠실·월드컵경기장(성산) 쏠림이 실제로 "이벤트가 특정 역·특정 시간대에 크게 작동한다"는
  상호작용이었다는 뜻이다. 남은 4% 중 약 1.5%p(전체의 30%대)를 이 상호작용만으로 회수했다.
- **관중수 규모까지(4.2절)**: 혼재된 결과다 — LightGBM은 +1.5~1.6%로 소폭 더 좋아졌지만,
  XGBoost는 오히려 +0.9~1.2%로 후퇴했다(NaN 처리 방식 차이로 추정). RandomForest는
  -0.25%대로 계속 열세다. 관중수 규모는 "확실한 개선"이라기보다 LightGBM에서만 미세하게
  더 이기는 정도라, 굳이 넣을지는 복잡도 대비 이득을 보고 판단할 문제다.
- **후보 순위**: LightGBM ≈ XGBoost가 유효한 후보(이벤트×역×시간대 조합에서 +1.2~1.6%),
  RandomForest는 범주형 인코딩 한계로 세 후보 중 가장 약하다."""))

nb["cells"] = cells
nb["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3"},
}

with open("model_comparison.ipynb", "w") as f:
    nbf.write(nb, f)

print("wrote model_comparison.ipynb")
