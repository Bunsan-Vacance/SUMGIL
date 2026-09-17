"""이력 마스킹 — 결측 내성 학습·평가에 쓰는 순수 numpy 유틸(144, 145 공유).

143에서 배포 세트(LightGBM)는 시차가 전부 NaN이면 lookup보다 −37%였다. 144(GRU)·145(계열 비교)는
"이력이 짧거나 없을 때 lookup 이하로 떨어지지 않는가"를 같은 규칙으로 재야 하므로 마스킹 규칙을
모델별 모듈이 아니라 여기에 둔다.

시퀀스 축 규약: 길이 N인 이력 축의 인덱스 `i`는 대상일 기준 **D−(N−i)**다 — `i=0`이 가장 오래된 날
(D−N), `i=N−1`이 전날(D−1). 마스크는 1이 "있음", 0이 "없음"이고, 값 배열은 마스크가 0인 자리에서
항상 0이다. **0은 결측을 뜻하지 않는다 — 결측은 마스크로만 알린다**(데이터 검증 리포트 원칙 8).

- `truncate_history` — 앞쪽 k일을 지운다(학습 증강, 그리고 "7일치만 온 예측기" 상황).
- `keep_offsets_mask` — 지정한 시차(D−1, D−7 …)만 남긴다. 143 `nolag_loss.mask_lags`의
  `full / d7_only / d1_only / no_lag` 4시나리오를 시퀀스에 옮긴 것.
- `sample_truncation` — 표본마다 `k ~ U{0..N}`을 뽑는다. `p_full`로 "절단 없음" 비중을 높일 수 있다
  (144 계획: 균등 1회, 필요하면 2안 비교 파라미터 1개).

표형(tabular) 시차 마스킹도 145부터 이 모듈에 같이 둔다 — LightGBM 학습(`train.py`)과 평가
(`validation/CROWD/dl-resid-check/evaluate_dl.LGB_MASK`, 143 규칙)가 컬럼 접두 정의 하나를 같이
쓰게 하기 위해서다. 정의가 두 곳에 따로 있으면 한쪽만 고치는 사고가 난다. 시나리오는 **행 단위가
아니라 날짜 단위**로 뽑는다 — 서빙에서는 하루 전체가 같은 시차 가용성 상태(전날 배치가 아직
안 왔다 등)를 공유하므로, 학습 증강이 그 상황을 재현하려면 같은 날의 모든 슬롯·역이 같은
시나리오를 받아야 한다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

# 143 `nolag_loss.SCENARIOS`와 같은 이름. 값은 남길 시차(일) — None은 전부 남김, 빈 튜플은 전부 마스크.
SCENARIOS: dict[str, tuple[int, ...] | None] = {
    "full": None,
    "d7_only": (7,),
    "d1_only": (1,),
    "no_lag": (),
}


def truncate_history(
    values: np.ndarray, mask: np.ndarray, k: int | np.ndarray, axis: int = -1
) -> tuple[np.ndarray, np.ndarray]:
    """이력 축(`axis`)의 **앞쪽** `k`일을 지운다(값 0, 마스크 0). 입력은 바꾸지 않는다.

    `values`는 `mask`와 같은 이력 축을 가지고 뒤에 채널 축이 더 붙을 수 있다(예: values `[B, N, 20, 2]`,
    mask `[B, N, 20]`, axis=1). `k`는 스칼라 또는 배치 축 길이의 정수 배열(표본별 절단).
    """
    mask = np.asarray(mask)
    values = np.asarray(values)
    axis = axis % mask.ndim
    n = mask.shape[axis]
    k_arr = np.asarray(k)
    if k_arr.ndim == 0:
        keep = np.arange(n) >= int(k_arr)  # [N]
        shape = [1] * mask.ndim
        shape[axis] = n
        keep = keep.reshape(shape)
    else:
        if axis == 0:
            raise ValueError("표본별 k를 쓰려면 배치 축(0)과 이력 축이 달라야 한다.")
        if k_arr.shape[0] != mask.shape[0]:
            raise ValueError(f"k 길이 {k_arr.shape[0]} ≠ 배치 크기 {mask.shape[0]}")
        keep = np.arange(n)[None, :] >= k_arr[:, None]  # [B, N]
        shape = [1] * mask.ndim
        shape[0] = mask.shape[0]
        shape[axis] = n
        keep = keep.reshape(shape)
    new_mask = mask * keep
    extra = values.ndim - mask.ndim
    keep_v = keep.reshape(keep.shape + (1,) * extra)
    new_values = values * keep_v
    return new_values, new_mask


def keep_offsets_mask(
    mask: np.ndarray, offsets: Sequence[int] | None, axis: int = -1
) -> np.ndarray:
    """이력 축에서 지정한 시차(일)만 남긴 마스크. `offsets=None`이면 그대로, `()`면 전부 0.

    시차 `d`는 인덱스 `N−d`다(D−1 → 마지막 자리). N보다 큰 시차는 조용히 무시하지 않고 오류를 낸다 —
    시나리오와 시퀀스 길이가 어긋난 설정을 잡기 위해서다.
    """
    mask = np.asarray(mask)
    if offsets is None:
        return mask.copy()
    axis = axis % mask.ndim
    n = mask.shape[axis]
    keep = np.zeros(n, dtype=mask.dtype)
    for d in offsets:
        if not 1 <= d <= n:
            raise ValueError(f"시차 {d}일은 이력 길이 {n}일 안에 없다.")
        keep[n - d] = 1
    shape = [1] * mask.ndim
    shape[axis] = n
    return mask * keep.reshape(shape)


def apply_scenario(
    values: np.ndarray, mask: np.ndarray, scenario: str, axis: int = -1
) -> tuple[np.ndarray, np.ndarray]:
    """`SCENARIOS` 이름으로 값·마스크를 함께 마스킹한다(값은 마스크 0 자리에서 0)."""
    if scenario not in SCENARIOS:
        raise KeyError(f"모르는 시나리오 {scenario!r} — {list(SCENARIOS)} 중 하나")
    new_mask = keep_offsets_mask(mask, SCENARIOS[scenario], axis=axis)
    extra = np.asarray(values).ndim - new_mask.ndim
    return np.asarray(values) * new_mask.reshape(new_mask.shape + (1,) * extra), new_mask


def sample_truncation(
    rng: np.random.Generator, size: int, seq_days: int, p_full: float = 0.0
) -> np.ndarray:
    """표본별 절단 길이 `k`. 기본은 `U{0..seq_days}`(k=seq_days면 이력 전부 없음).

    `p_full > 0`이면 그 확률로 k=0(절단 없음)을 먼저 뽑고 나머지만 균등으로 채운다.
    """
    if not 0.0 <= p_full <= 1.0:
        raise ValueError("p_full은 0~1")
    k = rng.integers(0, seq_days + 1, size=size)
    if p_full > 0:
        full = rng.random(size) < p_full
        k = np.where(full, 0, k)
    return k.astype(np.int64)


# ── 표형(tabular) 시차 마스킹 — LightGBM 학습·평가용 ──

# 143 `nolag_loss` / `evaluate_dl.LGB_MASK`와 같은 정의. 시나리오 → NaN으로 가리는 컬럼 접두.
LAG_COLUMN_PREFIXES: dict[str, tuple[str, ...]] = {
    "full": (),
    "d7_only": ("lag1d_", "lagsd_"),
    "d1_only": ("lag7d_", "lagsd_"),
    "no_lag": ("lag1d_", "lag7d_", "lagsd_"),
}
assert set(LAG_COLUMN_PREFIXES) == set(
    SCENARIOS
), "LAG_COLUMN_PREFIXES는 SCENARIOS와 이름이 같아야 한다."


def lag_columns_for(scenario: str, feature_cols: Sequence[str]) -> list[str]:
    """`scenario`가 가리는 접두로 시작하는 컬럼을 `feature_cols`에서 고른다(순서 보존).

    `full`은 접두가 없어 빈 리스트. 모르는 시나리오는 `apply_scenario`와 같은 형식으로 KeyError.
    """
    if scenario not in LAG_COLUMN_PREFIXES:
        raise KeyError(f"모르는 시나리오 {scenario!r} — {list(LAG_COLUMN_PREFIXES)} 중 하나")
    prefixes = LAG_COLUMN_PREFIXES[scenario]
    return [c for c in feature_cols if c.startswith(prefixes)]


def mask_lag_columns(
    frame: pd.DataFrame, scenario: str, feature_cols: Sequence[str]
) -> pd.DataFrame:
    """`scenario`가 가리는 시차 컬럼을 NaN으로 덮은 복사본을 돌려준다. 원본은 바꾸지 않는다.

    `feature_cols`에는 있지만 `frame`에 없는 컬럼은 조용히 건너뛴다(피처 세트마다 컬럼 구성이
    다르므로). `full`은 가릴 컬럼이 없어 변경 없는 복사본이 된다.
    """
    out = frame.copy()
    cols = [c for c in lag_columns_for(scenario, feature_cols) if c in out.columns]
    if cols:
        out[cols] = np.nan
    return out


def assign_date_scenarios(
    dates: Sequence, weights: Mapping[str, float], rng: np.random.Generator
) -> pd.Series:
    """고유 날짜마다 시나리오 하나를 `weights` 확률로 뽑는다(범주형 추출).

    행이 아니라 **날짜 단위**로 뽑는 이유는 모듈 docstring 참고 — 서빙은 하루 전체가 같은
    가용성 상태를 공유한다. `weights`의 키는 `SCENARIOS`(=`LAG_COLUMN_PREFIXES`)의 부분집합이어야
    하고(아니면 KeyError), 값은 전부 0 이상이며 합이 1이어야 한다(오차 1e-9, 벗어나면 ValueError).
    반환은 날짜 오름차순으로 정렬된 `pd.Timestamp` 인덱스의 `pd.Series`(값=시나리오 이름)이고,
    같은 `rng` 상태에서는 결정적이다.
    """
    unknown = set(weights) - set(LAG_COLUMN_PREFIXES)
    if unknown:
        raise KeyError(f"모르는 시나리오 {sorted(unknown)} — {list(LAG_COLUMN_PREFIXES)} 중 하나")
    names = list(weights.keys())
    values = np.array([float(weights[n]) for n in names], dtype=float)
    if (values < 0).any():
        raise ValueError("weights는 전부 0 이상이어야 한다.")
    total = values.sum()
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"weights 합이 1이 아니다: {total!r}")

    unique_dates = pd.DatetimeIndex(
        sorted(pd.to_datetime(pd.Series(dates)).dt.normalize().unique())
    )
    picks = rng.choice(names, size=len(unique_dates), p=values / total)
    return pd.Series(picks, index=unique_dates.rename("date"), name="scenario")


def mask_by_date(
    frame: pd.DataFrame,
    date_scenarios: pd.Series | Mapping,
    feature_cols: Sequence[str],
    date_col: str = "date",
) -> pd.DataFrame:
    """`frame`의 각 행에 그 행 날짜의 시나리오 마스크를 적용한 복사본을 돌려준다.

    `date_scenarios`에 없는 날짜가 `frame`에 있으면 조용히 마스킹을 건너뛰지 않고 KeyError를
    낸다 — 어떤 시나리오인지 모르는 날짜를 그대로 두면 "마스킹했다"는 메타와 실제가 어긋난다.
    시나리오별로 행 마스크를 한 번에 만들어(불리언 배열) 해당 컬럼을 NaN 처리한다 — 시나리오
    개수(4개)만큼만 반복하고 행 단위 루프는 쓰지 않는다.
    """
    raw_items = (
        date_scenarios.items()
        if isinstance(date_scenarios, Mapping)
        else date_scenarios.to_dict().items()
    )
    mapping = {pd.Timestamp(k).normalize(): v for k, v in raw_items}
    frame_dates = pd.to_datetime(frame[date_col]).dt.normalize()
    missing = set(frame_dates.unique()) - set(mapping)
    if missing:
        missing_str = sorted(str(pd.Timestamp(d).date()) for d in missing)
        raise KeyError(f"date_scenarios에 없는 날짜: {missing_str}")

    out = frame.copy()
    for scenario in set(mapping.values()):
        scenario_dates = {d for d, s in mapping.items() if s == scenario}
        row_mask = frame_dates.isin(scenario_dates).to_numpy()
        cols = [c for c in lag_columns_for(scenario, feature_cols) if c in out.columns]
        if cols and row_mask.any():
            out.loc[row_mask, cols] = np.nan
    return out


def count_dates_by_scenario(date_scenarios: pd.Series | Mapping) -> dict[str, int]:
    """시나리오별 날짜 수 — 학습 아티팩트 메타 기록용 작은 집계 헬퍼."""
    values = (
        list(date_scenarios.values())
        if isinstance(date_scenarios, Mapping)
        else list(date_scenarios)
    )
    counts = pd.Series(values).value_counts()
    return {str(k): int(v) for k, v in counts.items()}
