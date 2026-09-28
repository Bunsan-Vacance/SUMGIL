"""시각표 로딩·요일유형 변환·슬롯 카운트 — 열차·노드 표(239)가 쓰는 소규모 헬퍼.

`app/`은 `DATA_ENGINE/`을 import하지 않는 규약(`AI/CLAUDE.md`)이라
`DATA_ENGINE/eda/parsers_timetable.day_type_to_timetable`과
`DATA_ENGINE/eda/build_load_by_train.prepare_inputs`의 시각표 정리·슬롯 카운트 로직을 여기
복제한다. 두 곳이 갈리면 안 되므로 규칙을 바꿀 때는 두 파일을 같이 고친다.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from app.CROWD.pipeline.disaggregate import (
    SLOT_MINUTES,
    minutes_to_slot30,
    segment_has_adjacent,
    segment_is_terminal,
    to_minutes,
)

# `load_timetable`이 남기는 컬럼과 순서 — 135 시각표 interim 원본에는 이 밖에도
# direction_code·origin·terminus 등이 있지만 열차 배분(`disaggregate.allocate_to_trains`)에는
# 필요 없어 버린다.
TIMETABLE_COLS = [
    "station_no",
    "line",
    "direction",
    "day_type",
    "train_id",
    "arrival_time",
    "express",
]


def timetable_day_type(day_type: str) -> str:
    """패널 요일유형 → 시각표 요일유형. 공휴일은 일요일 시각표를 쓴다.

    `DATA_ENGINE/eda/parsers_timetable.day_type_to_timetable`과 같은 규칙이다 — `app/`이
    `DATA_ENGINE/`을 import할 수 없어(`AI/CLAUDE.md`) 여기 복제했다. 서울교통공사 열차운행
    시각표는 평일·토요일·일요일 3종 다이어로만 돌고 공휴일 다이어가 따로 없다(`RESOLUTION_LADDER.md`
    §2).
    """
    return "일요일" if day_type == "휴일" else day_type


def load_timetable(path: Path) -> pd.DataFrame:
    """135 파서(`DATA_ENGINE.eda.parsers_timetable`)가 만든 시각표 interim parquet을 읽는다.

    원본에 `arrival_time`/`departure_time`이 있으면 버리고 `pass_time`(도착, 없으면 출발 —
    그 역을 "지나는" 시각)을 `arrival_time`으로 쓴다(`DATA_ENGINE/eda/build_load_by_train.
    prepare_inputs`와 같은 처리). `TIMETABLE_COLS`만 남겨 돌려준다. 파일이 없으면 무엇을 먼저
    돌려야 하는지 알려주는 오류를 낸다 — 옵션(`settings.crowd_train_table`)을 켰을 때만 불린다.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"시각표 interim 파일이 없다: {path} — 먼저 `python -m DATA_ENGINE.eda.parsers_timetable`로 "
            "공공데이터포털 15098251(열차운행시각표) 원본 CSV를 파싱해 만든다"
        )
    tt = pd.read_parquet(path)
    tt = tt.drop(columns=["arrival_time", "departure_time"], errors="ignore")
    tt = tt.rename(columns={"pass_time": "arrival_time"})
    return tt[TIMETABLE_COLS]


def timetable_version(path: Path) -> str:
    """시각표 파일의 버전 표시(`파일명@수정일`, 로컬 시각).

    interim parquet에는 버전 컬럼이 없어(135) 파일 mtime으로 대신한다 — 배치 메타
    `timetable_version`에 그대로 실린다.
    """
    path = Path(path)
    # tz 없는 fromtimestamp는 ruff DTZ006가 막는다 — UTC로 만든 뒤 로컬로 변환해도 값(로컬
    # 자정 기준 날짜)은 tz-naive로 바로 만드는 것과 같다.
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).astimezone()
    return f"{path.name}@{mtime:%Y-%m-%d}"


def trains_per_slot(timetable: pd.DataFrame, extra_key: Sequence[str] = ()) -> pd.DataFrame:
    """(station_no, direction, day_type, time_slot_30min)별 서로 다른 train_id 수.

    `disaggregate.allocate_to_trains`와 정확히 같은 슬롯 배정(`to_minutes` → 30분 내림 →
    `minutes_to_slot30`)을 써야 두 표에서 같은 열차가 같은 슬롯으로 떨어진다 — 규칙이 어긋나면
    `onboard_30min_est`(평균 혼잡도 × 정원 × 열차 수)의 분모가 틀어진다.

    `extra_key`(239): 그룹 키에 더할 컬럼(예: `assign_links`가 붙인 `link_id`) — 강동처럼 한
    역이 여러 세그먼트에 걸칠 때 링크마다 열차 수를 따로 세야 `onboard_30min_est`가 그 링크를
    실제로 지나는 열차 수를 쓴다(135 버그, `disaggregate.allocate_to_trains`의 `extra_key`와
    짝이다).
    """
    tt = timetable.copy()
    arr_min = to_minutes(tt["arrival_time"])
    slot_start = (arr_min // SLOT_MINUTES) * SLOT_MINUTES
    tt["time_slot_30min"] = slot_start.map(minutes_to_slot30)
    key = ["station_no", "direction", "day_type", *extra_key, "time_slot_30min"]
    return tt.groupby(key, observed=True)["train_id"].nunique().rename("n_trains").reset_index()


def assign_links(trajectory: pd.DataFrame, link_segments: dict[str, list[int]]) -> pd.DataFrame:
    """열차 궤적(`disaggregate.train_trajectory` 출력)의 각 정차에 실제 링크를 배정한다(239).

    입력에는 `station_no, prev_station_no, next_station_no`가 있어야 한다. 반환은 입력 컬럼
    그대로에 `link_id`(str, 후보가 전혀 없으면 NaN)와 `link_ambiguous`(bool)를 더한 프레임이다.

    역마다 후보 = `station_no`를 포함하는 세그먼트들(`link_segments`의 키, 값은 역 순서 목록).
    후보가 하나면 그대로 쓴다. 여럿이면(강동처럼 세그먼트가 겹치는 역) 그 열차가 실제로 지나온·
    갈 방향으로 좁힌다 — 다음 역이 있으면 (station_no, next_station_no)가 인접한 세그먼트,
    없으면(종점) 직전 역이 있을 때 (prev_station_no, station_no)가 인접한 세그먼트. 그 결과가
    정확히 하나면 그것으로 정하고 `link_ambiguous=False`다. 그래도 안 정해지거나(0개·2개 이상)
    prev·next가 둘 다 없으면(런이 한 행뿐인 퇴화 케이스) `link_segments` 등록 순서에서 역이
    세그먼트의 첫/끝(종점 링크)인 첫 후보를 고르고, 없으면 등록 순서상 첫 후보를 고른 뒤
    `link_ambiguous=True`로 표시한다(숨기지 않는다, 원칙 8). 후보가 아예 없는 역은
    `link_id=NaN, link_ambiguous=True`.

    다중 후보(교차점) 역만 행 단위로 순회하고, 후보가 하나뿐인 대다수 역은 벡터화해 처리한다.
    """
    out = trajectory.reset_index(drop=True).copy()

    # station_no → 그 역을 포함하는 세그먼트 이름 목록(link_segments 등록 순서 보존).
    station_candidates: dict[int, list[str]] = {}
    for name, stations in link_segments.items():
        for s in dict.fromkeys(int(x) for x in stations):  # 세그먼트 안 중복 역 제거·순서 보존
            station_candidates.setdefault(s, []).append(name)

    counts = out["station_no"].map(lambda s: len(station_candidates.get(s, [])))
    single_link = {s: names[0] for s, names in station_candidates.items() if len(names) == 1}

    link_id = out["station_no"].map(single_link).astype(object)
    link_ambiguous = np.zeros(len(out), dtype=bool)
    link_ambiguous[counts.to_numpy() == 0] = True  # 후보 없음 — link_id는 NaN 그대로

    multi_mask = (counts > 1).to_numpy()
    if multi_mask.any():
        station_arr = out.loc[multi_mask, "station_no"].to_numpy()
        next_arr = out.loc[multi_mask, "next_station_no"].to_numpy()
        prev_arr = out.loc[multi_mask, "prev_station_no"].to_numpy()
        resolved_id = np.empty(len(station_arr), dtype=object)
        resolved_amb = np.zeros(len(station_arr), dtype=bool)

        for i, station_no in enumerate(station_arr):
            candidates = station_candidates[station_no]
            nxt, prv = next_arr[i], prev_arr[i]
            matches: list[str] = []
            if pd.notna(nxt):
                matches = [
                    c for c in candidates if segment_has_adjacent(link_segments[c], station_no, nxt)
                ]
            elif pd.notna(prv):
                matches = [
                    c for c in candidates if segment_has_adjacent(link_segments[c], prv, station_no)
                ]
            if len(matches) == 1:
                resolved_id[i] = matches[0]
                continue
            terminal = [c for c in candidates if segment_is_terminal(link_segments[c], station_no)]
            resolved_id[i] = terminal[0] if terminal else candidates[0]
            resolved_amb[i] = True

        link_id_arr = link_id.to_numpy().copy()
        link_id_arr[multi_mask] = resolved_id
        link_id = pd.Series(link_id_arr, index=out.index)
        link_ambiguous[multi_mask] = resolved_amb

    out["link_id"] = link_id
    out["link_ambiguous"] = link_ambiguous
    return out


def segment_links(segments: list[dict]) -> tuple[set[tuple[int, int]], dict[str, list[int]]]:
    """해석된 세그먼트(`topology.resolve_segments`) → (역 인접 쌍 집합, `line/segment` → 역 순서).

    `adjacency`는 각 세그먼트의 연속한 역 쌍을 양방향으로 담고, `circular: true`인 세그먼트는
    마지막 역 → 첫 역 wrap-around 쌍도 더한다. `link_segments`는 "본선"처럼 세그먼트 이름이
    호선 간 겹치는 경우를 구분하려고 `line/segment`를 키로 쓴다(강동처럼 한 역이 여러 세그먼트에
    걸치는 중복 해소에 `node_states`가 그대로 쓴다, `RESOLUTION_LADDER.md` §3 L5).
    """
    adjacency: set[tuple[int, int]] = set()
    link_segments: dict[str, list[int]] = {}
    for seg in segments:
        stations = [int(s) for s in seg["stations"]]
        link_segments[f"{seg['line']}/{seg['segment']}"] = stations
        for i in range(len(stations) - 1):
            a, b = stations[i], stations[i + 1]
            adjacency.add((a, b))
            adjacency.add((b, a))
        if seg.get("circular") and len(stations) > 1:
            a, b = stations[-1], stations[0]
            adjacency.add((a, b))
            adjacency.add((b, a))
    return adjacency, link_segments


def segment_pairs(segments: list[dict]) -> set[tuple[int, int]]:
    """같은 세그먼트에 속한 모든 역 쌍(양방향) — `node_states`의 `adjacency` 인자로 넘기는 "이어붙임 허용" 집합.

    `segment_links`의 연속 인접 쌍만 쓰면 급행(1호선)이나 시각표에 정차 행이 빠진 열차(6·8호선에서
    실측 1,171행/일)처럼 **한 세그먼트 안에서 역을 건너뛴** 궤적이 전부 `gap`으로 끊겨 도착 재차가
    NaN이 된다. 열차는 건너뛴 역을 지나도 사람을 그대로 싣고 가므로 같은 세그먼트 안이면
    이어붙이는 것이 맞다(239). 세그먼트를 벗어나는 건너뜀(분기점을 거치지 않고 다른 세그먼트로
    넘어감 — 시각표 결함)만 `gap`으로 남는다.
    """
    pairs: set[tuple[int, int]] = set()
    for seg in segments:
        stations = [int(s) for s in seg["stations"]]
        for a in stations:
            for b in stations:
                if a != b:
                    pairs.add((a, b))
    return pairs
