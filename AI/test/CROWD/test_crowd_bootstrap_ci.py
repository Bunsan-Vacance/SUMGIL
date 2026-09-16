"""142 2단계 — 날짜 블록 부트스트랩·DM 검정(`validation/CROWD/significance-check/bootstrap.py`)의 순수 함수.

parquet을 읽는 부분(예측·손실 집계)은 데이터가 있어야 돌아가므로 빼고, 재표본·가중 평균·
HAC 분산처럼 입력만으로 결정되는 함수만 검사한다. 폴더명에 하이픈이 있어 파일 경로로 읽어 온다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

AI_ROOT = Path(__file__).resolve().parents[2]
_SPEC_PATH = AI_ROOT / "validation" / "CROWD" / "significance-check" / "bootstrap.py"


def _load_module():
    if str(AI_ROOT) not in sys.path:
        sys.path.insert(0, str(AI_ROOT))
    spec = importlib.util.spec_from_file_location("crowd_significance_bootstrap", _SPEC_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


boot = _load_module()


# ── 재표본 ──
def test_resample_dates_shape_and_range():
    idx = boot.resample_dates(n_dates=365, n_boot=50, seed=0)
    assert idx.shape == (50, 365)
    assert idx.min() >= 0
    assert idx.max() < 365


def test_resample_dates_is_deterministic_per_seed():
    """같은 seed면 항상 같은 재표본 — RESULTS의 CI를 재현할 수 있어야 한다."""
    a = boot.resample_dates(20, 10, seed=7)
    b = boot.resample_dates(20, 10, seed=7)
    c = boot.resample_dates(20, 10, seed=8)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_resample_counts_preserves_total_draws():
    """날짜별 등장 횟수의 합은 언제나 날짜 수와 같다(복원추출 n개를 n번 뽑는다)."""
    idx = boot.resample_dates(30, 25, seed=1)
    counts = boot.resample_counts(idx, 30)
    assert counts.shape == (25, 30)
    assert np.allclose(counts.sum(axis=1), 30)


# ── 가중 평균 ──
def test_weighted_rmse_matches_pooled_formula():
    """가중치가 전부 1이면 날짜별 합을 그대로 모은 RMSE와 같아야 한다."""
    sse = np.array([100.0, 200.0, 300.0])
    n = np.array([10.0, 20.0, 30.0])
    counts = np.ones((1, 3))
    assert boot.weighted_rmse(counts, sse, n)[0] == pytest.approx(np.sqrt(600.0 / 60.0))


def test_weighted_rmse_weights_dates_by_count():
    """한 날짜를 두 번 뽑으면 그 날짜의 제곱오차와 행 수가 둘 다 두 배로 들어간다."""
    sse = np.array([100.0, 0.0])
    n = np.array([10.0, 10.0])
    counts = np.array([[2.0, 0.0], [1.0, 1.0]])
    got = boot.weighted_rmse(counts, sse, n)
    assert got[0] == pytest.approx(np.sqrt(10.0))
    assert got[1] == pytest.approx(np.sqrt(5.0))


def test_weighted_mae_and_improvement_pct():
    sae = np.array([50.0, 50.0])
    n = np.array([10.0, 10.0])
    mae = boot.weighted_mae(np.ones((1, 2)), sae, n)
    assert mae[0] == pytest.approx(5.0)
    # lookup 10 → 모델 7.5면 개선율 25%
    assert boot.improvement_pct(np.array([10.0]), np.array([7.5]))[0] == pytest.approx(25.0)
    # 기준선이 0이면 개선율이 정의되지 않는다 — 0으로 채우지 않는다(원칙 8)
    assert np.isnan(boot.improvement_pct(np.array([0.0]), np.array([1.0]))[0])


def test_percentile_ci_drops_nan_and_orders():
    samples = np.concatenate([np.arange(1.0, 1001.0), [np.nan, np.nan]])
    low, high = boot.percentile_ci(samples, level=0.95)
    assert low < high
    assert low == pytest.approx(25.975, abs=0.5)
    assert high == pytest.approx(975.025, abs=0.5)
    assert np.isnan(boot.percentile_ci(np.array([np.nan]))[0])


# ── HAC · DM ──
def test_newey_west_variance_zero_lag_is_sample_variance():
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert boot.newey_west_variance(x, lags=0) == pytest.approx(float(np.var(x)))


def test_newey_west_variance_absorbs_positive_autocorrelation():
    """양의 자기상관이 있으면 장기 분산은 단순 분산보다 커진다 — 그래서 CI가 넓어진다."""
    rng = np.random.default_rng(0)
    noise = rng.normal(size=400)
    ar1 = np.zeros(400)
    for i in range(1, 400):
        ar1[i] = 0.7 * ar1[i - 1] + noise[i]
    assert boot.newey_west_variance(ar1, lags=8) > boot.newey_west_variance(ar1, lags=0)


def test_default_lags_standard_rule():
    assert boot.default_lags(365) == 5
    assert boot.default_lags(100) == 4
    assert boot.default_lags(1) >= 1


def test_diebold_mariano_sign_and_symmetry():
    """손실차가 음수로 치우치면 통계량도 음수(모델이 낫다)이고, 부호를 뒤집으면 대칭이다."""
    rng = np.random.default_rng(3)
    diff = -2.0 + rng.normal(scale=0.5, size=200)
    got = boot.diebold_mariano(diff)
    assert got["stat"] < 0
    assert got["p"] < 1e-6
    flipped = boot.diebold_mariano(-diff)
    assert flipped["stat"] == pytest.approx(-got["stat"])
    assert flipped["p"] == pytest.approx(got["p"])


def test_diebold_mariano_needs_enough_dates():
    got = boot.diebold_mariano(np.array([1.0, 2.0]))
    assert got["n"] == 2
    assert np.isnan(got["stat"])


# ── 표 조립 ──
def test_bootstrap_table_reproduces_point_estimate():
    """전체 표본(가중치 1)의 개선율은 점추정과 같고, CI가 그 값을 감싼다."""
    dates = pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"])
    losses = pd.DataFrame(
        {
            "date": dates,
            "group": "전체",
            "axis": "전체",
            "target": "boarding",
            "n": [100.0] * 4,
            "sse_lookup": [400.0, 400.0, 400.0, 400.0],
            "sae_lookup": [200.0, 200.0, 200.0, 200.0],
            "sse_model": [100.0, 100.0, 100.0, 100.0],
            "sae_model": [100.0, 100.0, 100.0, 100.0],
        }
    )
    table = boot.bootstrap_table(losses, n_boot=50, seed=0)
    row = table.iloc[0]
    assert row["RMSE_개선율_%"] == pytest.approx(50.0)  # rmse 2.0 → 1.0
    assert row["MAE_개선율_%"] == pytest.approx(50.0)  # mae 2.0 → 1.0
    assert row["RMSE_CI_low"] <= row["RMSE_개선율_%"] <= row["RMSE_CI_high"]
    assert row["n_rows"] == 400
    assert row["n_dates"] == 4
