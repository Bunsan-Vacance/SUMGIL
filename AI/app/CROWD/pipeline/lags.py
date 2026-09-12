"""시차(lag) 피처 — 같은 역의 과거 값을 현재 행에 붙인다.

`adjacency.py`의 인접역 피처는 **같은 시간대** 인접역 실측을 쓰기 때문에 실시간 보정에서만
유효하다(사전 예측 시점엔 그 값이 없다). 이 모듈은 그 제약을 피하는 형태를 만든다 —
예측 시점에 이미 확정된 과거 값만 쓴다.

- `attach_day_lags` — 같은 (역, 시간대)의 `d`일 전 값. `lag{d}d_{col}` (예: `lag7d_boarding_resid`).
  d−1은 "전날 집계가 다음 날 아침에 들어온다"는 전제가 있어야 쓸 수 있고, d−7은 원천이
  일별 CSV여도 안전하다. 둘 다 만들어 모델이 고르게 하되, 배포 시 원천 지연에 맞춰 세트를
  고른다.
- `attach_slot_lag` — 같은 날 **직전 시간대** 값. `lag1s_{col}`. 실시간 집계가 1시간 지연으로
  들어오는 상황(nowcast)용이다. 첫 슬롯은 직전이 없어 NaN.

**위치 shift가 아니라 날짜·슬롯 키로 조인한다.** 패널에 빠진 날짜가 있으면 `groupby.shift`는
"이전 행"을 이전 날로 오해한다. 키 조인은 그 날이 없으면 NaN으로 정직하게 남긴다(원칙 8).

인접역의 시차 값이 필요하면 이 모듈로 먼저 lag 컬럼을 만든 뒤 `adjacency.attach_neighbor_features`
에 그 컬럼을 `value_cols`로 넘긴다(`nb_prev_lag7d_boarding_resid`처럼 이름이 겹쳐 쌓인다).
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

import pandas as pd


def day_lag_names(value_cols: Sequence[str], day_lags: Sequence[int]) -> list[str]:
    return [f"lag{d}d_{c}" for d in day_lags for c in value_cols]


def slot_lag_names(value_cols: Sequence[str]) -> list[str]:
    return [f"lag1s_{c}" for c in value_cols]


def attach_day_lags(
    panel: pd.DataFrame,
    value_cols: Sequence[str],
    day_lags: Sequence[int] = (1, 7),
    keys: Sequence[str] = ("station_no", "time_slot"),
    date_col: str = "date",
) -> pd.DataFrame:
    """각 행에 같은 `keys`의 `d`일 전 `value_cols`를 `lag{d}d_{col}`로 붙인다."""
    keys = list(keys)
    value_cols = list(value_cols)
    out = panel.copy()
    source = panel[[date_col, *keys, *value_cols]]
    for d in day_lags:
        shifted = source.copy()
        shifted[date_col] = shifted[date_col] + pd.Timedelta(days=d)
        shifted = shifted.rename(columns={c: f"lag{d}d_{c}" for c in value_cols})
        out = out.merge(shifted, on=[date_col, *keys], how="left")
    return out


def same_day_type_lag_names(value_cols: Sequence[str]) -> list[str]:
    return [f"lagsd_{c}" for c in value_cols]


def attach_same_day_type_lag(
    panel: pd.DataFrame,
    value_cols: Sequence[str],
    keys: Sequence[str] = ("station_no", "time_slot"),
    date_col: str = "date",
    day_type_col: str = "day_type",
    max_gap_days: int = 14,
) -> pd.DataFrame:
    """각 행에 **같은 요일유형의 직전 날** `value_cols`를 `lagsd_{col}`로 붙인다(93 B′).

    전날 시차(`lag1d_*`)는 토요일 행에 금요일을, 월요일 행에 일요일을 가리켜 요일유형이 갈린다 —
    90에서 주말·공휴일 개선폭이 평일의 60%였던 원인 후보. 이 시차는 (역, 시간대, 요일유형) 안에서
    바로 이전 날짜의 값을 쓴다: 평일은 전날(월요일은 금요일), 토요일은 지난 토요일, 일요일·공휴일은
    직전 일요일 또는 공휴일. `lagsd_gap_days`에 며칠 전인지 남기고, `max_gap_days`를 넘으면 NaN으로
    둔다(연휴 뒤 첫 공휴일이 몇 주 전 공휴일을 끌어오는 것을 막는다 — 원칙 8).

    같은 (역, 시간대, 요일유형) 그룹 안의 날짜 순 직전 행이라 위치 shift를 쓰지만, 그룹이 요일유형으로
    나뉘어 있어 "빠진 날을 이전 날로 오해"하는 문제가 없다 — 빠진 날은 gap_days로 드러난다.
    """
    keys = list(keys)
    value_cols = list(value_cols)
    out = panel.copy()
    order = out.sort_values([*keys, day_type_col, date_col]).index
    grp_cols = [*keys, day_type_col]
    src = out.loc[order, [*grp_cols, date_col, *value_cols]]
    g = src.groupby(grp_cols, observed=True, sort=False)
    prev_date = g[date_col].shift(1)
    gap = (src[date_col] - prev_date).dt.days
    valid = gap <= max_gap_days
    out["lagsd_gap_days"] = gap.where(valid).reindex(out.index)
    for c in value_cols:
        out[f"lagsd_{c}"] = g[c].shift(1).where(valid).reindex(out.index)
    return out


def attach_slot_lag(
    panel: pd.DataFrame,
    value_cols: Sequence[str],
    slot_order: Sequence[str],
    keys: Sequence[str] = ("date", "station_no"),
    slot_col: str = "time_slot",
) -> pd.DataFrame:
    """각 행에 같은 `keys`의 **직전 슬롯** `value_cols`를 `lag1s_{col}`로 붙인다.

    `slot_order`는 하루 안의 슬롯 순서(첫 슬롯은 직전이 없어 NaN). 슬롯 문자열은 사전순이
    운행 순서와 다를 수 있어(`~06` < `06-07` 등) 명시적으로 받는다.
    """
    keys = list(keys)
    value_cols = list(value_cols)
    next_slot = dict(pairwise(slot_order))
    source = panel[[*keys, slot_col, *value_cols]].copy()
    # 직전 슬롯의 값을 "다음 슬롯" 키로 옮겨 붙인다. 마지막 슬롯의 값은 받을 슬롯이 없다.
    source[slot_col] = source[slot_col].map(next_slot)
    source = source.dropna(subset=[slot_col])
    source = source.rename(columns={c: f"lag1s_{c}" for c in value_cols})
    return panel.merge(source, on=[*keys, slot_col], how="left")
