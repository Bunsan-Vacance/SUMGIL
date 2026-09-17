"""app/CROWD/pipeline/{train,predict}.py — 학습→아티팩트→추론 round-trip.

lightgbm은 requirements-ci.txt에 없어 CI에서는 스킵된다(`AI/CLAUDE.md` 무거운 의존성 가드).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("lightgbm")

from app.CROWD.pipeline.features import FEATURE_SETS, SLOT_ORDER, add_derived_columns, build_matrix
from app.CROWD.pipeline.lookup import DayTypeLookupBaseline
from app.CROWD.pipeline.masking import assign_date_scenarios, lag_columns_for
from app.CROWD.pipeline.predict import CrowdPredictor, predict_for_date
from app.CROWD.pipeline.train import (
    REPLACE_WEIGHTS,
    STACK_WEIGHTS,
    MaskingSpec,
    apply_masking,
    save_artifact,
    train_models,
)

SEGMENTS = [{"line": "L1", "segment": "본선", "stations": [1, 2, 3]}]
SMALL_PARAMS = {"n_estimators": 20, "num_leaves": 7, "min_child_samples": 5}
DEPLOY_SET = "festival_selflag_d1sd_d7_resid"


def _panel(days=30, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(days):
        date = pd.Timestamp("2025-01-01") + pd.Timedelta(days=d)
        for s in (1, 2, 3):
            for i, slot in enumerate(SLOT_ORDER[:4]):
                rows.append(
                    {
                        "date": date,
                        "station_no": s,
                        "station_name": f"S{s}",
                        "line": "L1",
                        "time_slot": slot,
                        "day_type": "평일" if date.dayofweek < 5 else "토요일",
                        "boarding": float(100 * s + 10 * i + rng.normal(0, 5)),
                        "alighting": float(80 * s + 5 * i + rng.normal(0, 5)),
                        "game_count": int(d % 9 == 0),
                        "festival_count": 0,
                        "festival_short_count": 0,
                        "festival_long_count": 0,
                        "festival_min_duration_days": np.nan,
                    }
                )
    return pd.DataFrame(rows)


def _fit(panel, group_col=None, feature_set="festival_all_derived_resid"):
    lookup = DayTypeLookupBaseline().fit(panel)
    derived = add_derived_columns(panel, lookup, SEGMENTS)
    models = train_models(derived, lookup, feature_set, SMALL_PARAMS, group_col)
    return lookup, derived, models


def _meta(feature_set, group_col=None):
    from app.CROWD.pipeline.features import CATEGORICAL_COLS, FEATURE_SETS

    return {
        "feature_set": feature_set,
        "feature_columns": FEATURE_SETS[feature_set],
        "categorical_columns": [c for c in CATEGORICAL_COLS if c in FEATURE_SETS[feature_set]],
        "targets": ["boarding", "alighting"],
        "lookup_keys": ["day_type", "station_no", "time_slot"],
        "group_col": group_col,
        "derived_version": 1,
    }


def test_train_predict_roundtrip_matches_in_memory_prediction(tmp_path):
    panel = _panel()
    lookup, derived, models = _fit(panel)
    out_dir = save_artifact(tmp_path / "art", lookup, models, _meta("festival_all_derived_resid"))
    assert {p.name for p in out_dir.iterdir()} >= {
        "lookup.parquet",
        "model_boarding.txt",
        "model_alighting.txt",
        "meta.json",
    }

    predictor = CrowdPredictor(out_dir)
    pred = predictor.predict(panel, SEGMENTS)
    assert len(pred) == len(panel)
    # 메모리 모델로 직접 재구성한 값과 같아야 한다.
    from app.CROWD.pipeline.features import build_matrix

    X = build_matrix(derived, "festival_all_derived_resid")
    expect = lookup.predict(derived)["boarding"].to_numpy() + models["boarding"]["__all__"].predict(
        X
    )
    np.testing.assert_allclose(pred["boarding_pred"].to_numpy(), expect, rtol=1e-6)
    # in-sample이면 lookup보다 잔차 모델이 더 맞아야 한다.
    err_model = np.abs(pred["boarding_pred"] - panel["boarding"]).mean()
    err_lookup = np.abs(pred["boarding_lookup"] - panel["boarding"]).mean()
    assert err_model < err_lookup


def test_grouped_models_pick_booster_by_group_value(tmp_path):
    panel = _panel()
    panel.loc[panel["station_no"] == 3, "line"] = "L2"
    lookup, _, models = _fit(panel, group_col="line")
    assert set(models["boarding"]) == {"L1", "L2"}
    out_dir = save_artifact(
        tmp_path / "art", lookup, models, _meta("festival_all_derived_resid", "line")
    )
    assert (out_dir / "model_boarding__L2.txt").exists()
    pred = CrowdPredictor(out_dir).predict(panel, SEGMENTS)
    assert pred["boarding_pred"].notna().all()


def test_predict_for_date_returns_only_target_day_with_lags_available(tmp_path):
    panel = _panel()
    lookup, _, models = _fit(panel, feature_set="festival_selflag_d1d7_resid")
    out_dir = save_artifact(tmp_path / "art", lookup, models, _meta("festival_selflag_d1d7_resid"))
    predictor = CrowdPredictor(out_dir)
    target = pd.Timestamp("2025-01-20")
    pred = predict_for_date(predictor, panel, target, history_days=7)
    assert (pred["date"] == target).all()
    assert len(pred) == 3 * 4
    assert pred["boarding_pred"].notna().all()


# ── 145 결측 마스킹 학습 ──


def _derived_deploy_frame(days=30, seed=0):
    """배포 세트 컬럼(`lag1d_`·`lag7d_`·`lagsd_` 포함)을 가진 파생 프레임과 그 lookup."""
    panel = _panel(days=days, seed=seed)
    lookup = DayTypeLookupBaseline().fit(panel)
    return lookup, add_derived_columns(panel, lookup, SEGMENTS)


def test_apply_masking_stack_keeps_original_and_masks_second_half_by_date():
    _, derived = _derived_deploy_frame()
    feature_cols = FEATURE_SETS[DEPLOY_SET]
    spec = MaskingSpec("stack", STACK_WEIGHTS, seed=7)
    out, summary = apply_masking(derived, feature_cols, spec)

    n_in = len(derived)
    assert len(out) == 2 * n_in
    pd.testing.assert_frame_equal(
        out.iloc[:n_in].reset_index(drop=True), derived.reset_index(drop=True)
    )

    # 두 번째 절반은 같은 seed로 다시 뽑은 날짜별 시나리오의 NaN 패턴과 일치해야 한다.
    rng = np.random.default_rng(spec.seed)
    date_scenarios = assign_date_scenarios(derived["date"], spec.weights, rng)
    second_half = out.iloc[n_in:].reset_index(drop=True)
    for date, scenario in date_scenarios.items():
        masked_cols = [
            c for c in lag_columns_for(scenario, feature_cols) if c in second_half.columns
        ]
        if not masked_cols:
            continue
        rows = second_half[second_half["date"] == date]
        assert rows[masked_cols].isna().all().all()

    assert summary["n_dates_by_scenario"]
    assert "full" not in summary["n_dates_by_scenario"]
    assert sum(summary["n_dates_by_scenario"].values()) == derived["date"].nunique()


def test_apply_masking_replace_keeps_full_dates_unchanged():
    _, derived = _derived_deploy_frame()
    feature_cols = FEATURE_SETS[DEPLOY_SET]
    spec = MaskingSpec("replace", REPLACE_WEIGHTS, seed=3)
    out, _ = apply_masking(derived, feature_cols, spec)
    assert len(out) == len(derived)

    rng = np.random.default_rng(spec.seed)
    date_scenarios = assign_date_scenarios(derived["date"], spec.weights, rng)
    full_dates = date_scenarios[date_scenarios == "full"].index
    original = derived.reset_index(drop=True)
    for date in full_dates:
        expect = original[original["date"] == date].reset_index(drop=True)
        got = out[out["date"] == date].reset_index(drop=True)
        pd.testing.assert_frame_equal(got, expect)


def test_masking_spec_stack_rejects_full_in_weights():
    with pytest.raises(ValueError):
        MaskingSpec("stack", {"full": 0.5, "no_lag": 0.5})


def test_train_models_without_masking_is_deterministic():
    panel = _panel()
    lookup, derived, _ = _fit(panel)
    X = build_matrix(derived, "festival_all_derived_resid")
    models_a = train_models(derived, lookup, "festival_all_derived_resid", SMALL_PARAMS)
    models_b = train_models(derived, lookup, "festival_all_derived_resid", SMALL_PARAMS)
    pred_a = models_a["boarding"]["__all__"].predict(X)
    pred_b = models_b["boarding"]["__all__"].predict(X)
    np.testing.assert_allclose(pred_a, pred_b)


def test_train_models_with_masking_fits_and_predicts_finite_including_no_lag():
    lookup, derived = _derived_deploy_frame()
    spec = MaskingSpec("stack", STACK_WEIGHTS, seed=1)
    models = train_models(derived, lookup, DEPLOY_SET, SMALL_PARAMS, masking=spec)

    X = build_matrix(derived, DEPLOY_SET)
    pred = models["boarding"]["__all__"].predict(X)
    assert np.isfinite(pred).all()

    lag_cols = [c for c in FEATURE_SETS[DEPLOY_SET] if c.startswith(("lag1d_", "lag7d_", "lagsd_"))]
    X_no_lag = X.copy()
    X_no_lag[lag_cols] = np.nan
    pred_no_lag = models["boarding"]["__all__"].predict(X_no_lag)
    assert np.isfinite(pred_no_lag).all()
