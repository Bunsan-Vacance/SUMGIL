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
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

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
