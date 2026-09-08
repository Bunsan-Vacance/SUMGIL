import pandas as pd
import pytest

from DATA_ENGINE.eda.analysis_crowd import (
    cluster_station_profiles,
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


def test_cluster_station_profiles_groups_by_shape_not_level():
    # 역A/역C는 오전 피크, 역B/역D는 오후 피크 — 절대 수준(역C·역D는 역A·역B의 2배)이 달라도
    # 패턴 모양이 같으면 같은 군집으로 묶여야 한다(행 단위 표준화 검증).
    profile = pd.DataFrame(
        {
            "06:00": [80.0, 20.0, 160.0, 40.0],
            "12:00": [40.0, 40.0, 80.0, 80.0],
            "18:00": [20.0, 80.0, 40.0, 160.0],
        },
        index=pd.Index(["역A", "역B", "역C", "역D"], name="station_name"),
    )

    result = cluster_station_profiles(profile, n_clusters=2)

    assert set(result.index) == {"역A", "역B", "역C", "역D"}
    assert result["역A"] == result["역C"]
    assert result["역B"] == result["역D"]
    assert result["역A"] != result["역B"]


def test_cluster_station_profiles_excludes_missing_and_constant_rows():
    profile = pd.DataFrame(
        {
            "06:00": [80.0, 20.0, None, 50.0],
            "18:00": [20.0, 80.0, 40.0, 50.0],
        },
        index=pd.Index(["역A", "역B", "역결측", "역균일"], name="station_name"),
    )

    result = cluster_station_profiles(profile, n_clusters=2)

    # 결측 행(역결측)과 표준편차 0인 행(역균일)은 군집 배정 없이 제외된다.
    assert set(result.index) == {"역A", "역B"}


def test_cluster_station_profiles_raises_when_too_few_complete_rows():
    profile = pd.DataFrame(
        {"06:00": [80.0, None], "18:00": [20.0, 40.0]},
        index=pd.Index(["역A", "역B"], name="station_name"),
    )

    with pytest.raises(ValueError, match="군집화할 수 없습니다"):
        cluster_station_profiles(profile, n_clusters=3)
