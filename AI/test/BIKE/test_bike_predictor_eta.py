"""LightGBMEtaPredictor._build_feature_row()/predict_global_fallback() 단위 테스트.

실제 모델 파일(lightgbm)은 안 쓴다 — `ensure_loaded()`를 건너뛰고 필요한 내부 상태
(`_rack_count`/`_station_dtype`/`_profile`)를 직접 주입한다. `HistoricalProfileBuilder`는
순수 pandas라 무거운 의존성 가드가 필요 없다(`AI/CLAUDE.md`).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from app.BIKE.pipeline.features import HistoricalProfileBuilder
from app.BIKE.pipeline.predictor_eta import LightGBMEtaPredictor, UnknownStation

NOW = datetime(2026, 9, 14, 14, 0)  # noqa: DTZ001


def _fitted_profile() -> HistoricalProfileBuilder:
    train_df = pd.DataFrame(
        {
            "od_station_id": ["ST-1"],
            "day_of_week": [0],
            "hour": [14],
            "horizon_min": [15],
            "target_net_flow": [1.0],
            "target_rent_count": [2.0],
            "target_return_count": [1.0],
        }
    )
    return HistoricalProfileBuilder().fit(train_df)


def _predictor_with_state(rack_count: dict, categories: list[str]) -> LightGBMEtaPredictor:
    predictor = LightGBMEtaPredictor(Path("unused"), Path("unused"))
    predictor._loaded = True
    predictor._rack_count = pd.Series(rack_count)
    predictor._station_dtype = pd.CategoricalDtype(categories=categories)
    predictor._profile = _fitted_profile()
    return predictor


def test_build_feature_row_raises_unknown_station_when_rack_count_missing():
    predictor = _predictor_with_state(rack_count={"ST-1": 20}, categories=["ST-1"])

    with pytest.raises(UnknownStation):
        predictor._build_feature_row(
            "ST-99", current_stock=5, eta_minutes=10, now=NOW, anchor_age_minutes=1.0, weather=None
        )


def test_build_feature_row_raises_unknown_station_when_not_in_trained_categories():
    # rack_count는 있음(station_master가 학습 패널보다 넓은 범위를 커버) — 그런데 학습 시점
    # station_code 목록엔 없는 경우. 두 raise 지점이 서로 다른 조건임을 확인한다.
    predictor = _predictor_with_state(rack_count={"ST-1": 20, "ST-99": 15}, categories=["ST-1"])

    with pytest.raises(UnknownStation):
        predictor._build_feature_row(
            "ST-99", current_stock=5, eta_minutes=10, now=NOW, anchor_age_minutes=1.0, weather=None
        )


def test_build_feature_row_succeeds_for_known_station():
    predictor = _predictor_with_state(rack_count={"ST-1": 20}, categories=["ST-1"])

    frame, horizon_min = predictor._build_feature_row(
        "ST-1", current_stock=5, eta_minutes=10, now=NOW, anchor_age_minutes=1.0, weather=None
    )

    assert horizon_min == 10
    assert frame["station_code"].iloc[0] == 0


class _StubProfile:
    def __init__(self, global_df: pd.DataFrame) -> None:
        self.global_ = global_df


def _predictor_with_global_profile(global_df: pd.DataFrame) -> LightGBMEtaPredictor:
    predictor = LightGBMEtaPredictor(Path("unused"), Path("unused"))
    predictor._loaded = True
    predictor._profile = _StubProfile(global_df)
    return predictor


def test_predict_global_fallback_uses_horizon_matched_row():
    predictor = _predictor_with_global_profile(
        pd.DataFrame(
            {
                "horizon_min": [5, 10, 15, 30],
                "historical_net_flow_mean": [0.1, 0.2, 0.3, 0.4],
            }
        )
    )

    result = predictor.predict_global_fallback(eta_minutes=1440)

    assert result == {
        "net_flow": 0.4,
        "horizon_min_used": 30,
        "p_empty": None,
        "p_full": None,
    }


def test_predict_global_fallback_defaults_to_zero_when_horizon_missing():
    predictor = _predictor_with_global_profile(
        pd.DataFrame({"horizon_min": [], "historical_net_flow_mean": []})
    )

    result = predictor.predict_global_fallback(eta_minutes=10)

    assert result["net_flow"] == 0.0
    assert result["horizon_min_used"] == 10
