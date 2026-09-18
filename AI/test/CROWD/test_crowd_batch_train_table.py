"""239 — 배치가 만드는 열차·노드 표(`predictions_train_*.parquet`)의 순수 로직 검증.

실제 데이터 파일 없이 4역 1호선 합성 표로 `to_train_table`을 부른다(`test_crowd_batch_output.py`의
합성 데이터 형태를 재사용). 확인하는 것은 질량 보존(슬롯 재차인원 합 = 열차 배분 합), 열차 궤적
이어붙임(도착 재차 = 직전 역 출발 재차), 결측 전파(배율표 결측 셀은 열차로 나눠도 NaN), 운행 없는
슬롯은 결과에서 빠지고 `slots_without_trains`에 잡히는지, 30분 승하차가 열차 몫으로 다시 합쳐지는지,
그리고 `validated_meta`가 새 5개 키를 요구하는지다.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.CROWD.pipeline.batch_predict import (
    META_KEYS,
    TRAIN_OUTPUT_COLS,
    _congestion_table_full,
    to_train_table,
    validated_meta,
)

CAPACITY = {"car_capacity": 160, "cars_per_train": {"1호선": 10}}
STATIONS = [150, 151, 158, 159]
DATE = pd.Timestamp("2025-10-08")  # 수요일(평일)
TRAIN_CAPACITY = CAPACITY["car_capacity"] * CAPACITY["cars_per_train"]["1호선"]  # 1600


def _predicted() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": DATE,
            "station_no": STATIONS,
            "station_name": ["서울역", "시청", "청량리", "왕십리"],
            "line": "1호선",
            "time_slot": "08-09",
            "day_type": "평일",
            "boarding": [300.0, 100.0, 80.0, 40.0],
            "alighting": [0.0, 100.0, 30.0, 20.0],
            "boarding_pred": [300.0, 100.0, 80.0, 40.0],
            "alighting_pred": [0.0, 100.0, 30.0, 20.0],
            "boarding_lookup": [280.0, 110.0, 75.0, 35.0],
            "alighting_lookup": [5.0, 90.0, 28.0, 12.0],
        }
    )


def _calibration() -> pd.DataFrame:
    """159는 일부러 뺀다 — 배율표 결측(`no_calibration`) 케이스를 만들기 위해서다."""
    rows = []
    for s in STATIONS:
        if s == 159:
            continue
        for d in ("하선", "상선"):
            for t in ("08:00", "08:30"):
                rows.append(
                    {
                        "station_no": s,
                        "direction": d,
                        "day_type": "평일",
                        "time_slot": t,
                        "ratio": 0.25,
                    }
                )
    return pd.DataFrame(rows)


def _segments() -> list[dict]:
    return [{"line": "1호선", "segment": "본선", "stations": STATIONS}]


def _timetable() -> pd.DataFrame:
    """하선 열차 3대만 만든다(08:00 슬롯 2대, 08:30 슬롯 1대) — 상선은 시각표가 없어
    `slots_without_trains`(운행 없는 슬롯)을 만드는 데 쓴다. 모든 열차가 150→151→158→159
    순서로 4역을 다 지난다.
    """
    trains = {
        "T1": ["08:00", "08:03", "08:06", "08:09"],
        "T2": ["08:05", "08:08", "08:11", "08:14"],
        "T3": ["08:32", "08:35", "08:38", "08:41"],
    }
    rows = []
    for train_id, times in trains.items():
        for station, t in zip(STATIONS, times):
            rows.append(
                {
                    "station_no": station,
                    "line": "1호선",
                    "direction": "하선",
                    "day_type": "평일",
                    "train_id": train_id,
                    "arrival_time": t,
                    "express": False,
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture
def full() -> pd.DataFrame:
    return _congestion_table_full(
        _predicted(), _segments(), CAPACITY, _calibration(), [50.0, 100.0]
    )


@pytest.fixture
def train_result(full):
    return to_train_table(full, _timetable(), _segments(), _calibration(), [50.0, 100.0])


def test_columns_match_train_output_cols(train_result):
    train_tbl, _ = train_result
    assert list(train_tbl.columns) == TRAIN_OUTPUT_COLS


def test_mass_conservation_per_slot(full, train_result):
    """(station, direction=하선, slot)별 Σ onboard_dep_est == congestion_pct/100 × 정원 × n_trains."""
    train_tbl, stats = train_result
    assert stats["train_mass_gap"] < 1e-9

    n_trains_by_slot = {"08:00": 2, "08:30": 1}
    for station in (150, 151, 158):
        for slot, n_trains in n_trains_by_slot.items():
            cong = full.loc[
                (full["station_no"] == station)
                & (full["direction"] == "하선")
                & (full["time_slot_30min"] == slot),
                "congestion_pct",
            ].iloc[0]
            expected = cong / 100.0 * TRAIN_CAPACITY * n_trains
            actual = train_tbl.loc[
                (train_tbl["station_no"] == station)
                & (train_tbl["direction"] == "하선")
                & (train_tbl["time_slot_30min"] == slot),
                "onboard_dep_est",
            ].sum()
            assert actual == pytest.approx(expected, abs=1e-9)


def test_arrival_load_matches_previous_station_departure(train_result):
    """같은 열차의 다음 역 도착 재차(`onboard_arr_est`) = 직전 역 출발 재차(`onboard_dep_est`)."""
    train_tbl, _ = train_result
    t1 = train_tbl[(train_tbl["train_id"] == "T1") & (train_tbl["direction"] == "하선")]
    dep_150 = t1.loc[t1["station_no"] == 150, "onboard_dep_est"].iloc[0]
    arr_151 = t1.loc[t1["station_no"] == 151, "onboard_arr_est"].iloc[0]
    assert arr_151 == pytest.approx(dep_150)
    # 출발역이라 직전 역이 없다 — 도착 재차 0.
    assert t1.loc[t1["station_no"] == 150, "onboard_arr_est"].iloc[0] == 0.0


def test_missing_calibration_yields_nan_and_status(train_result):
    """159는 배율표 결측 — 재차·등급은 NaN, `data_status`는 슬롯 표를 그대로 상속한다."""
    train_tbl, _ = train_result
    rows = train_tbl[(train_tbl["station_no"] == 159) & (train_tbl["direction"] == "하선")]
    assert len(rows) > 0
    assert rows["load_dep_est"].isna().all()
    assert rows["grade_dep"].isna().all()
    assert (rows["data_status"] == "no_calibration").all()


def test_direction_without_timetable_is_absent_and_counted(train_result):
    """상선은 시각표가 없다 — 결과에 나오지 않고 `slots_without_trains`에 잡힌다."""
    train_tbl, stats = train_result
    assert (train_tbl["direction"] == "상선").sum() == 0
    # 150·151·158 × 상선 × (08:00, 08:30) = 6칸. 159는 배율표도 없어 애초에 값이 없다(중복 집계 아님).
    assert stats["slots_without_trains"] == 6


def test_boarding_train_est_sums_to_slot_boarding(train_result):
    """역별 30분 승차 추정(`boarding_train_est`)이 그 슬롯 열차 전체에서 30분 배분값으로 합쳐진다.

    1층 비중(`split_hourly_to_30min`)이 08-09시 안 두 30분에 50 : 50으로 나누고(배율표 ratio가
    양쪽 다 0.25로 같다), 상선 시각표가 없어 그 슬롯의 흐름 전부가 하선 열차로 몰린다
    (`allocate_flows_to_trains`의 방향 가중).
    """
    train_tbl, _ = train_result
    expected = {
        150: {"08:00": 150.0, "08:30": 150.0},
        151: {"08:00": 50.0, "08:30": 50.0},
        158: {"08:00": 40.0, "08:30": 40.0},
    }
    for station, slots in expected.items():
        for slot, exp_val in slots.items():
            actual = train_tbl.loc[
                (train_tbl["station_no"] == station) & (train_tbl["time_slot_30min"] == slot),
                "boarding_train_est",
            ].sum()
            assert actual == pytest.approx(exp_val)


def _full_meta() -> dict:
    return dict.fromkeys(META_KEYS)


def test_validated_meta_accepts_five_new_keys_and_rejects_missing_one():
    meta = _full_meta()
    assert validated_meta(meta) == meta  # 값이 전부 None이어도 키만 맞으면 통과한다

    missing = dict(meta)
    del missing["train_table"]
    with pytest.raises(RuntimeError):
        validated_meta(missing)


def test_no_negative_onboard_after_disaggregation(train_result):
    """분해 과정에서 값을 지어내지 않으므로 재차·승하차 추정은 결측 아니면 0 이상이어야 한다."""
    train_tbl, _ = train_result
    for col in ("onboard_arr_est", "onboard_dep_est", "boarding_train_est", "alighting_train_est"):
        values = train_tbl[col].dropna()
        assert (values >= -1e-9).all(), f"{col}에 음수가 있다"


# ── 239 후속: 강동류 접점(한 역이 세그먼트 여럿에 걸침) 링크 배정·질량 보존 ──
# 본선 [1,2,3] → 3에서 지선A [3,4,5]·지선B [3,6,7]로 갈라진다. T1은 지선A, T2는 지선B로
# 이어지고 T3는 본선에서 종착한다 — 강동(5호선 본선 종점·하남선/마천지선 분기)의 축소판이다.
JUNCTION_STATIONS = [1, 2, 3, 4, 5, 6, 7]
JUNCTION_DATE = pd.Timestamp("2025-10-08")  # 수요일(평일)
JUNCTION_CAPACITY = {"car_capacity": 160, "cars_per_train": {"5호선": 10}}
JUNCTION_TRAIN_CAPACITY = (
    JUNCTION_CAPACITY["car_capacity"] * JUNCTION_CAPACITY["cars_per_train"]["5호선"]
)  # 1600


def _junction_segments() -> list[dict]:
    return [
        {"line": "5호선", "segment": "본선", "stations": [1, 2, 3]},
        {"line": "5호선", "segment": "지선A", "stations": [3, 4, 5]},
        {"line": "5호선", "segment": "지선B", "stations": [3, 6, 7]},
    ]


def _junction_predicted() -> pd.DataFrame:
    n = len(JUNCTION_STATIONS)
    return pd.DataFrame(
        {
            "date": JUNCTION_DATE,
            "station_no": JUNCTION_STATIONS,
            "station_name": [f"역{s}" for s in JUNCTION_STATIONS],
            "line": "5호선",
            "time_slot": "08-09",
            "day_type": "평일",
            "boarding": [100.0] * n,
            "alighting": [0.0] * n,
            "boarding_pred": [100.0] * n,
            "alighting_pred": [0.0] * n,
            "boarding_lookup": [90.0] * n,
            "alighting_lookup": [5.0] * n,
        }
    )


def _junction_calibration() -> pd.DataFrame:
    """7역 모두 하선·상선 08:00/08:30에 배율 0.25 — 값 자체는 이 테스트의 관심사가 아니다."""
    rows = []
    for s in JUNCTION_STATIONS:
        for d in ("하선", "상선"):
            for t in ("08:00", "08:30"):
                rows.append(
                    {
                        "station_no": s,
                        "direction": d,
                        "day_type": "평일",
                        "time_slot": t,
                        "ratio": 0.25,
                    }
                )
    return pd.DataFrame(rows)


def _junction_timetable() -> pd.DataFrame:
    """T1(1→2→3→4→5)은 지선A로, T2(1→2→3→6→7)는 지선B로 이어지고 T3(1→2→3)는 본선 종착."""
    trains = {
        "T1": ([1, 2, 3, 4, 5], ["08:00", "08:03", "08:06", "08:09", "08:12"]),
        "T2": ([1, 2, 3, 6, 7], ["08:01", "08:04", "08:07", "08:10", "08:13"]),
        "T3": ([1, 2, 3], ["08:02", "08:05", "08:08"]),
    }
    rows = []
    for train_id, (stations, times) in trains.items():
        for station, t in zip(stations, times):
            rows.append(
                {
                    "station_no": station,
                    "line": "5호선",
                    "direction": "하선",
                    "day_type": "평일",
                    "train_id": train_id,
                    "arrival_time": t,
                    "express": False,
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture
def junction_full() -> pd.DataFrame:
    return _congestion_table_full(
        _junction_predicted(),
        _junction_segments(),
        JUNCTION_CAPACITY,
        _junction_calibration(),
        [50.0, 100.0],
    )


@pytest.fixture
def junction_result(junction_full):
    return to_train_table(
        junction_full,
        _junction_timetable(),
        _junction_segments(),
        _junction_calibration(),
        [50.0, 100.0],
    )


def test_junction_each_train_gets_exactly_one_link_row(junction_result):
    """station 3 하선에서 열차마다 정확히 한 행 — 링크를 정하기 전에 배분하던 옛 버그(135)라면
    세그먼트 수(3개)만큼 중복된 행이 남았을 것이다."""
    train_tbl, _ = junction_result
    at_3 = train_tbl[(train_tbl["station_no"] == 3) & (train_tbl["direction"] == "하선")]
    assert len(at_3) == 3
    assert at_3["train_id"].is_unique

    by_train = at_3.set_index("train_id")
    assert by_train.loc["T1", "segment"] == "지선A"
    assert by_train.loc["T2", "segment"] == "지선B"
    assert by_train.loc["T3", "segment"] == "본선"
    assert pd.isna(by_train.loc["T3", "to_station_no"])  # 본선 종착 — 다음 역 없음


def test_junction_link_ambiguous_false_and_no_dropped_trains(junction_result):
    train_tbl, stats = junction_result
    assert not train_tbl["link_ambiguous"].any()
    assert stats["trains_without_link"] == 0


def test_junction_mass_conserved_per_link(junction_full, junction_result):
    """station 3 하선의 링크별 onboard_dep_est가 그 링크 슬롯의 congestion_pct/100 × 정원 ×
    n_trains(그 링크만, 여기선 전부 1)와 같아야 한다 — 세그먼트를 섞어 배분하던 135 버그의 반증."""
    train_tbl, stats = junction_result
    assert stats["train_mass_gap"] < 1e-9

    cong = junction_full.set_index(["station_no", "direction", "segment", "time_slot_30min"])[
        "congestion_pct"
    ]
    at_3 = train_tbl[(train_tbl["station_no"] == 3) & (train_tbl["direction"] == "하선")].set_index(
        "train_id"
    )
    for train_id, segment in (("T1", "지선A"), ("T2", "지선B"), ("T3", "본선")):
        expected = (
            cong[(3, "하선", segment, "08:00")] / 100.0 * JUNCTION_TRAIN_CAPACITY * 1
        )  # n_trains=1
        actual = at_3.loc[train_id, "onboard_dep_est"]
        assert actual == pytest.approx(expected, abs=1e-9)


def test_no_train_table_rows_are_missing_data_status():
    """`data_status`는 슬롯 표에서 상속만 하므로 열차 표 어디에도 결측이 없어야 한다."""
    full_table = _congestion_table_full(
        _predicted(), _segments(), CAPACITY, _calibration(), [50.0, 100.0]
    )
    train_tbl, _ = to_train_table(
        full_table, _timetable(), _segments(), _calibration(), [50.0, 100.0]
    )
    assert train_tbl["data_status"].notna().all()
    assert train_tbl["pred_source"].notna().all()


def test_skipped_stop_within_segment_still_chains_arrival_load():
    """급행·정차 행 결측으로 역을 건너뛴 열차도 같은 세그먼트 안이면 도착 재차를 이어붙인다(239).

    T2의 151(시청) 정차 행을 지우면 150 → 158로 건너뛰는 궤적이 된다. 연속 인접만 허용하면
    158에서 `gap`(NaN)이 되지만, 실제 열차는 사람을 그대로 싣고 가므로 `prev_stop`으로 이어야 한다.
    """
    tt = _timetable()
    tt = tt[~((tt["train_id"] == "T2") & (tt["station_no"] == 151))].reset_index(drop=True)
    full_table = _congestion_table_full(
        _predicted(), _segments(), CAPACITY, _calibration(), [50.0, 100.0]
    )
    train_tbl, stats = to_train_table(full_table, tt, _segments(), _calibration(), [50.0, 100.0])
    t2 = train_tbl[train_tbl["train_id"] == "T2"].set_index("station_no")
    assert 151 not in t2.index
    assert t2.loc[158, "arr_source"] == "prev_stop"
    assert t2.loc[158, "prev_station_no"] == 150
    assert t2.loc[158, "load_arr_est"] == pytest.approx(t2.loc[150, "load_dep_est"])
    assert stats["trains_without_link"] == 0
