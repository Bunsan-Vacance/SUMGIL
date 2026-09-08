import pandas as pd
import pytest

from DATA_ENGINE.eda.analysis_crowd import (
    day_type_direction_coverage,
    missing_cell_inventory,
    outlier_flags,
    year_over_year_snapshot_reference,
)
from DATA_ENGINE.eda.parsers_crowd import _normalize_time_slot


def test_normalize_time_slot_csv_and_xlsx_agree():
    csv_result = _normalize_time_slot(pd.Series(["6시00분"]), "seoul_1_8")
    xlsx_result = _normalize_time_slot(pd.Series(["06:00~06:29"]), "line9")
    assert csv_result.iloc[0] == "06:00"
    assert xlsx_result.iloc[0] == "06:00"


def test_missing_cell_inventory_flags_gap_without_filling():
    pivot = pd.DataFrame(
        {"06:00": [80.0, None], "06:30": [75.0, 60.0]},
        index=pd.Index(["역A", "역B"], name="station_name"),
    )
    pivot.columns.name = "time_slot"
    original = pivot.copy()

    result = missing_cell_inventory(pivot)

    assert len(result) == 1
    assert result.iloc[0]["station_name"] == "역B"
    assert result.iloc[0]["time_slot"] == "06:00"
    pd.testing.assert_frame_equal(pivot, original)  # 원본은 그대로 — 채우지 않는다


def test_outlier_flags_detects_zero_and_extreme():
    df = pd.DataFrame({"congestion_pct": [0.0, 55.0, 120.0, 180.0]})

    result = outlier_flags(df)

    assert set(result["flag_reason"]) == {"zero", "over_100", "very_high"}
    assert len(result) == 3  # 55.0(정상)은 플래그되지 않는다
    assert set(result["congestion_pct"]) == {0.0, 120.0, 180.0}


def test_year_over_year_reference_is_pct_change():
    df = pd.DataFrame(
        {
            "station_name": ["역A", "역A"],
            "day_type": ["평일", "평일"],
            "direction": ["상선", "상선"],
            "train_type": ["일반", "일반"],
            "time_slot": ["06:00", "06:00"],
            "year": [2024, 2025],
            "congestion_pct": [50.0, 75.0],
        }
    )

    result = year_over_year_snapshot_reference(df)

    assert result[2025].iloc[0] == pytest.approx(0.5)  # (75-50)/50, 절대차 아님
    assert result[2024].isna().all()


def test_day_type_direction_coverage_keeps_asymmetry():
    df = pd.DataFrame(
        {
            "source": ["seoul_1_8", "seoul_1_8", "line9"],
            "line": ["2호선", "1호선", "9호선"],
            "day_type": ["평일", "평일", "평일"],
            "direction": ["내선", "상선", "상선"],
        }
    )

    coverage = day_type_direction_coverage(df)
    direction_ct = coverage["direction"]

    assert direction_ct.loc[("seoul_1_8", "2호선"), "내선"] == 1
    assert direction_ct.loc[("seoul_1_8", "1호선"), "상선"] == 1
    assert direction_ct.loc[("line9", "9호선"), "상선"] == 1
    # 2호선(내선)이 1호선/9호선(상선)과 같은 칸으로 합쳐지지 않았는지 확인
    assert direction_ct.loc[("seoul_1_8", "1호선"), "내선"] == 0
