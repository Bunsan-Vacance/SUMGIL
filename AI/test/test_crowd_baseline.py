import sys
from pathlib import Path

import numpy as np
import pandas as pd

# validation/CROWD/baseline-check/ 는 하이픈 때문에 패키지가 못 된다 — 경로로 가져온다.
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "validation" / "CROWD" / "baseline-check")
)

from baseline import DayTypeLookupBaseline, evaluate, regression_metrics, residuals
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
