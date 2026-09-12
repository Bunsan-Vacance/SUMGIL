"""피처 파이프라인 — 패널에 파생 컬럼을 붙이고, 세트 이름으로 피처 행렬을 만든다.

89번(피처 엔지니어링)의 결론을 프로덕션 형태로 옮긴 것이다. 검증 경위·수치는
`validation/CROWD/baseline-check/{features,derived_features}.py`와 `RESULTS.md`에 있고, 여기는
학습(`train.py`)과 추론(`predict.py`)이 **같은 함수**로 피처를 만들기 위한 순수 함수만 둔다.
pandas 기반이라 Spark에서는 `pandas_udf`로 감쌀 수 있다(`AI/README.md` 8절).

## 구조 — lookup + 잔차

모델 입력은 원본 승하차가 아니라 **lookup 잔차**(실측 − 요일유형×역×시간대 평균)다. 87에서
범주형을 트리에 직접 주면 lookup보다 나빠졌고, 89에서 인접역 원본값보다 잔차가 4배 효과였다.
`add_derived_columns`는 다음 순서로 붙인다.

1. 잔차 — `boarding_resid`, `alighting_resid`
2. 시차 — 전날·1주 전(`lag1d_*`, `lag7d_*`), 직전 시간대(`lag1s_*`) 잔차
3. 이웃 — 같은 호선 앞뒤 역(`nb_prev_*`, `nb_next_*`)·환승 노드(`nb_xfer_*`)의 같은 시간대 값,
   그리고 앞뒤 역의 시차 값

## 예측 시점과 결측

같은 시간대 이웃·직전 시간대 컬럼은 추론 시점에 그 시각 실측이 있어야 계산된다. 공개 원천은
D−1(전날) 갱신이 한계라(`getStnPsgr`, OA-22723) 서빙에서는 이 컬럼이 **NaN**이고, 모델은 전날·
1주 전 시차와 이벤트로 예측한다(89 검증: RMSE −21% / MAE −28%). LightGBM은 NaN을 분할
정보로 받으므로 하나의 모델로 두 상황을 덮을 수 있는지는 90번이 "실시간 컬럼 마스킹 평가"로
확인한다. **어느 경우에도 결측을 0으로 채우지 않는다**(원칙 8).

## 세트 레지스트리

`FEATURE_SETS`는 validation과 같은 키를 쓴다. 검증에서 쓴 세트 전부가 아니라 배포 후보만 둔다.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from app.CROWD.pipeline.adjacency import (
    attach_neighbor_features,
    build_neighbor_map,
    build_transfer_map,
    neighbor_feature_names,
)
from app.CROWD.pipeline.lags import (
    attach_day_lags,
    attach_same_day_type_lag,
    attach_slot_lag,
    day_lag_names,
    same_day_type_lag_names,
    slot_lag_names,
)
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline

# 패널의 20개 운행일 슬롯 순서. 사전순이 아니다(`~06`이 첫 슬롯, `24~`가 마지막).
SLOT_ORDER = ["~06"] + [f"{h:02d}-{h + 1:02d}" for h in range(6, 24)] + ["24~"]
DAY_LAGS = (1, 7)
# 파생 규칙이 바뀌면 올린다 — 캐시·아티팩트 메타에 기록돼 불일치를 잡는다.
# 2: 같은 요일유형 직전 날 시차(lagsd_*) 추가(93).
DERIVED_VERSION = 2

RESID_COLS = [f"{t}_resid" for t in TARGETS]

# ── 컬럼 그룹 ──
EVENT_COLS = ["game_count", "festival_count"]
FESTIVAL_SHAPE_COLS = ["festival_short_count", "festival_long_count", "festival_min_duration_days"]
CATEGORICAL_COLS = ["station_no", "time_slot"]
_FESTIVAL_SET = EVENT_COLS + CATEGORICAL_COLS + FESTIVAL_SHAPE_COLS

SELF_LAG_D1_COLS = day_lag_names(RESID_COLS, (1,))
SELF_LAG_D7_COLS = day_lag_names(RESID_COLS, (7,))
SELF_LAG_S1_COLS = slot_lag_names(RESID_COLS)
SELF_LAG_SD_COLS = same_day_type_lag_names(RESID_COLS)  # 같은 요일유형 직전 날(93 B′)
NEIGHBOR_RESID_COLS = neighbor_feature_names(RESID_COLS)
TRANSFER_RESID_COLS = neighbor_feature_names(RESID_COLS, sides=("xfer",))
NEIGHBOR_LAG_D1_COLS = neighbor_feature_names(SELF_LAG_D1_COLS)
NEIGHBOR_LAG_D7_COLS = neighbor_feature_names(SELF_LAG_D7_COLS)
NEIGHBOR_LAG_S1_COLS = neighbor_feature_names(SELF_LAG_S1_COLS)

# 추론 시점에 그 시각 실측이 필요한 컬럼 — D−1 원천만 있을 때 NaN이 되는 컬럼.
REALTIME_COLS = NEIGHBOR_RESID_COLS + TRANSFER_RESID_COLS + SELF_LAG_S1_COLS + NEIGHBOR_LAG_S1_COLS

FEATURE_SETS: dict[str, list[str]] = {
    # 87 권장 — 외부 요인만. 비교 기준선.
    "events_station_time_festival": _FESTIVAL_SET,
    # 사전 예측(D−1 원천) — 전날 집계가 확보될 때. 90 배포 세트(93에서 d1sd로 교체)
    "festival_selflag_d1d7_resid": _FESTIVAL_SET + SELF_LAG_D1_COLS + SELF_LAG_D7_COLS,
    # 사전 예측 — 일별 CSV 지연에도 안전한 하한
    "festival_lag_d7_resid": _FESTIVAL_SET + SELF_LAG_D7_COLS + NEIGHBOR_LAG_D7_COLS,
    # 93 B′ — 전날 대신 "같은 요일유형의 직전 날"(평일은 전날과 같고 토·일·공휴일에서 다르다) + 1주 전
    "festival_selflag_sameday_d7_resid": _FESTIVAL_SET + SELF_LAG_SD_COLS + SELF_LAG_D7_COLS,
    # 93 B″ — 전날·같은 요일유형 직전 날·1주 전 셋 다. **현재 배포 세트**(93: 전체 +1.4%p, 휴일 +3.6%p)
    "festival_selflag_d1sd_d7_resid": _FESTIVAL_SET
    + SELF_LAG_D1_COLS
    + SELF_LAG_SD_COLS
    + SELF_LAG_D7_COLS,
    # 실시간 집계가 있을 때의 상한. D−1 서빙에서는 REALTIME_COLS가 NaN.
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


def needs_derived_columns(cols: Sequence[str]) -> bool:
    return any(c.startswith(("nb_", "lag")) for c in cols)


def add_derived_columns(
    panel: pd.DataFrame,
    lookup: DayTypeLookupBaseline,
    segments: list[dict],
) -> pd.DataFrame:
    """전체 패널에 잔차 → 시차 → 이웃 순으로 파생 컬럼을 붙인다. 행 순서·개수는 그대로.

    `segments`는 `topology.resolve_segments`로 패널에 있는 역만 남긴 세그먼트 목록이다.
    시차가 날짜 경계를 넘어 참조하므로 **학습/평가로 나누기 전의 전체 패널**에 적용한다.
    """
    out = panel.copy()
    resid = lookup.residuals(out)
    for c in RESID_COLS:
        out[c] = resid[c].to_numpy()

    out = attach_day_lags(out, RESID_COLS, DAY_LAGS)
    out = attach_same_day_type_lag(out, RESID_COLS)
    out = attach_slot_lag(out, RESID_COLS, SLOT_ORDER)

    line_map = build_neighbor_map(segments)
    transfer_map = build_transfer_map(out[["station_no", "station_name", "line"]])
    out = attach_neighbor_features(
        out, pd.concat([line_map, transfer_map], ignore_index=True), [*TARGETS, *RESID_COLS]
    )
    out = attach_neighbor_features(
        out, line_map, [*SELF_LAG_D1_COLS, *SELF_LAG_D7_COLS, *SELF_LAG_S1_COLS]
    )
    return out


def build_matrix(frame: pd.DataFrame, feature_set: str) -> pd.DataFrame:
    """`feature_set`의 컬럼만 골라 돌려준다. 범주형은 category dtype으로 캐스팅한다.

    프레임에 없는 컬럼은 NaN으로 채운다 — 서빙에서 실시간 컬럼이 아직 계산되지 않은 경우를
    같은 코드로 다루기 위해서다(결측을 0으로 바꾸지는 않는다).
    """
    cols = FEATURE_SETS[feature_set]
    X = frame.reindex(columns=cols).copy()
    for col in CATEGORICAL_COLS:
        if col in X.columns:
            X[col] = X[col].astype("category")
    return X


def mask_realtime_columns(X: pd.DataFrame) -> pd.DataFrame:
    """실시간 컬럼을 NaN으로 가린다 — D−1 원천만 있는 서빙 상황을 평가에서 재현한다."""
    X = X.copy()
    for c in REALTIME_COLS:
        if c in X.columns:
            X[c] = float("nan")
    return X
