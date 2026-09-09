import numpy as np
import pandas as pd

from DATA_ENGINE.eda.build_congestion_label import (
    ASCENDING,
    CIRCULAR_LABELS,
    DESCENDING,
    circular_loads,
    circular_path_masks,
    directional_loads,
    expand_stations,
    resolve_segments,
)


def test_expand_stations_expands_range_and_keeps_literals():
    assert expand_stations([{"range": [201, 204]}, 250]) == [201, 202, 203, 204, 250]


def test_resolve_segments_drops_absent_stations_and_reports_them():
    topology = [{"line": "3호선", "segment": "본선", "stations": [{"range": [319, 322]}]}]

    resolved, gaps = resolve_segments(topology, available={319, 320, 322})

    assert resolved[0]["stations"] == [319, 320, 322]
    assert gaps.iloc[0]["missing"] == [321]


def test_directional_loads_are_zero_at_both_ends():
    """첫 역 이전과 마지막 역 이후로는 갈 곳이 없으니 통과량이 0이어야 한다."""
    boarding = np.array([100.0, 50.0, 30.0, 0.0])
    alighting = np.array([0.0, 40.0, 60.0, 80.0])

    up, down = directional_loads(boarding, alighting)

    assert up[-1] == 0.0
    assert down[0] == 0.0


def test_directional_loads_one_way_line_has_no_reverse_flow():
    """모두가 앞쪽에서 타서 뒤쪽에서만 내리면 역방향 통과량은 0이다."""
    boarding = np.array([100.0, 0.0, 0.0])
    alighting = np.array([0.0, 0.0, 100.0])

    up, down = directional_loads(boarding, alighting)

    assert up[0] == 100.0
    assert np.allclose(down, 0.0)


def test_directional_loads_counts_boarders_at_the_departure_station():
    """마지막 역에서 타고 역방향으로 가는 인원이 그 역 출발 통과량에 포함돼야 한다.

    내림차순 쪽을 `i > n`으로 두면 이 인원이 통째로 빠져 한쪽만 과소 집계된다.
    """
    boarding = np.array([0.0, 0.0, 100.0])
    alighting = np.array([100.0, 0.0, 0.0])

    _, down = directional_loads(boarding, alighting)

    assert down[2] == 100.0  # 2번 역을 떠나는 역방향 열차에 100명이 타 있다
    assert down[1] == 100.0
    assert down[0] == 0.0


def test_directional_loads_handles_empty_slot():
    boarding = np.zeros(3)
    alighting = np.zeros(3)

    up, down = directional_loads(boarding, alighting)

    assert np.allclose(up, 0.0)
    assert np.allclose(down, 0.0)


def test_ascending_accumulation_is_labelled_down_line():
    """역번호 오름차순 누적은 하선이다 — 실측 대조로 확정된 관례(반대로 두면 상관이 뒤집힌다)."""
    assert ASCENDING == "하선"
    assert DESCENDING == "상선"


def test_circular_labels_are_opposite_of_linear():
    """순환선은 오름차순이 내선이다 — 선형(하선)과 반대 방향으로 대응한다."""
    assert CIRCULAR_LABELS[ASCENDING] == "내선"
    assert CIRCULAR_LABELS[DESCENDING] == "외선"


def test_circular_path_masks_pick_the_shorter_way_around():
    """순환선에서 먼 쪽으로 돌아가지 않는다 — 6역 노선에서 0→1은 오름차순 한 칸이다."""
    asc, desc = circular_path_masks(6)

    assert asc[:, 0, 1].sum() == 1  # 링크 하나만 지난다
    assert desc[:, 0, 1].sum() == 0  # 반대로 5칸 도는 경로는 안 쓴다
    # 0→4는 내림차순 2칸(0→5→4)이 오름차순 4칸보다 짧다
    assert desc[:, 0, 4].sum() == 2
    assert asc[:, 0, 4].sum() == 0


def test_circular_loads_wrap_around_the_loop():
    """순환선은 마지막 역과 첫 역이 이어져 있어 그 링크에도 통과량이 실린다."""
    n = 4
    masks = circular_path_masks(n)
    boarding = np.array([0.0, 0.0, 0.0, 100.0])
    alighting = np.array([100.0, 0.0, 0.0, 0.0])

    asc, _ = circular_loads(boarding, alighting, masks)

    # 3번에서 타 0번에서 내리면 오름차순 한 칸(3→0)이 최단이라 마지막 링크만 실린다
    assert asc[3] == 100.0
    assert np.allclose(asc[:3], 0.0)


def test_directional_loads_matches_manual_proportional_split():
    """비례 배분 OD의 수식을 손으로 푼 값과 맞는지 확인한다."""
    boarding = np.array([10.0, 0.0, 0.0])
    alighting = np.array([0.0, 4.0, 6.0])

    up, _ = directional_loads(boarding, alighting)

    # 총하차 10, 1번 역 하차 0 → 가중치 10/10 = 1.0
    # 링크0 통과량 = 1.0 × (뒤쪽 하차 4+6) = 10, 링크1 = 1.0 × 6 = 6
    assert np.allclose(up, [10.0, 6.0, 0.0])


def test_expand_stations_accepts_plain_list():
    assert expand_stations([211, 244, 245]) == [211, 244, 245]


def test_resolve_segments_reports_nothing_when_all_present():
    topology = [{"line": "8호선", "segment": "본선", "stations": [2810, 2811]}]

    resolved, gaps = resolve_segments(topology, available={2810, 2811})

    assert resolved[0]["stations"] == [2810, 2811]
    assert gaps.empty


def test_directional_loads_conserves_flow_symmetry():
    """상행·하행 통과량의 합은 총 통행량을 넘지 않는다."""
    rng = np.random.default_rng(0)
    boarding = rng.uniform(0, 100, 8)
    alighting = rng.uniform(0, 100, 8)

    up, down = directional_loads(boarding, alighting)

    assert (up >= 0).all()
    assert (down >= 0).all()
    assert pd.notna(up).all()
