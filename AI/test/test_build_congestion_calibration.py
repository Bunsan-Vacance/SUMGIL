import pandas as pd
import pytest

from DATA_ENGINE.eda.build_congestion_calibration import (
    bucket_day_type,
    slot_30min_to_hour_bucket,
)


@pytest.mark.parametrize(
    ("slot", "expected"),
    [
        ("00:00", "24~"),
        ("00:30", "24~"),
        ("05:30", "~06"),
        ("06:00", "06-07"),
        ("06:30", "06-07"),
        ("23:00", "23-24"),
        ("23:30", "23-24"),
    ],
)
def test_slot_30min_to_hour_bucket(slot, expected):
    assert slot_30min_to_hour_bucket(slot) == expected


def test_slot_30min_to_hour_bucket_rejects_unknown_format():
    with pytest.raises(ValueError, match="알 수 없는"):
        slot_30min_to_hour_bucket("06시")


def test_bucket_day_type_keeps_1_to_8_line_weekday_saturday_sunday_unchanged():
    line = pd.Series(["1호선", "1호선", "1호선"])
    day_type = pd.Series(["평일", "토요일", "일요일"])

    result = bucket_day_type(line, day_type)

    assert list(result) == ["평일", "토요일", "일요일"]


def test_bucket_day_type_drops_1_to_8_line_holiday():
    """1~8호선 스냅샷엔 "휴일" 구분이 없어 대응이 안 된다 — 결측으로 둬 조인에서 빠지게 한다."""
    line = pd.Series(["1호선"])
    day_type = pd.Series(["휴일"])

    result = bucket_day_type(line, day_type)

    assert pd.isna(result.iloc[0])


def test_bucket_day_type_merges_line9_weekend_and_holiday_into_hyuil():
    """9호선 스냅샷은 주말+공휴일을 "휴일" 하나로 묶는다 — 그 정의를 그대로 따른다."""
    line = pd.Series(["9호선"] * 4)
    day_type = pd.Series(["평일", "토요일", "일요일", "휴일"])

    result = bucket_day_type(line, day_type)

    assert list(result) == ["평일", "휴일", "휴일", "휴일"]
