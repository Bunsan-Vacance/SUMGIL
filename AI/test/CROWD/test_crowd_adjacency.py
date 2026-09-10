"""app/CROWD/pipeline/adjacency.py — 인접역 매핑·피처 부착."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.CROWD.pipeline.adjacency import (
    attach_neighbor_features,
    build_neighbor_map,
    neighbor_feature_names,
)


def _pairs(nmap: pd.DataFrame, station: int, side: str) -> set[int]:
    sel = nmap[(nmap["station_no"] == station) & (nmap["side"] == side)]
    return set(sel["neighbor_station_no"])


def test_linear_segment_ends_have_no_neighbor_on_open_side():
    nmap = build_neighbor_map([{"line": "L", "segment": "본선", "stations": [1, 2, 3]}])
    assert _pairs(nmap, 1, "prev") == set()
    assert _pairs(nmap, 1, "next") == {2}
    assert _pairs(nmap, 2, "prev") == {1}
    assert _pairs(nmap, 2, "next") == {3}
    assert _pairs(nmap, 3, "next") == set()


def test_circular_segment_wraps_around():
    nmap = build_neighbor_map([{"line": "2호선", "circular": True, "stations": [201, 202, 203]}])
    assert _pairs(nmap, 201, "prev") == {203}
    assert _pairs(nmap, 203, "next") == {201}


def test_branch_point_collects_neighbors_from_every_segment():
    segs = [
        {"line": "5호선", "segment": "본선", "stations": [2547, 2548, 2549]},
        {"line": "5호선", "segment": "하남선", "stations": [2549, 2550, 2551]},
        {"line": "5호선", "segment": "마천지선", "stations": [2549, 2555, 2556]},
    ]
    nmap = build_neighbor_map(segs)
    assert _pairs(nmap, 2549, "prev") == {2548}
    assert _pairs(nmap, 2549, "next") == {2550, 2555}
    # 같은 쌍이 두 세그먼트에서 나와도 한 번만 남는다.
    assert not nmap.duplicated(["station_no", "side", "neighbor_station_no"]).any()


def test_descending_list_follows_list_order_not_station_number():
    # 9호선은 리스트를 역번호 내림차순으로 둔다 — prev/next는 리스트 순서를 따라야 한다.
    nmap = build_neighbor_map([{"line": "9호선", "stations": [4138, 4137, 4136]}])
    assert _pairs(nmap, 4137, "prev") == {4138}
    assert _pairs(nmap, 4137, "next") == {4136}


def test_single_station_segment_is_ignored():
    assert build_neighbor_map([{"stations": [7]}]).empty


def _panel() -> pd.DataFrame:
    rows = []
    for slot in ("07-08", "08-09"):
        for s, b in ((1, 10.0), (2, 20.0), (3, 30.0), (4, 40.0)):
            rows.append(
                {
                    "date": pd.Timestamp("2025-01-01"),
                    "time_slot": slot,
                    "station_no": s,
                    "boarding": b if slot == "07-08" else b * 2,
                }
            )
    return pd.DataFrame(rows)


def test_attach_uses_same_date_and_slot_and_leaves_ends_nan():
    nmap = build_neighbor_map([{"stations": [1, 2, 3]}])
    out = attach_neighbor_features(_panel(), nmap, ["boarding"])
    assert len(out) == 8
    assert list(out.columns[-2:]) == ["nb_prev_boarding", "nb_next_boarding"]
    r = out.set_index(["time_slot", "station_no"])
    assert r.loc[("07-08", 2), "nb_prev_boarding"] == 10.0
    assert r.loc[("07-08", 2), "nb_next_boarding"] == 30.0
    assert r.loc[("08-09", 2), "nb_prev_boarding"] == 20.0  # 같은 시간대만 본다
    assert np.isnan(r.loc[("07-08", 1), "nb_prev_boarding"])  # 종점
    assert np.isnan(r.loc[("07-08", 4), "nb_prev_boarding"])  # 토폴로지에 없는 역


def test_attach_aggregates_multiple_neighbors_with_mean():
    nmap = build_neighbor_map([{"stations": [1, 2]}, {"stations": [1, 4]}])
    out = attach_neighbor_features(_panel(), nmap, ["boarding"])
    r = out.set_index(["time_slot", "station_no"])
    assert r.loc[("07-08", 1), "nb_next_boarding"] == 30.0  # (20+40)/2


def test_attach_preserves_row_order_and_count():
    panel = _panel().sample(frac=1, random_state=0).reset_index(drop=True)
    nmap = build_neighbor_map([{"stations": [1, 2, 3]}])
    out = attach_neighbor_features(panel, nmap, ["boarding"])
    pd.testing.assert_frame_equal(out[panel.columns], panel)


def test_feature_names_match_attached_columns():
    names = neighbor_feature_names(["boarding", "alighting"])
    assert names == [
        "nb_prev_boarding",
        "nb_prev_alighting",
        "nb_next_boarding",
        "nb_next_alighting",
    ]
