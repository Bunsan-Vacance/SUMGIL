"""잔차 모델용 피처 세트 — 기상·이벤트가 lookup 베이스라인의 잔차를 얼마나 설명하는지
단계적으로 확인하기 위한 것이다.

**왜 잔차를 모델링하는가 (범주형을 다시 넣지 않는 이유)**: 처음엔 `day_type`·`station_no`·
`time_slot`을 원본 피처로 주고 트리 모델이 승하차를 직접 예측하게 했었다. 그런데 LightGBM
학습 RMSE가 num_leaves를 63→2000, n_estimators를 300→1000으로 올려도 281.5에서 전혀
안 줄었다 — 용량 문제가 아니라, 이 세 컬럼이 만드는 조합(요일유형×역×시간대, 약 2만 개)을
LightGBM의 근사 범주형 분할 알고리즘이 lookup 테이블(단순 groupby 평균)만큼 정확히
재현하지 못한다는 뜻이다. 그 결과 세 모델 다 lookup 베이스라인보다 나빴다(-11~-47%).

해법은 그 조합을 모델이 다시 학습하게 하지 않는 것이다. `station_no`는 컬럼에서 뺐다 —
`game_count`·`festival_count`가 이미 역별 값이라 역 정보가 피처에 암묵적으로 들어있고,
day_type·time_slot은 잔차 자체가 이미 그 축의 평균을 뺀 값이라 다시 넣을 이유가 없다.
그래서 이 모듈은 **기상·이벤트 원본 컬럼만** 다룬다 — lookup이 이미 설명한 몫을 모델이
다시 배우려다 실패하는 구조 자체를 없앤 것이다.

`FEATURE_SETS`는 키 하나만 바꾸면 피처 조합을 스왑할 수 있게 하는 중앙 레지스트리다
(`validation/README.md` 관례).
"""

from __future__ import annotations

import pandas as pd

WEATHER_COLS = ["temp_c", "precip_mm", "wind_ms", "humidity_pct", "snow_cm"]
EVENT_COLS = ["game_count", "festival_count"]

FEATURE_SETS: dict[str, list[str]] = {
    "weather": WEATHER_COLS,
    "events": EVENT_COLS,
    "weather_events": WEATHER_COLS + EVENT_COLS,
}


def build_matrix(panel: pd.DataFrame, feature_set: str) -> pd.DataFrame:
    """`feature_set`에 해당하는 컬럼만 골라 돌려준다. 전부 수치형이라 인코딩이 필요 없다."""
    return panel[FEATURE_SETS[feature_set]].copy()
