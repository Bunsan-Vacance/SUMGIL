"""파생 피처(인접역·환승 노드·시차) — 검증용 접착. 구현은 `app/CROWD/pipeline/`에 있다.

89번 검증 때는 이 파일이 파생 규칙을 직접 들고 있었지만, 90번에서 학습·추론이 같은 함수를 써야
해서 `app/CROWD/pipeline/features.py`(파생·세트)와 `dataset.py`(캐시)로 승격했다. 여기는
validation 코드(`compare_models.py`·노트북)가 쓰는 이름을 그대로 재수출하고, 검증 경위만 남긴다
(`validation/` → `app/` import는 허용 방향).

## 왜 잔차를 끌어오는가 (원본값이 아니라)

87의 교훈은 "lookup이 이미 설명한 역·시간대 수준을 모델이 다시 배우게 하면 실패한다"였다.
인접역 승하차 **원본값**(`nb_prev_boarding`)은 인접역의 평상시 규모를 그대로 담아 같은 함정에
빠진다 — 1차 비교에서 잔차 대비 1/4 효과였다(`RESULTS.md`). 그래서 파생은 전부 **lookup 잔차**
기준이고, 원본값 세트(`neighbors_raw`·`festival_neighbors_raw`)는 비교 기준으로만 남긴다.

## 세 종류의 이웃 — 예측 시점에 쓸 수 있는가로 갈린다

| 접두 | 뜻 | 쓸 수 있는 상황 |
| --- | --- | --- |
| `nb_{prev,next}_*` | 같은 호선 앞뒤 역의 **같은 시간대** 값 | 실시간 집계가 있을 때 |
| `nb_xfer_*` | 같은 역명 다른 호선 노드의 같은 시간대 값 | 실시간 집계가 있을 때 |
| `lag1s_*`, `nb_*_lag1s_*` | 같은 날 **직전 시간대** 값 | 실시간 집계, 1시간 지연 허용 |
| `lag1d_*`, `nb_*_lag1d_*` | **전날** 같은 시간대 값 | D−1 원천(`getStnPsgr`) |
| `lag7d_*`, `nb_*_lag7d_*` | **1주 전** 같은 시간대 값 | 일별 CSV여도 안전 |

공개 원천의 한계가 D−1이라 서빙에서는 첫 세 줄이 NaN이다(`features.REALTIME_COLS`). 2차 비교
결과: 시차만으로 RMSE −21% / MAE −28%, 전부 −46% / −49%.

## 잔차 계산 기준

잔차는 **학습 구간에 fit한 lookup으로 전체 패널에** 낸다(타깃 잔차와 같은 기준). 시차가 분할
경계를 넘어 참조해야 하므로 분할 전에 전체 패널에서 파생을 만들고 그 뒤에 나눈다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[2]
for p in (str(_HERE), str(AI_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.CROWD.pipeline.adjacency import (
    build_neighbor_map,
    build_transfer_map,
    neighbor_feature_names,
)
from app.CROWD.pipeline.dataset import (
    DERIVED_CACHE,
    load_or_build_derived,
    resolved_segments,
)
from app.CROWD.pipeline.features import (
    DAY_LAGS,
    DERIVED_VERSION,
    NEIGHBOR_LAG_D1_COLS,
    NEIGHBOR_LAG_D7_COLS,
    NEIGHBOR_LAG_S1_COLS,
    NEIGHBOR_RESID_COLS,
    REALTIME_COLS,
    RESID_COLS,
    SELF_LAG_D1_COLS,
    SELF_LAG_D7_COLS,
    SELF_LAG_S1_COLS,
    SLOT_ORDER,
    TRANSFER_RESID_COLS,
    add_derived_columns,
    needs_derived_columns,
)
from app.CROWD.pipeline.lookup import TARGETS

# 검증 전용 — 원본값 세트가 참조하는 이름(app 세트 레지스트리에는 없다).
NEIGHBOR_RAW_COLS = neighbor_feature_names(TARGETS)


def neighbor_maps_for(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(노선 앞뒤 인접역 표, 환승 노드 표, 결번 인벤토리) — 진단·안내 출력용."""
    segments, gaps = resolved_segments(panel)
    line_map = build_neighbor_map(segments)
    transfer_map = build_transfer_map(panel[["station_no", "station_name", "line"]])
    return line_map, transfer_map, gaps
