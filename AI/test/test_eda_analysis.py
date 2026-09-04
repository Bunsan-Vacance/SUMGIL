import pandas as pd
import pytest

from src.eda.analysis import _haversine_m, inventory_distribution, weekday_hour_heatmap


def _snapshots():
    return pd.DataFrame(
        {
            "stationId": ["ST-1", "ST-1", "ST-2", "ST-2"],
            "stationName": ["a", "a", "b", "b"],
            "rackTotCnt": [10, 10, 20, 20],
            "parkingBikeTotCnt": [0, 5, 2, 20],
            "shared": [0, 50, 10, 100],
            "stationLatitude": [37.50, 37.50, 37.51, 37.51],
            "stationLongitude": [127.00, 127.00, 127.01, 127.01],
            "collected_at": pd.to_datetime(
                ["2026-03-05 08:00", "2026-03-05 09:00", "2026-03-05 08:00", "2026-03-05 09:00"]
            ),
        }
    )


def test_inventory_distribution_depletion_rate():
    result = inventory_distribution(_snapshots())
    by_hour = result["by_hour"]
    # 08시엔 ST-1=0(고갈), ST-2=2(고갈) → 두 대여소 모두 N<=2
    assert by_hour.loc[8, "p_depleted"] == pytest.approx(1.0)
    assert by_hour.loc[8, "p_zero"] == pytest.approx(0.5)


def test_weekday_hour_heatmap_shape():
    pivot = weekday_hour_heatmap(_snapshots())
    assert set(pivot.columns) == {8, 9}


def test_haversine_zero_distance_for_same_point():
    assert _haversine_m(37.5, 127.0, 37.5, 127.0) == pytest.approx(0.0)


def test_haversine_known_distance_order_of_magnitude():
    # 위도 0.01도 차이는 대략 1.1km 안팎
    d = _haversine_m(37.50, 127.00, 37.51, 127.00)
    assert 900 < d < 1300
