import pandas as pd
import pytest

from DATA_ENGINE.eda.build_congestion_calibration import (
    bucket_day_type,
    dedupe_snapshot_keys,
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


def _line9_snapshot_rows():
    """언주역 평일 08:00 — 연도 2020~2025 × 급행/일반이 전부 섞인 중복 키 상황."""
    rows = []
    for year in (2020, 2021, 2022, 2023, 2024, 2025):
        for train_type in ("일반", "급행"):
            rows.append(
                {
                    "line": "9호선",
                    "station_no": 4126,
                    "direction": "상선",
                    "day_type": "평일",
                    "time_slot": "08:00",
                    "year": year,
                    "train_type": train_type,
                    "congestion_pct": float(year - 2000),
                }
            )
    return pd.DataFrame(rows)


def test_dedupe_snapshot_keys_keeps_only_latest_year_and_local_train_for_line9():
    result = dedupe_snapshot_keys(_line9_snapshot_rows())

    assert len(result) == 1
    assert result.iloc[0]["year"] == 2025
    assert result.iloc[0]["train_type"] == "일반"


def test_dedupe_snapshot_keys_leaves_1_to_8_line_untouched():
    """1~8호선은 연도·급행 축이 없는 단일 대표 조사라 필터가 아무것도 안 걸러야 한다."""
    df = pd.DataFrame(
        {
            "line": ["1호선", "1호선"],
            "station_no": [150, 151],
            "direction": ["상선", "상선"],
            "day_type": ["평일", "평일"],
            "time_slot": ["08:00", "08:00"],
            "year": [None, None],
            "train_type": [None, None],
            "congestion_pct": [50.0, 60.0],
        }
    )

    result = dedupe_snapshot_keys(df)

    assert len(result) == 2
