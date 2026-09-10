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

**`events_station*` 세트는 왜 `station_no`를 다시 넣어도 안전한가**: 위에서 뺀 이유는
"day_type×station_no×time_slot 조합 전체를 모델이 다시 외우려다 실패해서"였다. 여기서는
`station_no`를 이벤트 컬럼과만 결합한다 — `diagnose_residuals.py`가 짚은 종합운동장·잠실·
월드컵경기장(성산) 같은 소수 역만 game_count>0에서 갈라지면 되므로, 통으로 외워야 하는
2만 개 조합과는 학습 난이도가 다르다. 그래도 트리가 역 자체의 잡음(이벤트와 무관한 역별
평균 차이)을 다시 외우는 방향으로 새는지는 결과로 확인해야 한다.

**`ATTENDANCE_COLS`**: `game_count`는 경기 유무만 담아 "관중 1만 명"과 "관중 3만 명"을
구분 못 한다. `game_attendance`(연속값)를 대신 넣으면 규모까지 반영된다. 단 이 컬럼은
경기가 없는 날과 "경기는 있었는데 관중수를 못 구한 날" 둘 다 NaN이라(`dataset.py`가 일부러
채우지 않음), 그 둘을 구분하려면 `game_attendance_missing`을 같이 넣어야 한다.

**`FESTIVAL_SHAPE_COLS` — 축제에는 관중수가 없다**: 경기의 `game_attendance`에 대응하는
축제 관중수는 원천(KC_488)에 아예 없다. 그래서 규모를 추정해 만들어 넣는 대신
(원칙 4), 관측되는 값으로 축제의 **성격**을 가른다. `festival_count` 하나만 쓰던 때는 이
구분이 없어서, 역·날짜별 축제 행의 91.8%를 차지하는 장기 상설 행사(서울아트쇼 231일, 박물관
기획전 등)가 정작 인원이 몰리는 단기 축제의 신호를 덮고 있었다.

- `festival_short_count`·`festival_long_count` — 개최 기간 3일 이하/초과로 쪼갠 개수.
- `festival_min_duration_days` — 그 날 그 역에서 가장 짧게 열리는 축제의 기간(연속값).
  3일 경계는 임의로 정한 것이라, 모델이 다른 경계를 고를 수 있도록 같이 넣는다. 축제가
  없는 날은 NaN이다 — 0으로 채우면 "1일보다 짧은 축제"라는 없는 순서가 생긴다.

**`FESTIVAL_SPONSOR_COLS`**: 후원기관이 명시된 축제 수. 원본에서 분산이 있는 유일한 규모
프록시지만(775건 중 371건) 관중수의 대체물로는 약하다 — 별도 세트로 분리해 기여도를 따로
측정한다.
"""

from __future__ import annotations

import pandas as pd

WEATHER_COLS = ["temp_c", "precip_mm", "wind_ms", "humidity_pct", "snow_cm"]
EVENT_COLS = ["game_count", "festival_count"]
ATTENDANCE_COLS = ["game_attendance", "game_attendance_missing"]
# 축제 쪽 규모·성격 컬럼. 관중수가 원천에 없어 `game_attendance`의 대응물이 없고
# (`parsers_festival.py` 참고), 대신 개최 기간으로 성격을 가르고 후원기관 유무를 약한
# 규모 프록시로 쓴다.
FESTIVAL_SHAPE_COLS = [
    "festival_short_count",
    "festival_long_count",
    "festival_min_duration_days",
]
FESTIVAL_SPONSOR_COLS = ["festival_sponsored_count"]
CATEGORICAL_COLS = ["station_no", "time_slot"]

_EVENT_INTERACTION = EVENT_COLS + ["station_no", "time_slot"]

FEATURE_SETS: dict[str, list[str]] = {
    "weather": WEATHER_COLS,
    "events": EVENT_COLS,
    "weather_events": WEATHER_COLS + EVENT_COLS,
    "events_station": EVENT_COLS + ["station_no"],
    "events_station_time": _EVENT_INTERACTION,
    "events_station_time_attendance": _EVENT_INTERACTION + ATTENDANCE_COLS,
    # 아래 세 세트가 4단계(이벤트 유무·규모) 잔여분이다. 축제 기여를 경기 관중수와 섞지
    # 않고 단계별로 쌓아, 어느 컬럼이 실제로 개선을 만드는지 분리해서 본다
    # (원칙 1의 "확장 모델의 기여도를 별도 검증한다").
    "events_station_time_festival": _EVENT_INTERACTION + FESTIVAL_SHAPE_COLS,
    "events_station_time_festival_sponsor": (
        _EVENT_INTERACTION + FESTIVAL_SHAPE_COLS + FESTIVAL_SPONSOR_COLS
    ),
    "events_station_time_all_scale": (
        _EVENT_INTERACTION + ATTENDANCE_COLS + FESTIVAL_SHAPE_COLS + FESTIVAL_SPONSOR_COLS
    ),
}


def build_matrix(panel: pd.DataFrame, feature_set: str) -> pd.DataFrame:
    """`feature_set`에 해당하는 컬럼만 골라 돌려준다.

    `station_no`·`time_slot`이 포함된 세트는 category dtype으로 캐스팅한다(`models.py`가
    모델별로 처리). 기상·이벤트 원본 컬럼은 전부 수치형이라 그대로 둔다.
    """
    cols = FEATURE_SETS[feature_set]
    X = panel[cols].copy()
    for col in CATEGORICAL_COLS:
        if col in X.columns:
            X[col] = X[col].astype("category")
    return X
