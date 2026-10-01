"""재학습 루프 통계(`retrain/stats.py`) — 원본(`validation/.../bootstrap.py`)과 같은 결과인지 대조.

원본 import는 `app.CROWD.pipeline.dataset/features/lookup/predictor`를 끌어온다(pandas/numpy/yaml
수준이고 predictor는 lightgbm 등을 지연 import한다). 그래도 환경에 따라 실패할 수 있어 import
실패 시 스킵한다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.CROWD.pipeline.retrain import stats

AI_ROOT = Path(__file__).resolve().parents[2]
_SPEC_PATH = AI_ROOT / "validation" / "CROWD" / "significance-check" / "bootstrap.py"


def _load_original():
    if str(AI_ROOT) not in sys.path:
        sys.path.insert(0, str(AI_ROOT))
    spec = importlib.util.spec_from_file_location("retrain_stats_orig_bootstrap", _SPEC_PATH)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ImportError as exc:  # pragma: no cover - 의존성 없는 환경
        pytest.skip(f"원본 bootstrap.py를 import할 수 없다: {exc}")
    return module


orig = _load_original()


def make_losses(n_dates: int = 60, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = rng.integers(50, 100, size=n_dates).astype(float)
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=n_dates),
            "sse": rng.uniform(1, 5, size=n_dates) * n,
            "sae": rng.uniform(1, 2, size=n_dates) * n,
            "n": n,
        }
    )


def test_pure_functions_match_original():
    n_dates, n_boot, seed = 60, 200, 0
    a = stats.resample_dates(n_dates, n_boot, seed)
    b = orig.resample_dates(n_dates, n_boot, seed)
    assert np.array_equal(a, b)
    counts_a, counts_b = stats.resample_counts(a, n_dates), orig.resample_counts(b, n_dates)
    assert np.array_equal(counts_a, counts_b)

    m, base = make_losses(seed=1), make_losses(seed=2)
    n = m["n"].to_numpy()
    assert np.allclose(
        stats.weighted_rmse(counts_a, m["sse"].to_numpy(), n),
        orig.weighted_rmse(counts_b, m["sse"].to_numpy(), n),
    )
    assert np.allclose(
        stats.weighted_mae(counts_a, m["sae"].to_numpy(), n),
        orig.weighted_mae(counts_b, m["sae"].to_numpy(), n),
    )
    x = stats.weighted_rmse(counts_a, base["sse"].to_numpy(), n)
    y = stats.weighted_rmse(counts_a, m["sse"].to_numpy(), n)
    assert np.allclose(stats.improvement_pct(x, y), orig.improvement_pct(x, y))
    assert stats.percentile_ci(y) == orig.percentile_ci(y)

    diff = (m["sse"] - base["sse"]).to_numpy() / n
    assert stats.diebold_mariano(diff) == orig.diebold_mariano(diff)
    assert stats.default_lags(60) == orig.default_lags(60)
    assert stats.newey_west_variance(diff, 3) == orig.newey_west_variance(diff, 3)


def test_bootstrap_improvement_matches_manual_composition():
    model, base = make_losses(seed=1), make_losses(seed=2)
    # 두 표의 n을 같게 맞춘다(원본은 슬라이스 하나의 n을 공유한다).
    base["n"] = model["n"]
    n_dates = len(model)
    counts = orig.resample_counts(orig.resample_dates(n_dates, 300, 7), n_dates)
    boot = orig.improvement_pct(
        orig.weighted_rmse(counts, base["sse"].to_numpy(), model["n"].to_numpy()),
        orig.weighted_rmse(counts, model["sse"].to_numpy(), model["n"].to_numpy()),
    )
    full = np.ones((1, n_dates))
    point = orig.improvement_pct(
        orig.weighted_rmse(full, base["sse"].to_numpy(), model["n"].to_numpy()),
        orig.weighted_rmse(full, model["sse"].to_numpy(), model["n"].to_numpy()),
    )[0]
    low, high = orig.percentile_ci(boot)

    res = stats.bootstrap_improvement(model, base, n_boot=300, seed=7)
    assert res["point"] == pytest.approx(point)
    assert res["ci_low"] == pytest.approx(low)
    assert res["ci_high"] == pytest.approx(high)
    assert res["n_dates"] == n_dates
    assert res["n_rows"] == int(model["n"].sum())

    rel = stats.bootstrap_relative_rmse(model, base, n_boot=300, seed=7)
    assert rel == res
    assert (
        stats.bootstrap_improvement(model, base, n_boot=50, seed=0, metric="mae")["n_dates"] == 60
    )


def test_bootstrap_improvement_empty_is_nan():
    empty = pd.DataFrame({"date": [], "sse": [], "sae": [], "n": []})
    res = stats.bootstrap_improvement(empty, empty)
    assert res["n_dates"] == 0
    assert np.isnan(res["point"])


def test_stratified_resample_preserves_stratum_counts():
    strata = np.array(["wd"] * 5 + ["we"] * 2 + ["hol"] * 1 + ["wd"] * 4)
    idx = stats.stratified_resample_dates(strata, n_boot=100, seed=0)
    assert idx.shape == (100, len(strata))
    for label in np.unique(strata):
        pos = np.flatnonzero(strata == label)
        # 각 층의 열에는 그 층의 인덱스만 들어간다
        assert np.isin(idx[:, pos], pos).all()
    counts = stats.resample_counts(idx, len(strata))
    assert np.allclose(counts[:, strata == "we"].sum(axis=1), 2)
    assert np.allclose(counts[:, strata == "wd"].sum(axis=1), 9)
    assert np.array_equal(idx, stats.stratified_resample_dates(strata, 100, 0))


def test_block_resample_range_and_length():
    for n_dates in (60, 20, 7, 3):
        idx = stats.block_resample_dates(n_dates, n_boot=50, seed=0, block=7)
        assert idx.shape == (50, n_dates)
        assert idx.min() >= 0
        assert idx.max() < n_dates
    idx = stats.block_resample_dates(30, 10, 0, block=7)
    # 블록 안은 연속 인덱스다
    assert (np.diff(idx[:, :7], axis=1) == 1).all()


def test_bootstrap_improvement_with_strata_and_block_runs():
    model, base = make_losses(seed=1), make_losses(seed=2)
    strata = pd.Series(np.where(np.arange(60) % 7 >= 5, "we", "wd"), index=model["date"])
    plain = stats.bootstrap_improvement(model, base, n_boot=200, seed=0)
    strat = stats.bootstrap_improvement(model, base, n_boot=200, seed=0, strata=strata)
    blocked = stats.bootstrap_improvement(model, base, n_boot=200, seed=0, block=7)
    assert strat["point"] == pytest.approx(plain["point"])
    assert blocked["point"] == pytest.approx(plain["point"])
    assert strat["ci_low"] <= strat["ci_high"]
    assert blocked["ci_low"] <= blocked["ci_high"]


def test_daily_losses_one_row_per_date():
    rows = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-02", "2026-01-01", "2026-01-01", "2026-01-02"]),
            "p": [3.0, 1.0, 2.0, np.nan],
            "a": [1.0, 1.0, 4.0, 5.0],
        }
    )
    out = stats.daily_losses(rows, "p", "a")
    assert out["date"].tolist() == list(pd.to_datetime(["2026-01-01", "2026-01-02"]))
    assert out["n"].tolist() == [2, 1]
    assert out["sse"].tolist() == [4.0, 4.0]
    assert out["sae"].tolist() == [2.0, 2.0]
