"""경로 순위 뒤집힘 실험(239 후속, `RESOLUTION_LADDER.md` §6)이 쓰는 OD 그래프 — BE 그래프가 아니다.

우리 토폴로지(`topology.resolve_segments`)와 시각표(`timetable.load_timetable`)만으로 최단
경로·대안 경로를 만든다. 노드는 `station_no`, 간선은 두 종류다.

- **승차(ride) 간선**: 한 세그먼트의 인접 역 쌍(양방향). `minutes`는 시각표에서 그 구간을
  실제로 지난 열차들의 통과시각 차 중앙값이다 — 요일유형을 구분하지 않고 시각표 전체에서
  중앙값을 낸다(그래프는 한 번만 만들고, 요일유형별 시간은 `wait_minutes`·`schedule_path`가
  실제 출발 시각과 함께 다시 반영한다 — PoC 단순화, 서비스 그래프가 아니다). 지날 열차가
  하나도 없으면 같은 호선의 다른 간선 중앙값으로, 그것도 없으면 `FALLBACK_RIDE_MINUTES`(2.0분)
  상수로 채운다 — 채워 넣은 값임을 숨기지 않고 `graph.graph["fallback_line_median_edges"]`·
  `graph.graph["fallback_hard_edges"]`에 개수를 남긴다(원칙 8과 같은 태도).
- **환승(transfer) 간선**: `adjacency.build_transfer_map`이 찾은, 같은 역명·다른 `station_no`
  쌍(양방향)에 고정 도보 시간(`transfer_walk_min`)을 준다.

동일한 (from, to, line, direction)이 여러 세그먼트에 걸쳐 나오면(강동처럼 겹치는 구간)
`networkx.DiGraph`는 병렬 간선을 허용하지 않으므로 마지막에 처리된 세그먼트 값이 남는다 —
BE 그래프가 아닌 순위 실험용 근사라 허용한다.

`networkx`는 무거운 의존성(torch 설치 시 같이 들어오는 패키지)이라 함수 안에서 지연
import한다(`AI/CLAUDE.md` 무거운 의존성 가드). 이 환경(SUMGIL conda)에는 3.6.1이 이미 있다.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence

import numpy as np
import pandas as pd

from app.CROWD.pipeline.adjacency import build_transfer_map
from app.CROWD.pipeline.congestion import ASCENDING, CIRCULAR_LABELS, DESCENDING
from app.CROWD.pipeline.disaggregate import SLOT_MINUTES, minutes_to_slot30, to_minutes

DEFAULT_TRANSFER_WALK_MIN = 5.0
# 지날 열차가 하나도 없는 간선의 대체값(문서화된 가정, 채워 넣은 값임을 숨기지 않는다).
FALLBACK_RIDE_MINUTES = 2.0
# `wait_minutes`가 같은 슬롯 안 헤드웨이를 하나도 못 찾았을 때의 대체값(문서화된 가정).
FALLBACK_WAIT_MIN = 3.0


def _train_time_lookup(timetable: pd.DataFrame) -> dict[tuple[str, str], list[dict[int, float]]]:
    """(line, direction)별로 "열차 한 편의 역 → 통과분" 딕셔너리 목록을 만든다.

    요일유형을 구분하지 않고 전부 모은다(모듈 docstring 참고) — 같은 (line, direction, train_id,
    day_type) 조합이 한 편이다. 시각표가 비어 있으면(문자열 컬럼도 없는 빈 프레임 포함) 빈
    딕셔너리를 돌려준다 — `to_minutes`(`str.split`)는 빈 프레임에서 열 자체가 없어 실패한다.
    """
    if timetable.empty:
        return {}
    tt = timetable.copy()
    tt["_arr_min"] = to_minutes(tt["arrival_time"])
    out: dict[tuple[str, str], list[dict[int, float]]] = {}
    group_cols = ["line", "direction", "train_id", "day_type"]
    for (line, direction, _train_id, _day_type), g in tt.groupby(group_cols, observed=True):
        out.setdefault((line, direction), []).append(
            dict(zip(g["station_no"].tolist(), g["_arr_min"].tolist()))
        )
    return out


def _edge_minutes(
    lookup: dict[tuple[str, str], list[dict[int, float]]],
    line: str,
    direction: str,
    frm: int,
    to: int,
) -> float | None:
    """시각표에서 `frm → to`를 실제로 지난 열차들의 통과시각 차 중앙값. 없으면 `None`."""
    diffs = [
        m[to] - m[frm]
        for m in lookup.get((line, direction), ())
        if frm in m and to in m and m[to] > m[frm]
    ]
    return float(np.median(diffs)) if diffs else None


def build_graph(
    segments: Sequence[dict],
    stations: pd.DataFrame,
    timetable: pd.DataFrame,
    *,
    transfer_walk_min: float = DEFAULT_TRANSFER_WALK_MIN,
):
    """해석된 세그먼트(`topology.resolve_segments`) + 시각표 → OD 탐색용 `networkx.DiGraph`.

    `stations`는 `station_no`·`station_name`(·선택적 `line`) 컬럼을 가진 역 목록
    (`adjacency.build_transfer_map`의 입력과 같다). 노드는 `station_no`, 간선 속성은
    `line`·`segment`·`direction`·`minutes`·`kind`(`"ride"` 또는 `"transfer"`)다.

    방향 라벨은 세그먼트 리스트의 인덱스가 증가하는 쪽이 `congestion.ASCENDING`("하선"),
    감소하는 쪽이 `congestion.DESCENDING`("상선")이고(`congestion.py`의 약속과 동일),
    `circular` 세그먼트는 `CIRCULAR_LABELS`로 내선/외선으로 옮긴다. wrap-around 간선
    (마지막 역 → 첫 역)은 증가 방향으로 취급한다(스펙 지시).
    """
    import networkx as nx

    ride_edges: list[dict] = []
    for seg in segments:
        seg_stations = [int(s) for s in seg.get("stations", ())]
        n = len(seg_stations)
        if n < 2:
            continue
        circular = bool(seg.get("circular"))
        line, segment_name = seg["line"], seg["segment"]
        raw_pairs = [(seg_stations[i], seg_stations[i + 1], ASCENDING) for i in range(n - 1)]
        raw_pairs += [(seg_stations[i + 1], seg_stations[i], DESCENDING) for i in range(n - 1)]
        if circular:
            raw_pairs.append((seg_stations[-1], seg_stations[0], ASCENDING))
            raw_pairs.append((seg_stations[0], seg_stations[-1], DESCENDING))
        for frm, to, raw_label in raw_pairs:
            direction = CIRCULAR_LABELS[raw_label] if circular else raw_label
            ride_edges.append(
                {
                    "from": frm,
                    "to": to,
                    "line": line,
                    "segment": segment_name,
                    "direction": direction,
                }
            )

    train_lookup = _train_time_lookup(timetable)
    direct: dict[tuple[str, str, int, int], float | None] = {}
    for e in ride_edges:
        key = (e["line"], e["direction"], e["from"], e["to"])
        if key not in direct:
            direct[key] = _edge_minutes(train_lookup, *key)

    line_known: dict[str, list[float]] = {}
    for e in ride_edges:
        v = direct[(e["line"], e["direction"], e["from"], e["to"])]
        if v is not None:
            line_known.setdefault(e["line"], []).append(v)
    line_fallback = {ln: float(np.median(vs)) for ln, vs in line_known.items()}

    g = nx.DiGraph()
    n_line_fallback = 0
    n_hard_fallback = 0
    for e in ride_edges:
        key = (e["line"], e["direction"], e["from"], e["to"])
        minutes = direct[key]
        if minutes is None:
            minutes = line_fallback.get(e["line"])
            if minutes is None:
                minutes = FALLBACK_RIDE_MINUTES
                n_hard_fallback += 1
            else:
                n_line_fallback += 1
        g.add_edge(
            e["from"],
            e["to"],
            line=e["line"],
            segment=e["segment"],
            direction=e["direction"],
            minutes=float(minutes),
            kind="ride",
        )

    transfer_map = build_transfer_map(stations)
    for _, row in transfer_map.iterrows():
        g.add_edge(
            int(row["station_no"]),
            int(row["neighbor_station_no"]),
            line=row.get("line"),
            segment=row.get("segment"),
            direction=None,
            minutes=float(transfer_walk_min),
            kind="transfer",
        )

    g.graph["fallback_line_median_edges"] = n_line_fallback
    g.graph["fallback_hard_edges"] = n_hard_fallback
    return g


def wait_minutes(
    timetable: pd.DataFrame,
    station_no: int,
    direction: str,
    day_type: str,
    minute_of_day: float,
) -> float:
    """탑승 대기시간(분) = 같은 30분 슬롯에 든 열차들의 헤드웨이 중앙값 ÷ 2.

    슬롯 배정은 `disaggregate.allocate_to_trains`와 같은 규칙(30분 내림 → `minutes_to_slot30`)을
    쓴다 — 헤드웨이는 "그 열차와 직전 열차의 간격"이고, 슬롯은 **그 열차 자신의 도착 시각**으로
    정한다(슬롯 첫 열차의 헤드웨이는 슬롯 경계 이전 마지막 열차와의 간격이다). 그 (역, 방향,
    요일유형)에 열차가 없거나 그 슬롯에 헤드웨이가 하나도 없으면 `FALLBACK_WAIT_MIN`(3.0분,
    문서화된 가정).
    """
    sub = timetable[
        (timetable["station_no"] == station_no)
        & (timetable["direction"] == direction)
        & (timetable["day_type"] == day_type)
    ].copy()
    if sub.empty:
        return FALLBACK_WAIT_MIN
    sub["_arr_min"] = to_minutes(sub["arrival_time"])
    sub = sub.sort_values("_arr_min")
    sub["_headway"] = sub["_arr_min"].diff()
    slot_start = (sub["_arr_min"] // SLOT_MINUTES) * SLOT_MINUTES
    sub["_slot"] = slot_start.map(minutes_to_slot30)
    target_slot = minutes_to_slot30((int(minute_of_day) // SLOT_MINUTES) * SLOT_MINUTES)
    in_slot = sub.loc[sub["_slot"] == target_slot, "_headway"].dropna()
    if in_slot.empty:
        return FALLBACK_WAIT_MIN
    return float(in_slot.median()) / 2.0


def _path_minutes(graph, path: list[int]) -> float:
    return float(sum(graph[u][v]["minutes"] for u, v in itertools.pairwise(path)))


def _dedup_signature(graph, path: list[int]) -> tuple[int, ...]:
    """환승 간선의 도착 노드를 신호에서 뺀다 — 같은 물리적 경로를 다른 환승 노드 번호로 표현한
    경로끼리 겹치는 것을 잡기 위해서다."""
    sig = [path[0]]
    for u, v in itertools.pairwise(path):
        if graph[u][v].get("kind") == "transfer":
            continue
        sig.append(v)
    return tuple(sig)


def candidate_routes(
    graph, origin: int, dest: int, k: int = 3, slack_min: float = 15.0
) -> list[list[int]]:
    """origin → dest 후보 경로 최대 `k`개(역번호 시퀀스 목록).

    `networkx.shortest_simple_paths`(가중치 `minutes`, 오름차순)에서 앞의 `k`개만 본다 — 그
    뒤를 더 뒤져 `k`개를 채우지 않는다(스펙이 정한 그대로: "take up to k paths"가 먼저다).
    그중 총 소요가 최단 경로 + `slack_min`을 넘는 것과, 환승 간선을 뺀 역 시퀀스가 같은
    경로(중복)를 뺀다. 경로가 없으면(`NetworkXNoPath`/`NodeNotFound`) 빈 리스트.
    """
    import networkx as nx

    if origin == dest:
        return []
    try:
        gen = nx.shortest_simple_paths(graph, origin, dest, weight="minutes")
        paths = list(itertools.islice(gen, k))
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []
    if not paths:
        return []
    totals = [_path_minutes(graph, p) for p in paths]
    best = min(totals)
    kept = [(p, t) for p, t in zip(paths, totals) if t <= best + slack_min]

    out: list[list[int]] = []
    seen_sig: set[tuple[int, ...]] = set()
    for p, _t in kept:
        sig = _dedup_signature(graph, p)
        if sig in seen_sig:
            continue
        seen_sig.add(sig)
        out.append(p)
    return out


def legs_of(graph, path: list[int]) -> list[dict]:
    """경로를 구간(leg)으로 쪼갠다 — 간선의 `line`이 바뀌거나 환승 간선을 만나면 새 leg.

    승차 leg: `{"kind": "ride", "line", "direction", "stations": [...], "minutes"}`
    (`direction`은 leg 첫 간선의 값을 쓴다 — 같은 `line` 안에서 환승 없이 방향이 바뀌는 것은
    상정하지 않는다). 환승 leg: `{"kind": "transfer", "stations": [u, v], "minutes"}`.
    """
    legs: list[dict] = []
    cur: dict | None = None
    for u, v in itertools.pairwise(path):
        edge = graph[u][v]
        if edge.get("kind") == "transfer":
            if cur is not None:
                legs.append(cur)
                cur = None
            legs.append({"kind": "transfer", "stations": [u, v], "minutes": float(edge["minutes"])})
            continue
        if cur is None or cur["line"] != edge["line"]:
            if cur is not None:
                legs.append(cur)
            cur = {
                "kind": "ride",
                "line": edge["line"],
                "direction": edge["direction"],
                "stations": [u, v],
                "minutes": float(edge["minutes"]),
            }
        else:
            cur["stations"].append(v)
            cur["minutes"] += float(edge["minutes"])
    if cur is not None:
        legs.append(cur)
    return legs


def schedule_path(
    graph, legs: list[dict], depart_min: float, timetable: pd.DataFrame, day_type: str
) -> list[dict]:
    """leg 목록을 시간순으로 채워 `node_times`(leg의 `stations`와 같은 길이)를 붙인다.

    승차 leg 시작에서는 `wait_minutes`만큼 기다린 뒤 열차를 탄다고 보고(그 시각이
    `node_times[0]`), 그 뒤 간선별 `minutes`를 누적한다. 환승 leg는 `stations`가 [내리는 역,
    갈아타는 역] 두 개이고 `minutes`(도보)만 더한다. 반환은 leg마다 `node_times`·`depart_min`
    (leg 시작 시각)·`arrive_min`(leg 끝 시각)이 붙은 새 리스트다 — 전체 도착 시각은
    `legs[-1]["arrive_min"]`(경로 총 소요 = 그 값 − 최초 `depart_min`).
    """
    out: list[dict] = []
    t = float(depart_min)
    for leg in legs:
        leg = dict(leg)
        if leg["kind"] == "transfer":
            node_times = [t, t + leg["minutes"]]
            t = node_times[-1]
        else:
            stations = leg["stations"]
            t += wait_minutes(timetable, stations[0], leg["direction"], day_type, t)
            node_times = [t]
            for u, v in itertools.pairwise(stations):
                t += graph[u][v]["minutes"]
                node_times.append(t)
        leg["node_times"] = node_times
        leg["depart_min"] = node_times[0]
        leg["arrive_min"] = node_times[-1]
        out.append(leg)
    return out
