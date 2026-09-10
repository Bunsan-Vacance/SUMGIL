import pandas as pd
import pytest

from DATA_ENGINE.eda.build_congestion_label_calibrated import (
    explode_to_30min,
    hour_bucket_to_30min_slots,
    verify_calibration_identity,
)


@pytest.mark.parametrize(
    ("hour_bucket", "expected"),
    [
        ("24~", ["00:00", "00:30"]),
        ("~06", ["05:30"]),
        ("06-07", ["06:00", "06:30"]),
        ("23-24", ["23:00", "23:30"]),
    ],
)
def test_hour_bucket_to_30min_slots(hour_bucket, expected):
    assert hour_bucket_to_30min_slots(hour_bucket) == expected


def test_explode_to_30min_duplicates_the_hourly_value_for_each_half_hour():
    """1시간 값을 30분 두 개로 복제한다 — 값 자체는 아직 안 바뀐다(배율 곱하기 전)."""
    labels = pd.DataFrame({"time_slot": ["06-07"], "congestion_raw_pct": [80.0]})

    result = explode_to_30min(labels)

    assert list(result["time_slot_30min"]) == ["06:00", "06:30"]
    assert list(result["congestion_raw_pct"]) == [80.0, 80.0]


def test_explode_to_30min_tilde_06_produces_a_single_row():
    labels = pd.DataFrame({"time_slot": ["~06"], "congestion_raw_pct": [10.0]})

    result = explode_to_30min(labels)

    assert len(result) == 1
    assert result.iloc[0]["time_slot_30min"] == "05:30"


def test_verify_calibration_identity_passes_when_ratio_definition_holds():
    """배율이 실측÷raw평균으로 정의됐다면, raw×배율의 평균은 정의상 실측과 같아야 한다."""
    key = {
        "station_no": 4126,
        "direction": "상선",
        "day_type_bucket": "평일",
        "time_slot_30min": "08:00",
    }
    # raw 두 날짜(10, 30 — 평균 20)에 배율 2.0을 곱하면 20, 60 — 평균 40이 스냅샷과 같아야 한다.
    calibrated = pd.DataFrame(
        [
            {**key, "congestion_pct_calibrated": 20.0},
            {**key, "congestion_pct_calibrated": 60.0},
        ]
    )
    calibration = pd.DataFrame(
        [
            {
                "station_no": 4126,
                "direction": "상선",
                "day_type": "평일",
                "time_slot": "08:00",
                "congestion_pct": 40.0,
            }
        ]
    )

    assert verify_calibration_identity(calibrated, calibration).empty


def test_verify_calibration_identity_flags_a_real_mismatch():
    key = {
        "station_no": 4126,
        "direction": "상선",
        "day_type_bucket": "평일",
        "time_slot_30min": "08:00",
    }
    calibrated = pd.DataFrame([{**key, "congestion_pct_calibrated": 20.0}])
    calibration = pd.DataFrame(
        [
            {
                "station_no": 4126,
                "direction": "상선",
                "day_type": "평일",
                "time_slot": "08:00",
                "congestion_pct": 99.0,
            }
        ]
    )

    result = verify_calibration_identity(calibrated, calibration)

    assert len(result) == 1
