import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# validation/CROWD/baseline-check/ 는 하이픈 때문에 패키지가 못 된다 — 경로로 가져온다.
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "validation" / "CROWD" / "baseline-check")
)

from baseline import DayTypeLookupBaseline, evaluate, regression_metrics, residuals
from compare_models import add_improvement_columns
from dataset import time_split


def _frame(dates, station, slot, day_type, boarding, alighting):
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "station_no": station,
            "time_slot": slot,
            "day_type": day_type,
            "boarding": boarding,
            "alighting": alighting,
        }
    )


def test_time_split_cuts_on_date_not_randomly():
    panel = _frame(
        ["2024-06-01", "2024-12-31", "2025-01-01", "2025-06-01"],
        150,
        "08-09",
        "평일",
        [1, 2, 3, 4],
        [5, 6, 7, 8],
    )

    train, test = time_split(panel, pd.Timestamp("2025-01-01"))

    assert len(train) == 2
    assert len(test) == 2
    assert train["date"].max() < test["date"].min()


def test_baseline_predicts_the_training_mean():
    train = _frame(["2024-01-02", "2024-01-09"], 150, "08-09", "평일", [100, 200], [10, 30])
    test = _frame(["2025-01-07"], 150, "08-09", "평일", [999], [999])

    predicted = DayTypeLookupBaseline().fit(train).predict(test)

    assert predicted.loc[0, "boarding"] == 150.0
    assert predicted.loc[0, "alighting"] == 20.0


def test_baseline_leaves_unseen_combination_missing():
    """학습에 없던 조합을 전체 평균으로 채우면 성능이 실제보다 좋아 보인다 — 결측으로 둔다."""
    train = _frame(["2024-01-02"], 150, "08-09", "평일", [100], [10])
    test = _frame(["2025-01-04"], 150, "08-09", "토요일", [50], [5])

    predicted = DayTypeLookupBaseline().fit(train).predict(test)

    assert pd.isna(predicted.loc[0, "boarding"])


def test_evaluate_counts_lookup_failures():
    train = _frame(["2024-01-02"], 150, "08-09", "평일", [100], [10])
    test = pd.concat(
        [
            _frame(["2025-01-07"], 150, "08-09", "평일", [120], [14]),
            _frame(["2025-01-04"], 150, "08-09", "토요일", [50], [5]),
        ],
        ignore_index=True,
    )

    metrics, missing = evaluate(DayTypeLookupBaseline().fit(train), test)

    assert missing == 1
    assert metrics.loc[metrics["target"] == "boarding", "n"].item() == 1


def test_regression_metrics_matches_hand_computation():
    actual = pd.Series([10.0, 20.0, 30.0])
    predicted = pd.Series([12.0, 18.0, 33.0])

    m = regression_metrics(actual, predicted)

    assert np.isclose(m["mae"], (2 + 2 + 3) / 3)
    assert np.isclose(m["rmse"], np.sqrt((4 + 4 + 9) / 3))
    assert m["n"] == 3


def test_regression_metrics_skips_zero_actuals_for_mape():
    """실측 0인 행에서 MAPE가 발산하므로 제외하고, 몇 건 썼는지 알려준다."""
    actual = pd.Series([0.0, 100.0])
    predicted = pd.Series([5.0, 90.0])

    m = regression_metrics(actual, predicted)

    assert m["n"] == 2
    assert m["mape_n"] == 1
    assert np.isclose(m["mape"], 10.0)


def test_regression_metrics_handles_all_missing():
    m = regression_metrics(pd.Series([np.nan]), pd.Series([np.nan]))

    assert m["n"] == 0
    assert np.isnan(m["rmse"])


def test_residuals_are_actual_minus_prediction():
    train = _frame(["2024-01-02"], 150, "08-09", "평일", [100], [10])
    test = _frame(["2025-01-07"], 150, "08-09", "평일", [130], [25])

    resid = residuals(DayTypeLookupBaseline().fit(train), test)

    assert resid.loc[0, "boarding_resid"] == 30.0
    assert resid.loc[0, "alighting_resid"] == 15.0


def test_regression_metrics_r2_is_one_for_perfect_prediction():
    actual = pd.Series([100.0, 200.0, 300.0])

    assert regression_metrics(actual, actual.copy())["r2"] == 1.0


def test_regression_metrics_r2_is_zero_when_predicting_the_mean():
    """평균만 내놓는 예측의 R²는 0 — 이게 R²의 기준점이다."""
    actual = pd.Series([100.0, 200.0, 300.0])
    predicted = pd.Series([200.0, 200.0, 200.0])

    assert regression_metrics(actual, predicted)["r2"] == pytest.approx(0.0)


def test_regression_metrics_r2_is_negative_when_worse_than_the_mean():
    actual = pd.Series([100.0, 200.0, 300.0])
    predicted = pd.Series([300.0, 200.0, 100.0])

    assert regression_metrics(actual, predicted)["r2"] < 0


def test_regression_metrics_r2_is_nan_for_constant_actuals():
    """실측이 전부 같으면 분모가 0이라 R²가 정의되지 않는다 — 0(설명력 없음)이 아니다."""
    actual = pd.Series([50.0, 50.0, 50.0])
    predicted = pd.Series([50.0, 51.0, 49.0])

    assert np.isnan(regression_metrics(actual, predicted)["r2"])


def _comparison_frame():
    """lookup_baseline보다 rmse·mae가 낮고 r2가 높은 후보 하나."""
    return pd.DataFrame(
        [
            {
                "model": "lookup_baseline",
                "target": "boarding",
                "rmse": 200.0,
                "mae": 100.0,
                "r2": 0.90,
            },
            {"model": "lightgbm", "target": "boarding", "rmse": 190.0, "mae": 95.0, "r2": 0.92},
        ]
    )


def test_add_improvement_columns_reports_relative_and_absolute_gain():
    result = add_improvement_columns(_comparison_frame()).set_index("model")

    assert result.loc["lightgbm", "RMSE_개선율_%"] == 5.0
    assert result.loc["lightgbm", "MAE_개선율_%"] == 5.0
    assert result.loc["lightgbm", "RMSE_개선_명"] == 10.0
    assert result.loc["lightgbm", "MAE_개선_명"] == 5.0


def test_add_improvement_columns_uses_percentage_points_for_r2():
    """R²는 높을수록 좋으므로 비율이 아니라 차이(%p)로 낸다."""
    result = add_improvement_columns(_comparison_frame()).set_index("model")

    assert result.loc["lightgbm", "R2_개선_%p"] == pytest.approx(2.0)


def test_add_improvement_columns_leaves_baseline_at_zero():
    """베이스라인 자신의 개선폭은 모든 지표에서 0이어야 한다."""
    result = add_improvement_columns(_comparison_frame()).set_index("model")

    for col in ("RMSE_개선율_%", "MAE_개선율_%", "R2_개선_%p", "RMSE_개선_명", "MAE_개선_명"):
        assert result.loc["lookup_baseline", col] == 0


def test_add_improvement_columns_reports_negative_gain_for_worse_model():
    frame = _comparison_frame()
    frame.loc[1, ["rmse", "mae", "r2"]] = [220.0, 110.0, 0.88]

    result = add_improvement_columns(frame).set_index("model")

    assert result.loc["lightgbm", "RMSE_개선율_%"] == -10.0
    assert result.loc["lightgbm", "RMSE_개선_명"] == -20.0
    assert result.loc["lightgbm", "R2_개선_%p"] == pytest.approx(-2.0)
