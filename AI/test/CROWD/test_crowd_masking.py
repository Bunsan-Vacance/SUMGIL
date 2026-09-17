"""app/CROWD/pipeline/masking.py — 이력 절단·시나리오 마스킹(numpy)과 표형 시차 마스킹(pandas).

둘 다 무거운 의존성이 없어(numpy·pandas·pytest) CI에서 그대로 돈다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from app.CROWD.pipeline.features import FEATURE_SETS
from app.CROWD.pipeline.masking import (
    LAG_COLUMN_PREFIXES,
    SCENARIOS,
    apply_scenario,
    assign_date_scenarios,
    count_dates_by_scenario,
    keep_offsets_mask,
    lag_columns_for,
    mask_by_date,
    mask_lag_columns,
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


# ── 표형(tabular) 시차 마스킹 ──

DEPLOY_SET = "festival_selflag_d1sd_d7_resid"
LAG_COLS_6 = [
    "lag1d_boarding_resid",
    "lag1d_alighting_resid",
    "lag7d_boarding_resid",
    "lag7d_alighting_resid",
    "lagsd_boarding_resid",
    "lagsd_alighting_resid",
]


def _load_lgb_mask_literal() -> dict[str, tuple[str, ...]]:
    """`evaluate_dl.py`를 import하지 않고(torch 의존) `LGB_MASK` 딕셔너리 리터럴만 파싱한다."""
    path = (
        Path(__file__).resolve().parents[2]
        / "validation"
        / "CROWD"
        / "dl-resid-check"
        / "evaluate_dl.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            target = node.targets[0]
        if target is not None and target.id == "LGB_MASK":
            return {k: tuple(v) for k, v in ast.literal_eval(node.value).items()}
    raise AssertionError("evaluate_dl.py에서 LGB_MASK 정의를 찾지 못했다.")


def test_lag_column_prefixes_keys_match_scenarios():
    assert set(LAG_COLUMN_PREFIXES) == set(SCENARIOS)


def test_lag_column_prefixes_matches_evaluate_dl_lgb_mask():
    assert LAG_COLUMN_PREFIXES == _load_lgb_mask_literal()


def test_lag_columns_for_picks_prefixed_columns_from_deploy_set():
    cols = FEATURE_SETS[DEPLOY_SET]
    assert lag_columns_for("full", cols) == []
    assert set(lag_columns_for("d1_only", cols)) == {
        c for c in cols if c.startswith(("lag7d_", "lagsd_"))
    }
    assert set(lag_columns_for("d7_only", cols)) == {
        c for c in cols if c.startswith(("lag1d_", "lagsd_"))
    }
    assert set(lag_columns_for("no_lag", cols)) == {
        c for c in cols if c.startswith(("lag1d_", "lag7d_", "lagsd_"))
    }
    with pytest.raises(KeyError):
        lag_columns_for("d3_only", cols)


def test_mask_lag_columns_masks_only_named_columns_and_does_not_mutate():
    frame = pd.DataFrame(
        {
            "lag1d_boarding_resid": [1.0, 2.0],
            "lag7d_boarding_resid": [3.0, 4.0],
            "lagsd_boarding_resid": [5.0, 6.0],
            "other": [7.0, 8.0],
        }
    )
    original = frame.copy()

    out = mask_lag_columns(frame, "d1_only", list(frame.columns))
    assert out["lag7d_boarding_resid"].isna().all()
    assert out["lagsd_boarding_resid"].isna().all()
    unchanged = ["lag1d_boarding_resid", "other"]
    assert_frame_equal(out[unchanged], frame[unchanged])
    assert_frame_equal(frame, original)  # 입력 불변

    full_out = mask_lag_columns(frame, "full", list(frame.columns))
    assert_frame_equal(full_out, frame)


def test_assign_date_scenarios_one_per_unique_date_and_deterministic():
    dates = pd.to_datetime(["2025-01-01", "2025-01-01", "2025-01-02", "2025-01-03"])
    weights = {"full": 0.5, "no_lag": 0.5}
    s1 = assign_date_scenarios(dates, weights, np.random.default_rng(0))
    s2 = assign_date_scenarios(dates, weights, np.random.default_rng(0))
    assert len(s1) == 3  # 고유 날짜 수
    assert set(s1.to_numpy()) <= set(weights)
    pd.testing.assert_series_equal(s1, s2)


def test_assign_date_scenarios_rejects_bad_weights_and_unknown_keys():
    dates = pd.date_range("2025-01-01", periods=5)
    with pytest.raises(ValueError):
        assign_date_scenarios(dates, {"full": 0.4, "no_lag": 0.4}, np.random.default_rng(0))
    with pytest.raises(KeyError):
        assign_date_scenarios(dates, {"d3_only": 1.0}, np.random.default_rng(0))


def test_assign_date_scenarios_empirical_shares_match_weights():
    dates = pd.date_range("2020-01-01", periods=2000)
    weights = {"full": 0.5, "d7_only": 0.3, "no_lag": 0.2}
    picks = assign_date_scenarios(dates, weights, np.random.default_rng(0))
    shares = picks.value_counts(normalize=True)
    for name, w in weights.items():
        assert abs(shares.get(name, 0.0) - w) < 0.05


def _small_frame_for_mask_by_date() -> pd.DataFrame:
    dates = pd.to_datetime(["2025-02-01", "2025-02-02", "2025-02-03"])
    rows = []
    for d in dates:
        for station in (1, 2):
            for slot in range(3):
                row = {"date": d, "station_no": station, "slot": slot}
                row.update({c: 1.0 for c in LAG_COLS_6})
                rows.append(row)
    return pd.DataFrame(rows)


def test_mask_by_date_applies_per_date_scenario_and_rejects_unmapped_dates():
    frame = _small_frame_for_mask_by_date()
    d1, d2, d3 = sorted(frame["date"].unique())
    date_scenarios = {
        pd.Timestamp(d1): "full",
        pd.Timestamp(d2): "d7_only",
        pd.Timestamp(d3): "no_lag",
    }
    out = mask_by_date(frame, date_scenarios, LAG_COLS_6)

    def _nan_cols(day):
        sub = out[out["date"] == day]
        return {c for c in LAG_COLS_6 if sub[c].isna().all()}

    assert _nan_cols(d1) == set()
    assert _nan_cols(d2) == {
        "lag1d_boarding_resid",
        "lag1d_alighting_resid",
        "lagsd_boarding_resid",
        "lagsd_alighting_resid",
    }
    assert _nan_cols(d3) == set(LAG_COLS_6)

    partial = {k: v for k, v in date_scenarios.items() if k != pd.Timestamp(d3)}
    with pytest.raises(KeyError):
        mask_by_date(frame, partial, LAG_COLS_6)


def test_count_dates_by_scenario_counts_without_absent_keys():
    scenarios = pd.Series(
        ["d7_only", "d7_only", "no_lag"], index=pd.date_range("2025-01-01", periods=3)
    )
    assert count_dates_by_scenario(scenarios) == {"d7_only": 2, "no_lag": 1}
