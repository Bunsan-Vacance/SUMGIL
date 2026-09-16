"""145 — 통계 모형 비교 검증(`validation/CROWD/stat-model-check/stat_models.py`)의 순수 함수.

폴더명에 하이픈이 있어 `test_crowd_bootstrap_ci.py`와 같은 방식으로 파일 경로로 읽어 온다.
statsmodels가 필요한 SARIMAX 테스트는 `pytest.importorskip`으로 따로 묶어 CI(`requirements-ci.txt`에
statsmodels가 없다)에서는 스킵되고, 순수 numpy/pandas 로직(나이브·OLS)은 항상 돈다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

AI_ROOT = Path(__file__).resolve().parents[2]
_SPEC_PATH = AI_ROOT / "validation" / "CROWD" / "stat-model-check" / "stat_models.py"


def _load_module():
    if str(AI_ROOT) not in sys.path:
        sys.path.insert(0, str(AI_ROOT))
    spec = importlib.util.spec_from_file_location("crowd_stat_models", _SPEC_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sm = _load_module()


# ── 계절 나이브 ──
def test_attach_snaive_uses_raw_value_not_shift():
    """빠진 날짜가 있으면 위치 shift가 아니라 날짜 키 조인 — 그 날이 없으면 NaN이지 이전 값이 아니다."""
    panel = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2025-01-01", "2025-01-02", "2025-01-08", "2025-01-09", "2025-01-15"]
            ),
            "station_no": [1, 1, 1, 1, 1],
            "time_slot": ["06-07"] * 5,
            "boarding": [100.0, 200.0, 300.0, 400.0, 500.0],
            "alighting": [10.0, 20.0, 30.0, 40.0, 50.0],
        }
    )
    out = sm.attach_snaive(panel, day_lag=7)
    row = out.set_index("date")
    # 01-08의 7일 전은 01-01 → 100 그대로 이어진다.
    assert row.loc["2025-01-08", "boarding_snaive"] == pytest.approx(100.0)
    # 01-09의 7일 전은 01-02 → 200.
    assert row.loc["2025-01-09", "boarding_snaive"] == pytest.approx(200.0)
    # 01-15의 7일 전은 01-08(있음) → 300. 위치 shift였다면 "이전 행"인 01-09(400)를 가리켰을 것.
    assert row.loc["2025-01-15", "boarding_snaive"] == pytest.approx(300.0)
    # 01-01·01-02는 7일 전 데이터가 아예 없어 NaN — 0이나 근처 값으로 채우지 않는다.
    assert np.isnan(row.loc["2025-01-01", "boarding_snaive"])
    assert np.isnan(row.loc["2025-01-02", "boarding_snaive"])


# ── OLS ──
def test_fit_ols_recovers_coefficients_on_synthetic_data():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(500, 3))
    true_coef = np.array([2.0, -1.0, 0.5, 3.0])  # 절편 2.0 + 세 계수
    y = true_coef[0] + X @ true_coef[1:]
    coef = sm.fit_ols(X, y, min_valid_rows=10)
    assert coef is not None
    assert coef == pytest.approx(true_coef, abs=1e-8)


def test_fit_ols_ignores_rows_with_nan_feature_or_target():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(200, 2))
    true_coef = np.array([1.0, 2.0, -3.0])
    y = true_coef[0] + X @ true_coef[1:]
    X_dirty = X.copy()
    X_dirty[:50, 0] = np.nan  # 앞 50행은 피처 결측
    y_dirty = y.copy()
    y_dirty[50:70] = np.nan  # 다음 20행은 타깃 결측
    coef = sm.fit_ols(X_dirty, y_dirty, min_valid_rows=10)
    assert coef is not None
    # 유효행(130개)만으로도 계수가 거의 복원된다.
    assert coef == pytest.approx(true_coef, abs=1e-6)


def test_fit_ols_returns_none_when_not_enough_valid_rows():
    X = np.array([[1.0], [2.0], [np.nan], [np.nan], [np.nan]])
    y = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert sm.fit_ols(X, y, min_valid_rows=3) is None  # 유효행 2개 < 3


def test_predict_ols_nan_when_no_coef_or_missing_feature():
    coef = np.array([1.0, 2.0])
    X = np.array([[1.0], [np.nan], [3.0]])
    pred = sm.predict_ols(X, coef)
    assert pred[0] == pytest.approx(3.0)
    assert np.isnan(pred[1])  # 피처 결측 행은 계수가 있어도 값을 채우지 않는다
    assert pred[2] == pytest.approx(7.0)
    # 계수 자체가 없으면(그 시리즈가 학습되지 않음) 전부 NaN
    assert np.all(np.isnan(sm.predict_ols(X, None)))


# ── SARIMAX(statsmodels 필요) ──
def test_sarimax_leakage_guard():
    """d일 값을 바꿔도 d일 예측(1단계 앞)은 변하지 않고, d+1일 예측은 변한다."""
    pytest.importorskip("statsmodels")
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", "2024-08-31", freq="D")
    n = len(dates)
    week = np.arange(n) % 7
    base = 100 + 20 * np.sin(2 * np.pi * week / 7) + rng.normal(scale=3.0, size=n)
    series = pd.Series(base, index=dates)
    split_date = dates[-30]
    forecast_start = dates[-20]

    res_a = sm.fit_predict_sarimax(
        series,
        order=(1, 0, 0),
        seasonal_order=(0, 0, 0, 7),
        split_date=split_date,
        forecast_start=forecast_start,
        trend="c",
    )
    assert res_a["ok"]

    target_day = forecast_start + pd.Timedelta(days=5)
    next_day = target_day + pd.Timedelta(days=1)
    series_b = series.copy()
    series_b.loc[target_day] += 500.0  # 예측 대상 구간 안의 한 날을 크게 바꾼다

    res_b = sm.fit_predict_sarimax(
        series_b,
        order=(1, 0, 0),
        seasonal_order=(0, 0, 0, 7),
        split_date=split_date,
        forecast_start=forecast_start,
        trend="c",
    )
    assert res_b["ok"]
    # d일(target_day) 예측은 d-1까지의 정보만 쓰므로 그 날 자신의 값을 바꿔도 그대로다.
    assert res_a["pred"].loc[target_day] == pytest.approx(res_b["pred"].loc[target_day], abs=1e-6)
    # d+1일 예측은 d일 값을 관측으로 쓰므로 달라진다.
    assert res_a["pred"].loc[next_day] != pytest.approx(res_b["pred"].loc[next_day], abs=1e-6)


def test_sarimax_handles_missing_values_without_raising():
    pytest.importorskip("statsmodels")
    rng = np.random.default_rng(7)
    dates = pd.date_range("2024-01-01", "2024-06-30", freq="D")
    n = len(dates)
    values = 50 + 5 * np.sin(2 * np.pi * (np.arange(n) % 7) / 7) + rng.normal(scale=1.0, size=n)
    series = pd.Series(values, index=dates)
    # 결측 구간을 섞는다(수집 누락 재현) — 채우지 않고 NaN 그대로 둔다.
    series.iloc[10:15] = np.nan
    series.iloc[100:103] = np.nan

    split_date = dates[-20]
    forecast_start = dates[-10]
    res = sm.fit_predict_sarimax(
        series,
        order=(1, 0, 0),
        seasonal_order=(0, 0, 0, 7),
        split_date=split_date,
        forecast_start=forecast_start,
        trend="c",
    )
    assert res["error"] is None
    assert res["ok"]
    assert len(res["pred"]) == int((series.index >= forecast_start).sum())
    assert res["pred"].notna().all()


def test_sarimax_enforce_stationarity_flag_is_passed_through():
    """제약을 켠 변형도 같은 인터페이스로 돌아야 한다 — 발산 재발 방지책 비교의 전제."""
    pytest.importorskip("statsmodels")
    idx = pd.date_range("2024-01-01", "2025-02-28", freq="D")
    rng = np.random.default_rng(0)
    values = 100 + 10 * np.sin(np.arange(len(idx)) * 2 * np.pi / 7) + rng.normal(0, 1, len(idx))
    series = pd.Series(values, index=idx)
    res = sm.fit_predict_sarimax(
        series,
        order=(1, 0, 0),
        seasonal_order=(1, 0, 0, 7),
        split_date=pd.Timestamp("2025-01-01"),
        forecast_start=pd.Timestamp("2025-01-01"),
        trend="c",
        enforce_stationarity=True,
        enforce_invertibility=True,
    )
    assert res["ok"] is True
    assert res["pred"].notna().any()


def test_sarimax_insufficient_train_obs_returns_nan_without_exception():
    pytest.importorskip("statsmodels")
    dates = pd.date_range("2024-01-01", "2024-03-01", freq="D")
    series = pd.Series(np.nan, index=dates)
    series.iloc[:5] = [1.0, 2.0, 3.0, 4.0, 5.0]  # 학습 구간 유효값 5개 < min_train_obs
    split_date = dates[40]
    forecast_start = dates[50]
    res = sm.fit_predict_sarimax(
        series,
        order=(1, 0, 0),
        seasonal_order=(0, 0, 0, 7),
        split_date=split_date,
        forecast_start=forecast_start,
        min_train_obs=30,
    )
    assert not res["ok"]
    assert res["error"] == "insufficient_train_obs"
    assert res["pred"].isna().all()


def test_build_wide_series_and_run_sarima_batch_smoke():
    pytest.importorskip("statsmodels")
    rng = np.random.default_rng(3)
    dates = pd.date_range("2024-01-01", "2024-06-30", freq="D")
    rows = []
    for station in (1, 2):
        for slot in ("06-07", "07-08"):
            n = len(dates)
            vals = 30 + rng.normal(scale=2.0, size=n)
            for d, b, a in zip(dates, vals, vals * 0.5):
                rows.append(
                    {
                        "date": d,
                        "station_no": station,
                        "time_slot": slot,
                        "boarding": b,
                        "alighting": a,
                    }
                )
    frame = pd.DataFrame(rows)
    full_dates = pd.date_range("2024-01-01", "2024-06-30", freq="D")
    wide = sm.build_wide_series(frame, ["boarding", "alighting"], full_dates)
    keys = [c for c in wide.columns if c[0] == "boarding"]
    assert len(keys) == 4  # 역 2 × 슬롯 2

    split_date = dates[-15]
    forecast_start = dates[-10]
    out = sm.run_sarima_batch(
        wide,
        keys,
        order=(1, 0, 0),
        seasonal_order=(0, 0, 0, 7),
        split_date=split_date,
        forecast_start=forecast_start,
        trend="c",
        n_jobs=1,
    )
    assert set(out["station_no"].unique()) == {1, 2}
    assert set(out["time_slot"].unique()) == {"06-07", "07-08"}
    assert (
        out.groupby(["station_no", "time_slot"]).size() == int((dates >= forecast_start).sum())
    ).all()


# ── 청크 캐시 지문 ──
def _sig_frame(values: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "station_no": [150, 150, 150],
            "time_slot": ["08-09"] * 3,
            "boarding": values,
        }
    )


def test_source_signature_changes_when_values_change_but_rows_do_not():
    """행 수·날짜 범위가 같아도 값이 바뀌면 지문이 달라야 한다 — 88번 요일유형 수정판이 그런 경우다."""
    before = sm.source_signature(_sig_frame([1.0, 2.0, 3.0]), ["boarding"])
    after = sm.source_signature(_sig_frame([1.0, 2.0, 4.0]), ["boarding"])
    assert before["rows"] == after["rows"] and before["date_max"] == after["date_max"]
    assert before != after


def test_source_signature_counts_missing_without_filling():
    sig = sm.source_signature(_sig_frame([1.0, np.nan, 3.0]), ["boarding"])
    assert sig["n_finite"] == 2
    assert sig["checksum"] == pytest.approx(4.0)


def test_chunk_cache_valid_survives_json_roundtrip_but_catches_spec_change():
    import json

    spec = {"order": (1, 0, 1), "seasonal_order": (0, 1, 1, 7), "trend": None}
    source = sm.source_signature(_sig_frame([1.0, 2.0, 3.0]), ["boarding"])
    want = sm.chunk_signature(
        source, spec, pd.Timestamp("2025-01-01"), pd.Timestamp("2025-01-01"), [150, 151]
    )
    # 파일에 저장했다 읽은 형태(튜플 → 리스트)여도 같다고 봐야 한다.
    assert sm.chunk_cache_valid(json.loads(json.dumps(want)), want)
    assert not sm.chunk_cache_valid(None, want)

    other_order = sm.chunk_signature(
        {**source},
        {**spec, "order": (2, 0, 1)},
        pd.Timestamp("2025-01-01"),
        pd.Timestamp("2025-01-01"),
        [150, 151],
    )
    assert not sm.chunk_cache_valid(other_order, want)

    enforced = sm.chunk_signature(
        {**source},
        {**spec, "enforce_stationarity": True},
        pd.Timestamp("2025-01-01"),
        pd.Timestamp("2025-01-01"),
        [150, 151],
    )
    assert not sm.chunk_cache_valid(enforced, want)

    other_stations = sm.chunk_signature(
        {**source}, spec, pd.Timestamp("2025-01-01"), pd.Timestamp("2025-01-01"), [150, 152]
    )
    assert not sm.chunk_cache_valid(other_stations, want)

    stale_source = sm.chunk_signature(
        sm.source_signature(_sig_frame([1.0, 2.0, 99.0]), ["boarding"]),
        spec,
        pd.Timestamp("2025-01-01"),
        pd.Timestamp("2025-01-01"),
        [150, 151],
    )
    assert not sm.chunk_cache_valid(stale_source, want)


# ── 발산 처리 ──
def test_divergence_bounds_come_from_train_only():
    """상한은 학습 구간 실측 최댓값 — 평가 구간의 더 큰 값을 보면 안 된다(누수)."""
    train = pd.DataFrame({"boarding": [10.0, 500.0, np.nan], "alighting": [1.0, 2.0, 3.0]})
    bounds = sm.divergence_bounds(train, ["boarding", "alighting"])
    assert bounds["boarding"] == (0.0, 500.0)
    assert bounds["alighting"] == (0.0, 3.0)


def test_apply_bounds_clip_scores_divergence_instead_of_dropping_it():
    """clip은 발산 행을 상한으로 **채점에 남기고**, drop은 결측으로 되돌려 평가에서 뺀다."""
    values = np.array([-3.0, 120.0, 1.0e14, np.nan])
    clipped, counts = sm.apply_bounds(values, 0.0, 1000.0, "clip")
    assert counts == {"n_low": 1, "n_high": 1}
    assert clipped[0] == 0.0  # 음수 인원은 0으로
    assert clipped[1] == 120.0  # 정상 행은 그대로
    assert clipped[2] == 1000.0  # 발산 행이 사라지지 않는다 — 큰 오차로 남는다
    assert np.isnan(clipped[3])

    dropped, counts_drop = sm.apply_bounds(values, 0.0, 1000.0, "drop")
    assert counts_drop == counts
    assert np.isnan(dropped[2])

    raw, counts_raw = sm.apply_bounds(values, 0.0, 1000.0, "raw")
    assert counts_raw == counts
    assert raw[0] == -3.0 and raw[2] == 1.0e14


def test_apply_bounds_rejects_unknown_mode():
    with pytest.raises(ValueError):
        sm.apply_bounds(np.array([1.0]), 0.0, 10.0, "그냥")


# ── 피처 누락 가드 ──
def test_missing_feature_columns_catches_silently_nan_filled_features():
    """`build_matrix`가 없는 컬럼을 NaN으로 채우므로, 평가 전에 여기서 걸러야 한다."""
    feature_cols = ["game_count", "festival_count", "lag1d_boarding_resid"]
    frame_cols = ["date", "station_no", "lag1d_boarding_resid"]
    assert sm.missing_feature_columns(frame_cols, feature_cols) == ["game_count", "festival_count"]
    assert (
        sm.missing_feature_columns([*frame_cols, "game_count", "festival_count"], feature_cols)
        == []
    )
