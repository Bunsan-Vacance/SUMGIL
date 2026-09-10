"""인접역 피처를 패널에 붙이는 검증용 접착 코드 — 89번(피처 엔지니어링).

순수 함수(`build_neighbor_map`·`attach_neighbor_features`)는 `app/CROWD/pipeline/adjacency.py`에
있고, 여기는 그 함수에 **무엇을 먹일지**를 정한다: 토폴로지 로딩·역 필터링(`DATA_ENGINE`의
것을 재사용), 그리고 인접역의 어떤 값을 피처로 쓸지.

**원본값과 잔차 두 종류를 만든다.** 87의 교훈은 "lookup이 이미 설명한 역·시간대 수준을
모델이 다시 배우게 하면 실패한다"였다. 인접역 승하차 **원본값**(`nb_prev_boarding` 등)은
인접역의 평상시 규모(역 수준)를 그대로 담고 있어 같은 함정에 빠질 수 있다. 그래서 인접역의
**잔차**(인접역 실측 − 인접역 lookup 예측, `nb_prev_boarding_resid` 등)도 같이 만든다 —
"인접역이 평소보다 얼마나 더/덜 붐볐나"만 남긴 값이라 이 역의 잔차와 짝이 맞는다.
어느 쪽이 나은지는 `compare_models.py`로 두 세트를 나란히 돌려 확인한다.

**같은 시간대 값을 쓴다는 것의 뜻.** 인접역 피처는 (date, time_slot)이 같은 인접역 행을
붙인다 — 미래를 보는 누수는 아니지만, **예측 시점에 인접역의 그 시간대 실측이 있어야 쓸 수
있다.** 사전 예측(내일 08시)에는 못 쓰고, 실시간 보정(지금 08시대 인접역 집계가 들어온 뒤
이 역을 갱신)에서만 유효한 피처다. 이 제약은 90번(모델 학습) 아키텍처 결정에 걸린다 —
Notion 논의 포인트에 올려둔다.

**잔차 계산 기준.** 인접역 잔차는 학습 구간에 fit한 lookup으로 학습·평가 양쪽에 낸다
(`compare_models.py`의 타깃 잔차와 같은 기준). 학습 구간 잔차는 in-sample이라 약간 낙관적이지만
타깃 쪽도 같은 방식이라 일관된다.
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

from baseline import DayTypeLookupBaseline
from dataset import TARGETS

from app.CROWD.pipeline.adjacency import (
    attach_neighbor_features,
    build_neighbor_map,
    neighbor_feature_names,
)
from DATA_ENGINE.eda.build_congestion_label import load_topology, resolve_segments

RESID_COLS = [f"{t}_resid" for t in TARGETS]
NEIGHBOR_RAW_COLS = neighbor_feature_names(TARGETS)
NEIGHBOR_RESID_COLS = neighbor_feature_names(RESID_COLS)


def neighbor_map_for(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """패널에 실제로 있는 역만으로 인접역 표를 만든다. 결번 인벤토리도 함께 돌려준다."""
    segments, gaps = resolve_segments(load_topology(), set(panel["station_no"].unique()))
    return build_neighbor_map(segments), gaps


def add_neighbor_columns(
    frame: pd.DataFrame, lookup: DayTypeLookupBaseline, neighbor_map: pd.DataFrame
) -> pd.DataFrame:
    """`frame`에 인접역 원본값·잔차 피처를 붙인다.

    먼저 각 행의 lookup 잔차(`boarding_resid`·`alighting_resid`)를 만들고, 원본 타깃과
    잔차 모두를 인접역 값으로 끌어온다. 돌려주는 프레임은 입력과 행 순서·개수가 같다.
    """
    out = frame.copy()
    pred = lookup.predict(out)
    for t in TARGETS:
        out[f"{t}_resid"] = out[t].to_numpy() - pred[t].to_numpy()
    return attach_neighbor_features(out, neighbor_map, [*TARGETS, *RESID_COLS])


def needs_neighbor_columns(cols: list[str]) -> bool:
    return any(c.startswith("nb_") for c in cols)
