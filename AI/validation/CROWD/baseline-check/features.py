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

**세트를 왜 이 8개로 줄였나**: 후보 비교를 실제로 돌려보고 기여가 없는 컬럼을 뺐다. 후원기관
수(`festival_sponsored_count`)는 넣고 빼도 LightGBM·XGBoost 개선율이 소수점까지 같아서
파이프라인에서 제거했다(경위는 `parsers_festival.py` docstring). 세트는 "무엇이 효과를
만들었는지 분리해서 볼 수 있는 최소 단위"만 남긴다 — 컬럼을 쌓기만 한 세트는 희소·약신호가
겹쳐 과적합하는 것이 기상·관중수에서 이미 두 번 확인됐다.
"""

from __future__ import annotations

import pandas as pd

WEATHER_COLS = ["temp_c", "precip_mm", "wind_ms", "humidity_pct", "snow_cm"]
EVENT_COLS = ["game_count", "festival_count"]
ATTENDANCE_COLS = ["game_attendance", "game_attendance_missing"]
# 축제 쪽 성격 컬럼. 관중수가 원천에 없어 `game_attendance`의 대응물이 없고
# (`parsers_festival.py` 참고), 대신 개최 기간으로 단기 축제와 상설 행사를 가른다.
FESTIVAL_SHAPE_COLS = [
    "festival_short_count",
    "festival_long_count",
    "festival_min_duration_days",
]
CATEGORICAL_COLS = ["station_no", "time_slot"]

# ── 89번 파생 피처. 컬럼 이름은 `derived_features.py`(→ app/CROWD/pipeline/{adjacency,lags})가
# 만드는 것과 같아야 한다. 어느 세트를 배포에 쓸 수 있는지는 예측 시점에 따라 갈린다
# (`derived_features.py` docstring의 표). 여기서는 문자열로만 적어 features.py가 무거운
# 모듈을 import하지 않게 한다.
_SIDES = ("prev", "next")
_RESID = ("boarding_resid", "alighting_resid")
NEIGHBOR_RAW_COLS = [f"nb_{s}_{t}" for s in _SIDES for t in ("boarding", "alighting")]
NEIGHBOR_RESID_COLS = [f"nb_{s}_{r}" for s in _SIDES for r in _RESID]
TRANSFER_RESID_COLS = [f"nb_xfer_{r}" for r in _RESID]
SELF_LAG_D1_COLS = [f"lag1d_{r}" for r in _RESID]
SELF_LAG_D7_COLS = [f"lag7d_{r}" for r in _RESID]
SELF_LAG_S1_COLS = [f"lag1s_{r}" for r in _RESID]
NEIGHBOR_LAG_D1_COLS = [f"nb_{s}_{c}" for s in _SIDES for c in SELF_LAG_D1_COLS]
NEIGHBOR_LAG_D7_COLS = [f"nb_{s}_{c}" for s in _SIDES for c in SELF_LAG_D7_COLS]
NEIGHBOR_LAG_S1_COLS = [f"nb_{s}_{c}" for s in _SIDES for c in SELF_LAG_S1_COLS]

_EVENT_INTERACTION = EVENT_COLS + ["station_no", "time_slot"]
_FESTIVAL_SET = _EVENT_INTERACTION + FESTIVAL_SHAPE_COLS

FEATURE_SETS: dict[str, list[str]] = {
    "weather": WEATHER_COLS,
    "events": EVENT_COLS,
    "weather_events": WEATHER_COLS + EVENT_COLS,
    "events_station": EVENT_COLS + ["station_no"],
    "events_station_time": _EVENT_INTERACTION,
    "events_station_time_attendance": _EVENT_INTERACTION + ATTENDANCE_COLS,
    "events_station_time_festival": _FESTIVAL_SET,
    "events_station_time_attendance_festival": (
        _EVENT_INTERACTION + ATTENDANCE_COLS + FESTIVAL_SHAPE_COLS
    ),
    # ── 89번: 파생 피처. 전부 87 권장 세트(_FESTIVAL_SET) 위에 얹어 증분을 본다.
    # (a) 같은 시간대 이웃 — 실시간 보정 전용
    "neighbors_resid": NEIGHBOR_RESID_COLS,
    "neighbors_raw": NEIGHBOR_RAW_COLS,
    "festival_neighbors_resid": _FESTIVAL_SET + NEIGHBOR_RESID_COLS,
    "festival_neighbors_raw": _FESTIVAL_SET + NEIGHBOR_RAW_COLS,
    "festival_neighbors_xfer_resid": _FESTIVAL_SET + NEIGHBOR_RESID_COLS + TRANSFER_RESID_COLS,
    # (b) 직전 시간대 — 실시간 보정, 1시간 지연 허용
    "festival_slotlag_resid": (_FESTIVAL_SET + SELF_LAG_S1_COLS + NEIGHBOR_LAG_S1_COLS),
    # (c) 전날·1주 전 — 사전 예측용. d7만 쓰는 세트는 일별 CSV 지연에도 안전한 하한.
    "festival_lag_d7_resid": _FESTIVAL_SET + SELF_LAG_D7_COLS + NEIGHBOR_LAG_D7_COLS,
    "festival_lag_d1d7_resid": (
        _FESTIVAL_SET
        + SELF_LAG_D1_COLS
        + SELF_LAG_D7_COLS
        + NEIGHBOR_LAG_D1_COLS
        + NEIGHBOR_LAG_D7_COLS
    ),
    "festival_selflag_d1d7_resid": _FESTIVAL_SET + SELF_LAG_D1_COLS + SELF_LAG_D7_COLS,
    # (d) 전부 — 실시간 보정에서 얻을 수 있는 상한
    "festival_all_derived_resid": (
        _FESTIVAL_SET
        + NEIGHBOR_RESID_COLS
        + TRANSFER_RESID_COLS
        + SELF_LAG_S1_COLS
        + NEIGHBOR_LAG_S1_COLS
        + SELF_LAG_D1_COLS
        + SELF_LAG_D7_COLS
        + NEIGHBOR_LAG_D1_COLS
        + NEIGHBOR_LAG_D7_COLS
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
