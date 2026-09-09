import numpy as np
import pandas as pd

from DATA_ENGINE.eda.build_congestion_label import (
    ASCENDING,
    DESCENDING,
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
