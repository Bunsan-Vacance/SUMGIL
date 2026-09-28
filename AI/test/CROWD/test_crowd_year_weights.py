"""227 — 연도 표본 가중 학습·기상 실험 세트.

`app/CROWD/pipeline/{lookup,train,dataset,features}.py`에 더한 것들을 검증한다. `train_models`
스택 프레임 테스트는 `_fit_lgbm`을 monkeypatch로 갈아치워 실제 학습을 하지 않으므로 lightgbm이
없어도 돈다 — 실제 lightgbm 호출을 확인하는 테스트만 `pytest.importorskip("lightgbm")`으로
따로 감싼다(`AI/CLAUDE.md` 무거운 의존성 가드).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import app.CROWD.pipeline.train as train_module
from app.CROWD.pipeline.dataset import _cache_compatible
from app.CROWD.pipeline.features import (
    FEATURE_SETS,
    SLOT_ORDER,
    WEATHER_COLS,
    add_derived_columns,
    build_matrix,
)
from app.CROWD.pipeline.lookup import DayTypeLookupBaseline
from app.CROWD.pipeline.train import (
    parse_year_weights,
    year_weight_series,
    year_weights_label,
)

DEPLOY_SET = "festival_selflag_d1sd_d7_resid"


# ── lookup.py: 가중 lookup ──


def _small_train() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "day_type": ["평일", "평일", "평일", "토요일"],
            "station_no": [1, 1, 1, 1],
            "time_slot": ["06-07"] * 4,
            "boarding": [10.0, 20.0, np.nan, 5.0],
            "alighting": [1.0, 2.0, 3.0, 4.0],
        }
    )


def test_lookup_fit_without_weights_matches_plain_mean():
    train = _small_train()
    got = DayTypeLookupBaseline().fit(train).table_
    expect = (
        train.groupby(["day_type", "station_no", "time_slot"], observed=True)[
            ["boarding", "alighting"]
        ]
        .mean()
        .reset_index()
    )
    pd.testing.assert_frame_equal(got, expect)


def test_lookup_fit_with_weights_matches_hand_calc_and_drops_weight_for_nan_target():
    train = _small_train()
    weights = pd.Series([1.0, 3.0, 5.0, 2.0])
    table = DayTypeLookupBaseline().fit(train, weights=weights).table_
    row = table[(table["day_type"] == "평일") & (table["time_slot"] == "06-07")].iloc[0]
    # boarding: 세 번째 행(가중 5)이 NaN이라 분모에서 빠진다 — (1*10+3*20)/(1+3)
    assert row["boarding"] == pytest.approx((1 * 10 + 3 * 20) / (1 + 3))
    # alighting: 세 행 모두 유효 — (1*1+3*2+5*3)/(1+3+5)
    assert row["alighting"] == pytest.approx((1 * 1 + 3 * 2 + 5 * 3) / (1 + 3 + 5))
    sat = table[table["day_type"] == "토요일"].iloc[0]
    assert sat["boarding"] == pytest.approx(5.0)
    assert sat["alighting"] == pytest.approx(4.0)


def test_lookup_fit_rejects_length_mismatch():
    train = _small_train()
    with pytest.raises(ValueError):
        DayTypeLookupBaseline().fit(train, weights=pd.Series([1.0, 2.0]))


def test_lookup_fit_rejects_negative_weights():
    train = _small_train()
    with pytest.raises(ValueError):
        DayTypeLookupBaseline().fit(train, weights=pd.Series([-1.0, 2.0, 3.0, 4.0]))


# ── train.py: parse_year_weights / year_weights_label / year_weight_series ──


def test_parse_year_weights_none_and_blank_return_none():
    assert parse_year_weights(None) is None
    assert parse_year_weights("") is None
    assert parse_year_weights("   ") is None


def test_parse_year_weights_parses_valid_string():
    assert parse_year_weights("2022:0.25,2023:0.5") == {2022: 0.25, 2023: 0.5}


def test_parse_year_weights_rejects_missing_colon():
    with pytest.raises(SystemExit):
        parse_year_weights("2022-0.25")


def test_parse_year_weights_rejects_zero_or_negative_weight():
    with pytest.raises(SystemExit):
        parse_year_weights("2022:0")
    with pytest.raises(SystemExit):
        parse_year_weights("2022:-0.1")


def test_parse_year_weights_rejects_duplicate_year():
    with pytest.raises(SystemExit):
        parse_year_weights("2022:0.25,2022:0.5")


def test_parse_year_weights_rejects_non_numeric_year_or_weight():
    with pytest.raises(SystemExit):
        parse_year_weights("abcd:0.5")
    with pytest.raises(SystemExit):
        parse_year_weights("2022:abcd")


def test_year_weights_label_none_or_empty_is_literal_none():
    assert year_weights_label(None) == "none"
    assert year_weights_label({}) == "none"


def test_year_weights_label_sorts_years_ascending():
    assert year_weights_label({2023: 0.5, 2022: 0.25}) == "2022:0.25,2023:0.5"


def test_year_weight_series_defaults_unlisted_years_to_one_and_keeps_index():
    dates = pd.Series(pd.to_datetime(["2022-06-01", "2023-06-01", "2024-06-01"]), index=[5, 6, 7])
    out = year_weight_series(dates, {2022: 0.25})
    assert list(out.index) == [5, 6, 7]
    np.testing.assert_allclose(out.to_numpy(), [0.25, 1.0, 1.0])


def test_year_weight_series_none_weights_is_all_ones():
    dates = pd.Series(pd.to_datetime(["2022-06-01", "2023-06-01"]))
    out = year_weight_series(dates, None)
    np.testing.assert_allclose(out.to_numpy(), [1.0, 1.0])


# ── train.py: _fit_lgbm이 sample_weight를 fit에 전달 ──


def test_fit_lgbm_forwards_sample_weight_to_model_fit(monkeypatch):
    lgb = pytest.importorskip("lightgbm")
    captured: dict[str, object] = {}

    def fake_fit(self, X, y, sample_weight=None):
        captured["sample_weight"] = sample_weight
        return self

    monkeypatch.setattr(lgb.LGBMRegressor, "fit", fake_fit)

    X = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    y = pd.Series([1.0, 2.0, 3.0])
    w = np.array([1.0, 2.0, 3.0])

    train_module._fit_lgbm(X, y, train_module.DEFAULT_PARAMS, sample_weight=w)
    np.testing.assert_array_equal(captured["sample_weight"], w)

    train_module._fit_lgbm(X, y, train_module.DEFAULT_PARAMS)
    assert captured["sample_weight"] is None


# ── train.py: train_models이 stack 증강 프레임에서 연도 가중을 계산 ──


def _min_train_frame() -> pd.DataFrame:
    """`events_station_time_festival`(파생 불필요)만 쓰는 2행 프레임 — 하나는 2024, 하나는 2025."""
    return pd.DataFrame(
        {
            "date": [pd.Timestamp("2024-12-31"), pd.Timestamp("2025-01-01")],
            "station_no": [1, 1],
            "time_slot": ["06-07", "06-07"],
            "day_type": ["평일", "평일"],
            "boarding": [10.0, 20.0],
            "alighting": [5.0, 6.0],
            "game_count": [0, 0],
            "festival_count": [0, 0],
            "festival_short_count": [0, 0],
            "festival_long_count": [0, 0],
            "festival_min_duration_days": [np.nan, np.nan],
        }
    )


def test_train_models_stack_frame_gets_weight_per_row_and_copy_matches_original_year(monkeypatch):
    original = _min_train_frame()
    stacked = pd.concat([original, original], ignore_index=True)  # 원본 2행 + 사본 2행
    lookup = DayTypeLookupBaseline().fit(original)

    captured: list[np.ndarray] = []

    def fake_fit_lgbm(X, y, params, sample_weight=None):
        captured.append(sample_weight)
        return "dummy-model"

    monkeypatch.setattr(train_module, "_fit_lgbm", fake_fit_lgbm)

    year_weights = {2024: 0.25, 2025: 1.0}
    train_module.train_models(
        stacked,
        lookup,
        "events_station_time_festival",
        params=train_module.DEFAULT_PARAMS,
        year_weights=year_weights,
    )

    assert len(captured) == 2  # boarding, alighting 타깃당 한 번(그룹 없음)
    for sw in captured:
        assert sw is not None
        assert len(sw) == len(stacked)
        # 인덱스 0·2는 2024-12-31(원본·사본), 1·3은 2025-01-01(원본·사본) — 같은 날짜는 같은 가중.
        assert sw[0] == sw[2] == pytest.approx(0.25)
        assert sw[1] == sw[3] == pytest.approx(1.0)


def test_train_models_without_year_weights_passes_none_sample_weight(monkeypatch):
    original = _min_train_frame()
    lookup = DayTypeLookupBaseline().fit(original)

    captured: list[object] = []

    def fake_fit_lgbm(X, y, params, sample_weight=None):
        captured.append(sample_weight)
        return "dummy-model"

    monkeypatch.setattr(train_module, "_fit_lgbm", fake_fit_lgbm)
    train_module.train_models(
        original, lookup, "events_station_time_festival", params=train_module.DEFAULT_PARAMS
    )
    assert captured == [None, None]


# ── dataset.py: _cache_compatible ──


def test_cache_compatible_old_meta_without_lookup_weights_matches_default_want():
    have = {"panel_file": "p.parquet", "panel_mtime": 1.0, "panel_rows": 10, "lookup_keys": ["k"]}
    want = {**have, "lookup_weights": "none", "events_file": None, "events_mtime": None}
    assert _cache_compatible(have, want)


def test_cache_compatible_old_meta_incompatible_with_explicit_weight_want():
    have = {"panel_file": "p.parquet", "panel_mtime": 1.0, "panel_rows": 10, "lookup_keys": ["k"]}
    want = {**have, "lookup_weights": "2024:1.0", "events_file": None, "events_mtime": None}
    assert not _cache_compatible(have, want)


def test_cache_compatible_same_weight_label_is_compatible():
    base = {"panel_file": "p.parquet", "panel_mtime": 1.0, "panel_rows": 10, "lookup_keys": ["k"]}
    have = {**base, "lookup_weights": "2024:1.0", "events_file": None, "events_mtime": None}
    want = {**base, "lookup_weights": "2024:1.0", "events_file": None, "events_mtime": None}
    assert _cache_compatible(have, want)


def test_cache_compatible_ignores_split_date_from_old_validation_meta():
    have = {
        "panel_file": "p.parquet",
        "panel_mtime": 1.0,
        "panel_rows": 10,
        "lookup_keys": ["k"],
        "split_date": "2025-01-01",
    }
    want = {
        "panel_file": "p.parquet",
        "panel_mtime": 1.0,
        "panel_rows": 10,
        "lookup_keys": ["k"],
        "lookup_weights": "none",
        "events_file": None,
        "events_mtime": None,
    }
    assert _cache_compatible(have, want)


def test_cache_compatible_old_meta_missing_events_keys_compatible_when_want_default():
    """옛 메타엔 events_file/events_mtime 키 자체가 없다 — want가 기본(None)이면 호환."""
    have = {
        "panel_file": "p.parquet",
        "panel_mtime": 1.0,
        "panel_rows": 10,
        "lookup_keys": ["k"],
        "lookup_weights": "none",
    }
    want = {**have, "events_file": None, "events_mtime": None}
    assert _cache_compatible(have, want)


def test_cache_compatible_old_meta_incompatible_when_want_specifies_events_file():
    """옛 메타(이벤트 지문 없음) + want가 이벤트 표를 명시 — 재빌드를 유도해야 하니 비호환."""
    have = {
        "panel_file": "p.parquet",
        "panel_mtime": 1.0,
        "panel_rows": 10,
        "lookup_keys": ["k"],
        "lookup_weights": "none",
    }
    want = {
        **have,
        "events_file": "crowd_station_events_2024_2025.parquet",
        "events_mtime": 123.0,
    }
    assert not _cache_compatible(have, want)


def test_cache_compatible_same_events_file_and_mtime_is_compatible():
    base = {
        "panel_file": "p.parquet",
        "panel_mtime": 1.0,
        "panel_rows": 10,
        "lookup_keys": ["k"],
        "lookup_weights": "none",
    }
    have = {**base, "events_file": "events.parquet", "events_mtime": 42.0}
    want = {**base, "events_file": "events.parquet", "events_mtime": 42.0}
    assert _cache_compatible(have, want)


# ── features.py: 기상 실험 세트(227) ──

SEGMENTS = [{"line": "L1", "segment": "본선", "stations": [1, 2]}]


def _weather_panel(days=10):
    rows = []
    for d in range(days):
        date = pd.Timestamp("2025-01-01") + pd.Timedelta(days=d)
        for s in (1, 2):
            for i, slot in enumerate(SLOT_ORDER[:3]):
                rows.append(
                    {
                        "date": date,
                        "station_no": s,
                        "station_name": f"S{s}",
                        "line": "L1",
                        "time_slot": slot,
                        "day_type": "평일" if date.dayofweek < 5 else "토요일",
                        "boarding": float(10 * s + i),
                        "alighting": float(5 * s + i),
                        "game_count": 0,
                        "festival_count": 0,
                        "festival_short_count": 0,
                        "festival_long_count": 0,
                        "festival_min_duration_days": np.nan,
                        "temp_c": 10.0 + i,
                        "precip_mm": 0.0,
                        "wind_ms": 1.0 + i * 0.1,
                        "humidity_pct": 50.0,
                        "snow_cm": 0.0,
                    }
                )
    return pd.DataFrame(rows)


def test_weather_feature_set_is_deploy_set_plus_weather_cols():
    deploy = FEATURE_SETS[DEPLOY_SET]
    weather = FEATURE_SETS[f"{DEPLOY_SET}_weather"]
    assert weather == deploy + WEATHER_COLS


def test_build_matrix_returns_weather_columns_and_raises_when_missing():
    panel = _weather_panel()
    lookup = DayTypeLookupBaseline().fit(panel)
    derived = add_derived_columns(panel, lookup, SEGMENTS)

    X = build_matrix(derived, f"{DEPLOY_SET}_weather")
    for col in WEATHER_COLS:
        assert col in X.columns
    pd.testing.assert_frame_equal(X[WEATHER_COLS], derived[WEATHER_COLS])

    missing = derived.drop(columns=WEATHER_COLS)
    with pytest.raises(KeyError, match="temp_c"):
        build_matrix(missing, f"{DEPLOY_SET}_weather")


# ── train.py: run()의 --year-weights 가드는 패널 로딩 전에 걸린다 ──


def test_run_requires_derived_cache_with_year_weights_before_loading_panel():
    with pytest.raises(SystemExit, match="year-weights"):
        train_module.run(DEPLOY_SET, year_weights={2024: 1.0})
