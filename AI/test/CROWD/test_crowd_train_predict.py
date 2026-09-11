"""app/CROWD/pipeline/{train,predict}.py — 학습→아티팩트→추론 round-trip.

lightgbm은 requirements-ci.txt에 없어 CI에서는 스킵된다(`AI/CLAUDE.md` 무거운 의존성 가드).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("lightgbm")

from app.CROWD.pipeline.features import SLOT_ORDER, add_derived_columns
from app.CROWD.pipeline.lookup import DayTypeLookupBaseline
from app.CROWD.pipeline.predict import CrowdPredictor, predict_for_date
from app.CROWD.pipeline.train import save_artifact, train_models

SEGMENTS = [{"line": "L1", "segment": "본선", "stations": [1, 2, 3]}]
SMALL_PARAMS = {"n_estimators": 20, "num_leaves": 7, "min_child_samples": 5}


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
