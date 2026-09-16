"""app/CROWD/pipeline/masking.py — 이력 절단·시나리오 마스킹(numpy 순수 함수, CI에서 돈다)."""

from __future__ import annotations

import numpy as np
import pytest

from app.CROWD.pipeline.masking import (
    SCENARIOS,
    apply_scenario,
    keep_offsets_mask,
    sample_truncation,
    truncate_history,
)

B, N, SLOTS, CH = 3, 5, 4, 2


def _batch():
    rng = np.random.default_rng(0)
    values = rng.normal(size=(B, N, SLOTS, CH)).astype("float32")
    mask = np.ones((B, N, SLOTS), dtype="float32")
    return values, mask


def test_truncate_scalar_k_zeroes_front_days_only():
    values, mask = _batch()
    v, m = truncate_history(values, mask, k=2, axis=1)
    assert m[:, :2].sum() == 0 and m[:, 2:].all()
    assert np.all(v[:, :2] == 0) and np.array_equal(v[:, 2:], values[:, 2:])
    # 입력은 그대로
    assert mask.all()


def test_truncate_per_sample_k():
    values, mask = _batch()
    v, m = truncate_history(values, mask, k=np.array([0, N, 3]), axis=1)
    assert m[0].all()  # 절단 없음
    assert m[1].sum() == 0 and np.all(v[1] == 0)  # 이력 전부 없음
    assert m[2, :3].sum() == 0 and m[2, 3:].all()


def test_truncate_rejects_wrong_k_length():
    values, mask = _batch()
    with pytest.raises(ValueError):
        truncate_history(values, mask, k=np.array([1, 2]), axis=1)


def test_keep_offsets_maps_d1_to_last_index():
    mask = np.ones((B, N, SLOTS), dtype="float32")
    m = keep_offsets_mask(mask, (1,), axis=1)
    assert m[:, -1].all() and m[:, :-1].sum() == 0
    m7 = keep_offsets_mask(mask, (5,), axis=1)  # D−5 → 인덱스 0
    assert m7[:, 0].all() and m7[:, 1:].sum() == 0
    assert keep_offsets_mask(mask, None, axis=1).all()
    assert keep_offsets_mask(mask, (), axis=1).sum() == 0
    with pytest.raises(ValueError):
        keep_offsets_mask(mask, (6,), axis=1)


def test_scenarios_match_143_names_and_zero_values_where_masked():
    assert set(SCENARIOS) == {"full", "d7_only", "d1_only", "no_lag"}
    values, mask = _batch()
    v, m = apply_scenario(values, mask, "no_lag", axis=1)
    assert m.sum() == 0 and np.all(v == 0)
    v, m = apply_scenario(values, mask, "d1_only", axis=1)
    assert np.array_equal(v[:, -1], values[:, -1]) and np.all(v[:, :-1] == 0)
    with pytest.raises(KeyError):
        apply_scenario(values, mask, "d3_only", axis=1)


def test_sample_truncation_range_and_p_full():
    rng = np.random.default_rng(1)
    k = sample_truncation(rng, 2000, seq_days=14)
    assert k.min() == 0 and k.max() == 14  # k=14 = 이력 전부 없음도 나온다
    k_full = sample_truncation(np.random.default_rng(1), 2000, seq_days=14, p_full=1.0)
    assert (k_full == 0).all()
    with pytest.raises(ValueError):
        sample_truncation(rng, 10, 14, p_full=1.5)
