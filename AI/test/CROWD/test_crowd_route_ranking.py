"""`validation/CROWD/route-ranking-check/{graph,score}.py`(경로 순위 뒤집힘 실험)의 순수 함수.

합성 입력만 쓴다 — 실제 데이터 파일은 건드리지 않는다. 폴더명에 하이픈이 있어 일반 import가
안 되므로 파일 경로로 읽어 온다(`test_crowd_calibration_holdout.py`와 같은 방식).
`networkx`는 무거운 의존성 가드 규약(`AI/CLAUDE.md`)에 따라 `importorskip`한다 — 이 환경
(SUMGIL conda)에는 3.6.1이 이미 있어 스킵되지 않는다.
"""

from __future__ import annotations

import importlib.util
import itertools
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("networkx")

AI_ROOT = Path(__file__).resolve().parents[2]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from app.CROWD.pipeline.congestion import ASCENDING, DESCENDING

_CHECK_DIR = AI_ROOT / "validation" / "CROWD" / "route-ranking-check"


def _load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, _CHECK_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


graph = _load_module("crowd_route_ranking_graph", "graph.py")
score = _load_module("crowd_route_ranking_score", "score.py")

DAY_TYPE = "평일"
TIMETABLE_COLS = [
    "station_no",
    "line",
    "direction",
    "day_type",
    "train_id",
    "arrival_time",
    "express",
]
STATION_COLS = ["station_no", "station_name", "line"]
SLOT_TABLE_COLS = ["station_no", "direction", "time_slot_30min", "congestion_pct"]
TRAIN_TABLE_COLS = [
    "station_no",
    "direction",
    "line",
    "train_id",
    "run_id",
    "pass_time",
    "load_dep_est",
    "load_arr_est",
]


def _timetable(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=TIMETABLE_COLS)


def _stations(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=STATION_COLS)


def _slot_table(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=SLOT_TABLE_COLS)


def _train_table(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=TRAIN_TABLE_COLS)


def _fmt(minute: float) -> str:
    m = round(minute)
    return f"{m // 60:02d}:{m % 60:02d}"


def _ab_timetable() -> pd.DataFrame:
    """A호선(1..5)·B호선(11..15) 하선·상선 각 3편성, 08:00부터 5분 간격.

    역 간 통과시간이 편성마다 똑같도록 만들어(중앙값 계산을 손으로 검산할 수 있게) 오프셋을
    고정한다 — 실제 시각표처럼 편성마다 편차를 두지 않는다(테스트 목적).
    """
    a_down = {1: 0, 2: 2, 3: 5, 4: 8, 5: 11}
    a_up = {5: 0, 4: 3, 3: 6, 2: 9, 1: 11}
    b_down = {11: 0, 12: 2, 13: 5, 14: 8, 15: 11}
    b_up = {15: 0, 14: 3, 13: 6, 12: 9, 11: 11}
    starts = [480, 485, 490]  # 08:00, 08:05, 08:10
    specs = [
        ("A호선", ASCENDING, a_down, "A_d"),
        ("A호선", DESCENDING, a_up, "A_u"),
        ("B호선", ASCENDING, b_down, "B_d"),
        ("B호선", DESCENDING, b_up, "B_u"),
    ]
    rows = []
    for line, direction, offsets, prefix in specs:
        for i, start in enumerate(starts):
            for station, offset in offsets.items():
                rows.append(
                    {
                        "station_no": station,
                        "line": line,
                        "direction": direction,
                        "day_type": DAY_TYPE,
                        "train_id": f"{prefix}_{i}",
                        "arrival_time": _fmt(start + offset),
                        "express": False,
                    }
                )
    return _timetable(rows)


def _ab_stations() -> pd.DataFrame:
    """A호선 1·2·4·5 + 환승역 3, B호선 11·12·14·15 + 환승역 13(3과 같은 역명 "Transfer")."""
    rows = [
        {"station_no": 1, "station_name": "A1", "line": "A호선"},
        {"station_no": 2, "station_name": "A2", "line": "A호선"},
        {"station_no": 3, "station_name": "Transfer", "line": "A호선"},
        {"station_no": 4, "station_name": "A4", "line": "A호선"},
        {"station_no": 5, "station_name": "A5", "line": "A호선"},
        {"station_no": 11, "station_name": "B1", "line": "B호선"},
        {"station_no": 12, "station_name": "B2", "line": "B호선"},
        {"station_no": 13, "station_name": "Transfer", "line": "B호선"},
        {"station_no": 14, "station_name": "B4", "line": "B호선"},
        {"station_no": 15, "station_name": "B5", "line": "B호선"},
    ]
    return _stations(rows)


def _ab_segments() -> list[dict]:
    return [
        {"line": "A호선", "segment": "본선", "stations": [1, 2, 3, 4, 5]},
        {"line": "B호선", "segment": "본선", "stations": [11, 12, 13, 14, 15]},
    ]


def _full_graph():
    return graph.build_graph(_ab_segments(), _ab_stations(), _ab_timetable())


def _scheduled_ab_legs(depart_min: float = 482.0):
    g = _full_graph()
    legs = graph.legs_of(g, [1, 2, 3, 13, 14, 15])
    return graph.schedule_path(g, legs, depart_min, _ab_timetable(), DAY_TYPE)


def _ride1_only_scheduled(depart_min: float = 482.0):
    g = _full_graph()
    legs = graph.legs_of(g, [1, 2, 3])
    return graph.schedule_path(g, legs, depart_min, _ab_timetable(), DAY_TYPE)


# ── build_graph — 방향 라벨 ──
def test_build_graph_direction_labels_linear_and_hard_fallback():
    segments = [{"line": "A호선", "segment": "본선", "stations": [1, 2, 3]}]
    stations = _stations(
        [{"station_no": s, "station_name": f"s{s}", "line": "A호선"} for s in (1, 2, 3)]
    )
    g = graph.build_graph(segments, stations, _timetable([]))

    assert g[1][2]["direction"] == ASCENDING
    assert g[2][3]["direction"] == ASCENDING
    assert g[2][1]["direction"] == DESCENDING
    assert g[3][2]["direction"] == DESCENDING
    for u, v in ((1, 2), (2, 3), (2, 1), (3, 2)):
        assert g[u][v]["kind"] == "ride"
        assert g[u][v]["minutes"] == pytest.approx(graph.FALLBACK_RIDE_MINUTES)
    assert g.graph["fallback_hard_edges"] == 4
    assert g.graph["fallback_line_median_edges"] == 0


def test_build_graph_circular_direction_labels():
    segments = [{"line": "C호선", "segment": "본선", "stations": [21, 22, 23], "circular": True}]
    stations = _stations(
        [{"station_no": s, "station_name": f"c{s}", "line": "C호선"} for s in (21, 22, 23)]
    )
    g = graph.build_graph(segments, stations, _timetable([]))

    assert g[21][22]["direction"] == "내선"
    assert g[22][23]["direction"] == "내선"
    assert g[23][21]["direction"] == "내선"  # wrap-around(마지막→첫)은 증가 방향 취급
    assert g[22][21]["direction"] == "외선"
    assert g[23][22]["direction"] == "외선"
    assert g[21][23]["direction"] == "외선"
    assert g.graph["fallback_hard_edges"] == 6


def test_build_graph_transfer_edges():
    stations = _stations(
        [
            {"station_no": 3, "station_name": "Transfer", "line": "A호선"},
            {"station_no": 13, "station_name": "Transfer", "line": "B호선"},
        ]
    )
    g = graph.build_graph([], stations, _timetable([]))

    for u, v in ((3, 13), (13, 3)):
        assert g.has_edge(u, v)
        assert g[u][v]["kind"] == "transfer"
        assert g[u][v]["minutes"] == pytest.approx(graph.DEFAULT_TRANSFER_WALK_MIN)


# ── build_graph — minutes(시각표 중앙값 · 대체) ──
def test_build_graph_ride_minutes_from_timetable():
    segments = [{"line": "A호선", "segment": "본선", "stations": [1, 2, 3, 4, 5]}]
    stations = _stations(
        [{"station_no": s, "station_name": f"A{s}", "line": "A호선"} for s in range(1, 6)]
    )
    g = graph.build_graph(segments, stations, _ab_timetable())

    assert g[1][2]["minutes"] == pytest.approx(2.0)
    assert g[2][3]["minutes"] == pytest.approx(3.0)
    assert g[3][4]["minutes"] == pytest.approx(3.0)
    assert g[4][5]["minutes"] == pytest.approx(3.0)
    assert g[2][1]["minutes"] == pytest.approx(2.0)
    assert g[3][2]["minutes"] == pytest.approx(3.0)
    assert g[4][3]["minutes"] == pytest.approx(3.0)
    assert g[5][4]["minutes"] == pytest.approx(3.0)
    assert g.graph["fallback_line_median_edges"] == 0
    assert g.graph["fallback_hard_edges"] == 0


def test_build_graph_line_median_fallback():
    segments = [{"line": "D호선", "segment": "본선", "stations": [31, 32, 33, 34]}]
    stations = _stations(
        [{"station_no": s, "station_name": f"D{s}", "line": "D호선"} for s in (31, 32, 33, 34)]
    )
    rows = [
        {
            "station_no": s,
            "line": "D호선",
            "direction": ASCENDING,
            "day_type": DAY_TYPE,
            "train_id": "D1",
            "arrival_time": t,
            "express": False,
        }
        for s, t in ((31, "08:00"), (32, "08:04"), (33, "08:10"))
    ]
    g = graph.build_graph(segments, stations, _timetable(rows))

    assert g[31][32]["minutes"] == pytest.approx(4.0)
    assert g[32][33]["minutes"] == pytest.approx(6.0)
    # 33->34 하선은 지난 열차가 없어 같은 호선의 다른(알려진) 간선 중앙값(4·6의 중앙값=5.0)으로 대체
    assert g[33][34]["minutes"] == pytest.approx(5.0)
    # 상선은 시각표가 전혀 없어 전부 같은 대체값
    for u, v in ((32, 31), (33, 32), (34, 33)):
        assert g[u][v]["minutes"] == pytest.approx(5.0)
    assert g.graph["fallback_line_median_edges"] == 4
    assert g.graph["fallback_hard_edges"] == 0


# ── candidate_routes / legs_of / schedule_path ──
def test_candidate_routes_includes_transfer_path():
    g = _full_graph()
    paths = graph.candidate_routes(g, 1, 15, k=3)

    assert 1 <= len(paths) <= 3
    assert paths[0][0] == 1 and paths[0][-1] == 15
    totals = [graph._path_minutes(g, p) for p in paths]
    assert totals == sorted(totals)
    assert any(any(g[u][v]["kind"] == "transfer" for u, v in itertools.pairwise(p)) for p in paths)


def test_candidate_routes_no_path_returns_empty():
    g = graph.build_graph(
        [{"line": "A호선", "segment": "본선", "stations": [1, 2]}],
        _stations([{"station_no": s, "station_name": f"A{s}", "line": "A호선"} for s in (1, 2)]),
        _timetable([]),
    )
    assert graph.candidate_routes(g, 1, 999, k=3) == []


def test_legs_of_splits_at_transfer():
    g = _full_graph()
    legs = graph.legs_of(g, [1, 2, 3, 13, 14, 15])

    assert [leg["kind"] for leg in legs] == ["ride", "transfer", "ride"]
    assert legs[0]["line"] == "A호선" and legs[0]["direction"] == ASCENDING
    assert legs[0]["stations"] == [1, 2, 3]
    assert legs[0]["minutes"] == pytest.approx(5.0)
    assert legs[1]["stations"] == [3, 13]
    assert legs[1]["minutes"] == pytest.approx(graph.DEFAULT_TRANSFER_WALK_MIN)
    assert legs[2]["line"] == "B호선" and legs[2]["direction"] == ASCENDING
    assert legs[2]["stations"] == [13, 14, 15]
    assert legs[2]["minutes"] == pytest.approx(6.0)


def test_schedule_path_node_times_increase_and_include_wait():
    scheduled = _scheduled_ab_legs(depart_min=482.0)

    # leg 안에서는 엄격 증가, leg 경계에서는 "도착 = 다음 leg 시작"이라 값이 같을 수 있다
    # (환승 leg의 첫 시각 = 직전 승차 leg의 도착 시각).
    for leg in scheduled:
        assert leg["node_times"] == sorted(leg["node_times"])
        assert len(leg["node_times"]) == len(set(leg["node_times"]))
    # leg 경계: 환승 leg는 직전 도착 시각에서 바로 시작하고(대기 없음), 승차 leg는 그 뒤
    # `wait_minutes`만큼 더 기다렸다 출발하므로 경계에서 같거나 늘어나기만 한다.
    for prev_leg, next_leg in itertools.pairwise(scheduled):
        assert next_leg["node_times"][0] >= prev_leg["arrive_min"] - 1e-9

    ride1, transfer, ride2 = scheduled
    assert ride1["node_times"][0] > 482.0  # 대기가 포함돼 출발 시각보다 늦다
    assert ride1["node_times"] == pytest.approx([484.5, 486.5, 489.5])
    assert transfer["node_times"] == pytest.approx([489.5, 494.5])
    assert ride2["node_times"][0] > transfer["node_times"][-1]
    assert ride2["node_times"] == pytest.approx([497.0, 500.0, 503.0])


# ── score_slot_table ──
def test_score_slot_table_time_weighted_mean_and_coverage():
    scheduled = _scheduled_ab_legs()
    slot_table = _slot_table(
        [
            {
                "station_no": 1,
                "direction": ASCENDING,
                "time_slot_30min": "08:00",
                "congestion_pct": 40.0,
            },
            {
                "station_no": 2,
                "direction": ASCENDING,
                "time_slot_30min": "08:00",
                "congestion_pct": 60.0,
            },
            {
                "station_no": 13,
                "direction": ASCENDING,
                "time_slot_30min": "08:00",
                "congestion_pct": np.nan,
            },
            {
                "station_no": 14,
                "direction": ASCENDING,
                "time_slot_30min": "08:00",
                "congestion_pct": 80.0,
            },
        ]
    )
    result = score.score_slot_table(scheduled, slot_table)

    assert result["n_links"] == 4
    assert result["missing"] == 1
    assert result["coverage"] == pytest.approx(0.75)
    assert result["mean_tw"] == pytest.approx(62.5)
    assert result["max"] == pytest.approx(80.0)
    assert result["duplicate_keys"] == 0


def test_score_slot_table_all_missing_is_nan():
    scheduled = _scheduled_ab_legs()
    result = score.score_slot_table(scheduled, _slot_table([]))

    assert result["coverage"] == 0.0
    assert math.isnan(result["mean_tw"])
    assert math.isnan(result["max"])
    assert result["missing"] == result["n_links"] == 4


def test_score_slot_table_duplicate_key_takes_max():
    scheduled = _scheduled_ab_legs()
    slot_table = _slot_table(
        [
            {
                "station_no": 1,
                "direction": ASCENDING,
                "time_slot_30min": "08:00",
                "congestion_pct": 40.0,
            },
            {
                "station_no": 2,
                "direction": ASCENDING,
                "time_slot_30min": "08:00",
                "congestion_pct": 60.0,
            },
            {
                "station_no": 2,
                "direction": ASCENDING,
                "time_slot_30min": "08:00",
                "congestion_pct": 95.0,
            },
            {
                "station_no": 13,
                "direction": ASCENDING,
                "time_slot_30min": "08:00",
                "congestion_pct": 10.0,
            },
            {
                "station_no": 14,
                "direction": ASCENDING,
                "time_slot_30min": "08:00",
                "congestion_pct": 80.0,
            },
        ]
    )
    result = score.score_slot_table(scheduled, slot_table)

    assert result["duplicate_keys"] == 1
    assert result["coverage"] == pytest.approx(1.0)
    assert result["max"] == pytest.approx(95.0)


# ── score_train_table ──
def test_score_train_table_picks_earliest_train_and_follows_id():
    scheduled = _ride1_only_scheduled()  # node_times == [484.5, 486.5, 489.5]
    train_table = _train_table(
        [
            {
                "station_no": 1,
                "direction": ASCENDING,
                "line": "A호선",
                "train_id": "T1",
                "run_id": 0,
                "pass_time": "08:03",
                "load_dep_est": 999.0,
                "load_arr_est": np.nan,
            },
            {
                "station_no": 1,
                "direction": ASCENDING,
                "line": "A호선",
                "train_id": "T2",
                "run_id": 0,
                "pass_time": "08:05",
                "load_dep_est": 50.0,
                "load_arr_est": np.nan,
            },
            {
                "station_no": 2,
                "direction": ASCENDING,
                "line": "A호선",
                "train_id": "T2",
                "run_id": 0,
                "pass_time": "08:07",
                "load_dep_est": 55.0,
                "load_arr_est": np.nan,
            },
            {
                "station_no": 3,
                "direction": ASCENDING,
                "line": "A호선",
                "train_id": "T2",
                "run_id": 0,
                "pass_time": "08:09",
                "load_dep_est": np.nan,
                "load_arr_est": 45.0,
            },
            {
                "station_no": 1,
                "direction": ASCENDING,
                "line": "A호선",
                "train_id": "T3",
                "run_id": 0,
                "pass_time": "08:07",
                "load_dep_est": 999.0,
                "load_arr_est": np.nan,
            },
        ]
    )
    result = score.score_train_table(scheduled, train_table)

    assert result["trains"] == ["T2"]
    assert result["n_links"] == 3
    assert result["missing"] == 0
    assert result["mean_tw"] == pytest.approx(50.0)
    assert result["max"] == pytest.approx(55.0)


def test_score_train_table_no_train_found_leg_is_nan():
    scheduled = _ride1_only_scheduled()
    scheduled[0]["node_times"] = [10_000.0, 10_002.0, 10_005.0]  # 실제 열차보다 훨씬 뒤

    train_table = _train_table(
        [
            {
                "station_no": 1,
                "direction": ASCENDING,
                "line": "A호선",
                "train_id": "T2",
                "run_id": 0,
                "pass_time": "08:05",
                "load_dep_est": 50.0,
                "load_arr_est": np.nan,
            },
        ]
    )
    result = score.score_train_table(scheduled, train_table)

    assert result["trains"] == [None]
    assert result["missing"] == result["n_links"] == 3
    assert math.isnan(result["mean_tw"])
    assert math.isnan(result["max"])


def test_score_train_table_missing_station_row_is_nan_for_that_node():
    scheduled = _ride1_only_scheduled()
    train_table = _train_table(
        [
            {
                "station_no": 1,
                "direction": ASCENDING,
                "line": "A호선",
                "train_id": "T2",
                "run_id": 0,
                "pass_time": "08:05",
                "load_dep_est": 50.0,
                "load_arr_est": np.nan,
            },
            # station 2 행 없음 — 그 노드만 NaN
            {
                "station_no": 3,
                "direction": ASCENDING,
                "line": "A호선",
                "train_id": "T2",
                "run_id": 0,
                "pass_time": "08:09",
                "load_dep_est": np.nan,
                "load_arr_est": 45.0,
            },
        ]
    )
    result = score.score_train_table(scheduled, train_table)

    assert result["missing"] == 1
    assert result["coverage"] == pytest.approx(2 / 3)


# ── rank ──
def test_rank_puts_noncomparable_last():
    candidates = [
        {"mean_tw": 50.0, "coverage": 0.9},
        {"mean_tw": 30.0, "coverage": 0.9},
        {"mean_tw": 20.0, "coverage": 0.3},  # coverage 미달
        {"mean_tw": float("nan"), "coverage": 0.95},  # NaN 점수
    ]
    order = score.rank(candidates, key="mean_tw", min_coverage=0.5)

    assert order == [1, 0, 2, 3]
    assert [c["comparable"] for c in candidates] == [True, True, False, False]
