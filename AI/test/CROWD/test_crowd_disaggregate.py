"""app/CROWD/pipeline/disaggregate.py — 1시간→30분→열차 분해의 질량 보존과 경계 처리."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.CROWD.pipeline.disaggregate import (
    allocate_flows_to_trains,
    allocate_to_trains,
    arrival_mix_weight,
    half_hour_shares,
    node_states,
    platform_accumulation,
    slot30_start_minutes,
    slots_in_order,
    split_hourly_to_30min,
    train_trajectory,
)


def _calibration():
    # 강남(222) 평일 08시: 내선은 전반 60%, 외선은 전반 40% → 방향 평균 50/50
    rows = []
    for direction, a, b in (("내선", 0.6, 0.4), ("외선", 0.4, 0.6)):
        rows += [
            {
                "station_no": 222,
                "direction": direction,
                "day_type": "평일",
                "time_slot": "08:00",
                "ratio": a,
            },
            {
                "station_no": 222,
                "direction": direction,
                "day_type": "평일",
                "time_slot": "08:30",
                "ratio": b,
            },
        ]
    # 07시는 내선만 있고 70/30
    rows += [
        {
            "station_no": 222,
            "direction": "내선",
            "day_type": "평일",
            "time_slot": "07:00",
            "ratio": 0.35,
        },
        {
            "station_no": 222,
            "direction": "내선",
            "day_type": "평일",
            "time_slot": "07:30",
            "ratio": 0.15,
        },
        # ~06 은 05:30 하나
        {
            "station_no": 222,
            "direction": "내선",
            "day_type": "평일",
            "time_slot": "05:30",
            "ratio": 0.2,
        },
    ]
    return pd.DataFrame(rows)


def test_half_hour_shares_average_directions_and_sum_to_one():
    sh = half_hour_shares(_calibration()).set_index(["time_slot", "time_slot_30min"])["share"]
    assert sh[("08-09", "08:00")] == pytest.approx(0.5)
    assert sh[("07-08", "07:00")] == pytest.approx(0.7)
    assert sh[("07-08", "07:30")] == pytest.approx(0.3)
    assert sh[("~06", "05:30")] == pytest.approx(1.0)


def test_split_conserves_mass_and_leaves_missing_nan():
    panel = pd.DataFrame(
        {
            "date": pd.Timestamp("2025-03-03"),
            "station_no": [222, 222, 222],
            "day_type": "평일",
            "time_slot": ["07-08", "08-09", "10-11"],  # 10-11 은 배율표에 없다
            "boarding": [1000.0, 2000.0, 500.0],
            "alighting": [100.0, 200.0, 50.0],
        }
    )
    out = split_hourly_to_30min(panel, _calibration())
    assert len(out) == 6
    by_hour = out.groupby("time_slot")["boarding_30min_est"].sum()
    assert by_hour["07-08"] == pytest.approx(1000.0)
    assert by_hour["08-09"] == pytest.approx(2000.0)
    assert out.loc[out["time_slot"] == "10-11", "boarding_30min_est"].isna().all()
    first = out[(out["time_slot"] == "07-08") & (out["time_slot_30min"] == "07:00")]
    assert first["boarding_30min_est"].iloc[0] == pytest.approx(700.0)


def _timetable():
    # 08:00~08:29 슬롯: 08:02, 08:08, 08:14(6분 간격) / 08:30 슬롯: 08:44 (14분 → long)
    return pd.DataFrame(
        {
            "station_no": 222,
            "direction": "내선",
            "day_type": "평일",
            "train_id": ["T1", "T2", "T3", "T4", "T5"],
            "arrival_time": ["07:56", "08:02", "08:08", "08:14", "08:44"],
        }
    )


def test_allocate_shares_by_headway_and_conserves_slot_mass():
    loads = pd.DataFrame(
        {
            "date": pd.Timestamp("2025-03-03"),
            "station_no": 222,
            "direction": "내선",
            "day_type": "평일",
            "time_slot_30min": ["08:00", "08:30"],
            "onboard_30min_est": [1800.0, 900.0],
        }
    )
    out = allocate_to_trains(loads, _timetable())
    s1 = out[out["time_slot_30min"] == "08:00"]
    assert list(s1["train_id"]) == ["T2", "T3", "T4"]
    assert s1["load_est"].sum() == pytest.approx(1800.0)
    assert np.allclose(s1["share"], 1 / 3)  # 6분씩 균등
    assert not s1["headway_long"].any()
    s2 = out[out["time_slot_30min"] == "08:30"]
    assert list(s2["train_id"]) == ["T5"]
    assert s2["load_est"].iloc[0] == pytest.approx(900.0)
    assert s2["headway_long"].iloc[0]  # 30분 간격


def test_slot_without_trains_is_dropped_not_filled():
    loads = pd.DataFrame(
        {
            "date": pd.Timestamp("2025-03-03"),
            "station_no": 222,
            "direction": "내선",
            "day_type": "평일",
            "time_slot_30min": ["09:00"],
            "onboard_30min_est": [100.0],
        }
    )
    assert allocate_to_trains(loads, _timetable()).empty


def test_after_midnight_slots_fold_to_end_of_service_day():
    assert slot30_start_minutes("00:30") == 24 * 60 + 30
    assert slots_in_order()[0] == "05:30" and slots_in_order()[-1] == "00:30"
    assert len(slots_in_order()) == 39


# ── 92: 배차 의존 도착 혼합 ──
def test_arrival_mix_weight_is_piecewise_linear():
    w = arrival_mix_weight([3, 5, 10, 15, 20], h0=5, h1=15)
    assert np.allclose(w, [1.0, 1.0, 0.5, 0.0, 0.0])
    with pytest.raises(ValueError):
        arrival_mix_weight(5, h0=10, h1=10)


def _loads_one_slot(total=1200.0):
    return pd.DataFrame(
        {
            "date": pd.Timestamp("2025-03-03"),
            "station_no": 222,
            "direction": "내선",
            "day_type": "평일",
            "time_slot_30min": ["08:00"],
            "onboard_30min_est": [total],
        }
    )


def _timetable_uneven():
    # 08:00 슬롯에 열차 둘: 간격 5분(08:05)과 25분(08:29 → 실제 간격 24분)
    return pd.DataFrame(
        {
            "station_no": 222,
            "direction": "내선",
            "day_type": "평일",
            "train_id": ["A", "B", "C"],
            "arrival_time": ["08:00", "08:05", "08:29"],
        }
    )


def test_mix_none_keeps_headway_proportional_and_no_mix_column():
    out = allocate_to_trains(_loads_one_slot(), _timetable_uneven())
    assert "mix_w" not in out.columns
    # A는 첫차(간격 30 기본) — 슬롯 08:00에 A(30)·B(5)·C(24)
    assert out["load_est"].sum() == pytest.approx(1200.0)
    assert np.allclose(out.set_index("train_id")["share"][["B", "C"]], [5 / 59, 24 / 59])


def test_mix_moves_long_headway_trains_toward_equal_split_and_conserves_mass():
    out = allocate_to_trains(_loads_one_slot(), _timetable_uneven(), mix_h0=5, mix_h1=15)
    assert out["load_est"].sum() == pytest.approx(1200.0)
    s = out.set_index("train_id")
    # B(5분)는 가중 1 → 간격 비례 5/59, A(첫차, 기본 30분)·C(24분)는 가중 0 → 균등 1/3.
    # 재정규화 후 간격이 가장 길던 A의 몫은 줄고(30/59 → C와 같음) B의 몫은 커진다.
    assert s.loc["B", "mix_w"] == pytest.approx(1.0)
    assert s.loc["C", "mix_w"] == pytest.approx(0.0)
    assert s.loc["B", "share"] > 5 / 59
    assert s.loc["A", "share"] < 30 / 59
    assert s.loc["A", "share"] == pytest.approx(s.loc["C", "share"])
    assert s["share"].sum() == pytest.approx(1.0)
    assert s.loc["C", "headway_long"] and not s.loc["B", "headway_long"]


def test_mix_with_short_headways_equals_proportional():
    loads = pd.DataFrame(
        {
            "date": pd.Timestamp("2025-03-03"),
            "station_no": 222,
            "direction": "내선",
            "day_type": "평일",
            "time_slot_30min": ["08:00"],
            "onboard_30min_est": [1800.0],
        }
    )
    base = allocate_to_trains(loads, _timetable())
    mixed = allocate_to_trains(loads, _timetable(), mix_h0=5, mix_h1=15)
    assert np.allclose(base["share"], mixed["share"])  # 6분 간격 → w≈0.9지만 균등이라 몫 동일


# ── 239: allocate_to_trains extra_key(링크별 배분 분리) ──
def _timetable_with_links():
    # 한 역·방향·슬롯(08:00)에 링크 둘: 본선 열차 둘(A1·A2), 지선 열차 하나(B1). 도착 순서는
    # A1(08:02) → B1(08:05) → A2(08:08)로 섞여 있다 — 배차 간격은 링크와 무관하게 이 순서로 잰다.
    return pd.DataFrame(
        {
            "station_no": 2549,
            "direction": "하선",
            "day_type": "평일",
            "train_id": ["A1", "A2", "B1"],
            "arrival_time": ["08:02", "08:08", "08:05"],
            "link_id": ["본선", "본선", "지선"],
        }
    )


def _loads_two_links():
    return pd.DataFrame(
        {
            "date": pd.Timestamp("2025-03-03"),
            "station_no": 2549,
            "direction": "하선",
            "day_type": "평일",
            "link_id": ["본선", "지선"],
            "time_slot_30min": "08:00",
            "onboard_30min_est": [1200.0, 300.0],
        }
    )


def test_allocate_to_trains_extra_key_separates_links():
    out = allocate_to_trains(_loads_two_links(), _timetable_with_links(), extra_key=("link_id",))
    main = out[out["link_id"] == "본선"]
    branch = out[out["link_id"] == "지선"]
    assert list(main["train_id"]) == ["A1", "A2"]
    assert main["load_est"].sum() == pytest.approx(1200.0)
    assert list(branch["train_id"]) == ["B1"]
    # 링크로 안 나뉘면 B1이 A1·A2와 섞여 몫이 300보다 작아진다(135 강동 버그).
    assert branch["load_est"].iloc[0] == pytest.approx(300.0)


def test_allocate_to_trains_extra_key_missing_column_raises():
    timetable = _timetable_with_links().drop(columns=["link_id"])
    with pytest.raises(ValueError):
        allocate_to_trains(_loads_two_links(), timetable, extra_key=("link_id",))


# ── 239: train_trajectory(열차 궤적 — 런·직전/다음 역) ──
def test_train_trajectory_runs_and_neighbors():
    rows = pd.DataFrame(
        {
            "line": "2호선",
            "day_type": "평일",
            "train_id": "T1",
            "station_no": [201, 202, 301, 302],
            "arrival_time": ["08:00", "08:05", "09:10", "09:15"],  # 08:05→09:10 = 65분(> 20분 기본)
            "express": [False, False, True, True],  # 보존되는 추가 컬럼 확인용
        }
    )
    out = train_trajectory(rows)
    assert "arr_min" not in out.columns
    assert "express" in out.columns
    assert list(out["run_id"]) == [0, 0, 1, 1]

    r0 = out[out["run_id"] == 0].reset_index(drop=True)
    assert pd.isna(r0.loc[0, "prev_station_no"])
    assert r0.loc[0, "next_station_no"] == 202
    assert r0.loc[1, "prev_station_no"] == 201
    assert pd.isna(r0.loc[1, "next_station_no"])

    r1 = out[out["run_id"] == 1].reset_index(drop=True)
    assert pd.isna(r1.loc[0, "prev_station_no"])  # 새 런의 첫 행 — 직전 역 없음
    assert r1.loc[0, "next_station_no"] == 302
    assert r1.loc[1, "prev_station_no"] == 301
    assert pd.isna(r1.loc[1, "next_station_no"])


# ── 239: 3층 — 열차 → 노드 상태 ──
def _linear_train_rows(load_ests=(500.0, 600.0, 550.0)):
    # 선형 3역(201→202→203)을 지나는 열차 한 대. B의 onboard_arr_est는 A의 load_est와 같아야 한다.
    return pd.DataFrame(
        {
            "line": "2호선",
            "day_type": "평일",
            "station_no": [201, 202, 203],
            "direction": "외선",
            "train_id": "T1",
            "arrival_time": ["08:00", "08:05", "08:10"],
            "time_slot_30min": "08:00",
            "load_est": list(load_ests),
            "train_capacity": 1000.0,
        }
    )


def test_node_states_linear_trajectory_links_prev_and_next():
    out = node_states(_linear_train_rows())
    a, b, c = out.iloc[0], out.iloc[1], out.iloc[2]
    assert pd.isna(a["prev_station_no"])
    assert a["onboard_arr_est"] == pytest.approx(0.0)
    assert a["arr_source"] == "origin"
    assert b["onboard_arr_est"] == pytest.approx(500.0)  # A의 load_est
    assert b["arr_source"] == "prev_stop"
    assert pd.isna(c["next_station_no"])
    assert c["onboard_arr_est"] == pytest.approx(600.0)  # B의 load_est
    assert a["load_dep_est"] == pytest.approx(50.0)  # 500/1000*100
    assert b["load_dep_est"] == pytest.approx(60.0)
    assert b["load_arr_est"] == pytest.approx(50.0)  # onboard_arr_est(500)/1000*100
    assert c["load_arr_est"] == pytest.approx(60.0)


def test_node_states_run_split_on_large_gap():
    rows = pd.DataFrame(
        {
            "line": "2호선",
            "day_type": "평일",
            "station_no": [201, 202, 301, 302],
            "direction": "외선",
            "train_id": "T1",
            "arrival_time": ["08:00", "08:05", "09:10", "09:15"],  # 08:05→09:10 = 65분(> 20분)
            "time_slot_30min": ["08:00", "08:00", "09:00", "09:00"],
            "load_est": [500.0, 600.0, 300.0, 350.0],
            "train_capacity": 1000.0,
        }
    )
    out = node_states(rows, max_gap_min=20.0)
    assert list(out["run_id"]) == [0, 0, 1, 1]
    run1_first = out[(out["run_id"] == 1) & (out["station_no"] == 301)].iloc[0]
    assert run1_first["onboard_arr_est"] == pytest.approx(0.0)
    assert run1_first["arr_source"] == "origin"
    assert pd.isna(run1_first["prev_station_no"])


def test_node_states_adjacency_gap_sets_nan_and_gap_source():
    adjacency = {(201, 202)}  # (202, 203)은 없다
    out = node_states(_linear_train_rows(), adjacency=adjacency)
    b = out[out["station_no"] == 202].iloc[0]
    c = out[out["station_no"] == 203].iloc[0]
    assert b["onboard_arr_est"] == pytest.approx(500.0)
    assert b["arr_source"] == "prev_stop"
    assert pd.isna(c["onboard_arr_est"])
    assert c["arr_source"] == "gap"


def test_node_states_circular_trajectory_keeps_repeated_station():
    # 2호선류 순환: 같은 열차가 한 런 안에서 201을 두 번 지난다(서로 다른 시각).
    rows = pd.DataFrame(
        {
            "line": "2호선",
            "day_type": "평일",
            "station_no": [201, 202, 201],
            "direction": "외선",
            "train_id": "T1",
            "arrival_time": ["08:00", "08:05", "08:10"],
            "time_slot_30min": "08:00",
            "load_est": [500.0, 600.0, 550.0],
            "train_capacity": 1000.0,
        }
    )
    out = node_states(rows)
    assert len(out) == 3  # 겹치는 역이라도 접히지 않는다
    assert list(out["run_id"]) == [0, 0, 0]
    assert pd.isna(out.iloc[0]["prev_station_no"])
    assert out.iloc[0]["next_station_no"] == 202
    assert out.iloc[1]["prev_station_no"] == 201
    assert out.iloc[1]["next_station_no"] == 201
    assert out.iloc[2]["prev_station_no"] == 202
    assert pd.isna(out.iloc[2]["next_station_no"])


def test_node_states_nan_load_propagates_not_zero():
    out = node_states(_linear_train_rows(load_ests=(np.nan, 600.0, 550.0)))
    b = out[out["station_no"] == 202].iloc[0]
    assert pd.isna(b["onboard_arr_est"])  # 0이 아니라 NaN 그대로
    assert b["arr_source"] == "prev_stop"


LINK_SEGMENTS_GANGDONG = {
    "본선": [2547, 2548, 2549],
    "하남선": [2549, 2550, 2551],
    "마천선": [2549, 2560, 2561],
}


def _train_rows_gangdong_continuing():
    # 본선을 타고 오다 하남선으로 이어가는 열차: 2549가 세 세그먼트에 겹쳐 중복 행이 생긴다.
    # 최댓값(마천선 900)은 실제로 안 이어지는 세그먼트라, link_segments 없이는 오답을 고른다.
    rows = [
        {"station_no": 2548, "arrival_time": "08:00", "segment": "본선", "load_est": 800.0},
        {"station_no": 2549, "arrival_time": "08:03", "segment": "본선", "load_est": 750.0},
        {"station_no": 2549, "arrival_time": "08:03", "segment": "하남선", "load_est": 770.0},
        {"station_no": 2549, "arrival_time": "08:03", "segment": "마천선", "load_est": 900.0},
        {"station_no": 2550, "arrival_time": "08:06", "segment": "하남선", "load_est": 760.0},
    ]
    df = pd.DataFrame(rows)
    df["line"] = "5호선"
    df["day_type"] = "평일"
    df["direction"] = "하남방면"
    df["train_id"] = "H1"
    df["time_slot_30min"] = "08:00"
    df["train_capacity"] = 1000.0
    return df


def _train_rows_gangdong_terminating():
    # 강동(2549)에서 종착하는 본선 열차. 본선 몫(50)이 가장 작아도 그 행이 정답이어야 한다.
    rows = [
        {"station_no": 2548, "arrival_time": "08:10", "segment": "본선", "load_est": 800.0},
        {"station_no": 2549, "arrival_time": "08:13", "segment": "본선", "load_est": 50.0},
        {"station_no": 2549, "arrival_time": "08:13", "segment": "하남선", "load_est": 900.0},
        {"station_no": 2549, "arrival_time": "08:13", "segment": "마천선", "load_est": 910.0},
    ]
    df = pd.DataFrame(rows)
    df["line"] = "5호선"
    df["day_type"] = "평일"
    df["direction"] = "본선종착"
    df["train_id"] = "H2"
    df["time_slot_30min"] = "08:00"
    df["train_capacity"] = 1000.0
    return df


def test_node_states_gangdong_duplicate_links_resolved_by_topology():
    df = pd.concat(
        [_train_rows_gangdong_continuing(), _train_rows_gangdong_terminating()],
        ignore_index=True,
    )
    out = node_states(df, link_segments=LINK_SEGMENTS_GANGDONG)
    row_h1 = out[(out["train_id"] == "H1") & (out["station_no"] == 2549)].iloc[0]
    assert row_h1["load_est"] == pytest.approx(770.0)  # 하남선으로 이어지는 행
    assert not row_h1["link_ambiguous"]
    row_h2 = out[(out["train_id"] == "H2") & (out["station_no"] == 2549)].iloc[0]
    assert row_h2["load_est"] == pytest.approx(50.0)  # 본선 종점 행(최댓값이 아닌데도 선택)
    assert not row_h2["link_ambiguous"]


def test_node_states_gangdong_duplicate_links_fallback_to_max_load_without_segments():
    out = node_states(_train_rows_gangdong_continuing())  # link_segments 없음
    row = out[out["station_no"] == 2549].iloc[0]
    assert row["load_est"] == pytest.approx(900.0)  # 셋 중 최댓값(마천선, 135 규칙)
    assert row["link_ambiguous"]


# ── 239: allocate_flows_to_trains ──
def _node_rows_two_directions():
    return pd.DataFrame(
        {
            "date": pd.Timestamp("2025-03-03"),
            "station_no": 222,
            "time_slot_30min": "08:00",
            "direction": ["내선", "내선", "외선", "외선"],
            "train_id": ["T1", "T2", "T3", "T4"],
            "share": [0.4, 0.6, 0.5, 0.5],
            "onboard_dep_est": [100.0, 300.0, 100.0, 100.0],
            "onboard_arr_est": [50.0, 150.0, 300.0, 100.0],
        }
    )


def _slot_flows_single(boarding=1000.0, alighting=800.0, station_no=222):
    return pd.DataFrame(
        {
            "date": [pd.Timestamp("2025-03-03")],
            "station_no": [station_no],
            "time_slot_30min": ["08:00"],
            "boarding_30min_est": [boarding],
            "alighting_30min_est": [alighting],
        }
    )


def test_allocate_flows_share_rule_conserves_mass_and_follows_departing_load():
    out = allocate_flows_to_trains(_slot_flows_single(), _node_rows_two_directions())
    assert out["boarding_train_est"].sum() == pytest.approx(1000.0)
    assert out["alighting_train_est"].sum() == pytest.approx(800.0)
    by_dir = out.groupby("direction")["boarding_train_est"].sum()
    assert by_dir["내선"] == pytest.approx(1000.0 * 400 / 600)
    assert by_dir["외선"] == pytest.approx(1000.0 * 200 / 600)
    assert (out["flow_rule"] == "share").all()


def test_allocate_flows_load_rule_alighting_follows_arriving_load():
    out = allocate_flows_to_trains(_slot_flows_single(), _node_rows_two_directions(), rule="load")
    assert out["boarding_train_est"].sum() == pytest.approx(1000.0)
    assert out["alighting_train_est"].sum() == pytest.approx(800.0)
    row = out.set_index("train_id")
    assert row.loc["T3", "alighting_train_est"] == pytest.approx(800.0 * 300 / 600)
    assert row.loc["T1", "alighting_train_est"] == pytest.approx(800.0 * 50 / 600)


def test_allocate_flows_missing_slot_is_nan():
    slot_flows = _slot_flows_single(station_no=999)  # 매칭 안 되는 역
    out = allocate_flows_to_trains(slot_flows, _node_rows_two_directions())
    assert out["boarding_train_est"].isna().all()
    assert out["alighting_train_est"].isna().all()


def test_allocate_flows_nan_slot_value_is_nan_only_for_that_flow():
    slot_flows = _slot_flows_single().assign(boarding_30min_est=np.nan)
    out = allocate_flows_to_trains(slot_flows, _node_rows_two_directions())
    assert out["boarding_train_est"].isna().all()
    assert out["alighting_train_est"].notna().all()


def test_allocate_flows_equal_direction_weight_when_loads_all_nan():
    node_rows = _node_rows_two_directions().assign(onboard_dep_est=np.nan, onboard_arr_est=np.nan)
    out = allocate_flows_to_trains(_slot_flows_single(), node_rows)
    by_dir = out.groupby("direction")["boarding_train_est"].sum()
    assert by_dir["내선"] == pytest.approx(500.0)
    assert by_dir["외선"] == pytest.approx(500.0)


# ── 239: platform_accumulation ──
def test_platform_accumulation_boundary_and_monotone():
    h = 10.0
    taus = np.array([0.0, 2.0, 5.0, 8.0, 10.0])
    f = platform_accumulation(taus, h, board_est=1.0)
    assert f[0] == pytest.approx(0.0)
    assert f[-1] == pytest.approx(1.0)
    assert np.all(np.diff(f) >= -1e-9)


def test_platform_accumulation_linear_when_headway_at_or_below_h0():
    h = 4.0  # MIX_H0_DEFAULT(5) 이하
    taus = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    f = platform_accumulation(taus, h, board_est=1.0)
    assert np.allclose(f, taus / h)


def test_platform_accumulation_right_skewed_for_long_headway():
    # h=20 >= MIX_H1_DEFAULT(15) -> w=0, 순수 Johnson SB. 절반 시점에 절반 미만이면 출발 직전에
    # 쏠리는 형태(우측 스큐)다.
    f_half = platform_accumulation(10.0, 20.0, board_est=1.0)
    assert f_half < 0.5


def test_platform_accumulation_raises_for_nonpositive_headway():
    with pytest.raises(ValueError):
        platform_accumulation(1.0, 0.0, board_est=1.0)


def test_platform_accumulation_broadcasts_over_arrays():
    taus = np.array([[0.0, 5.0], [10.0, 20.0]])
    headways = np.array([10.0, 20.0])
    out = platform_accumulation(taus, headways, board_est=100.0)
    assert out.shape == (2, 2)
    assert out[0, 0] == pytest.approx(0.0)
