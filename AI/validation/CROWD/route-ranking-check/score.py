"""경로 후보를 세 해상도(정적 lookup 표 · 30분 모델 표 · 노드×열차 표)로 채점한다.

`graph.schedule_path`가 만든 leg 목록(`node_times` 포함)을 입력으로 받아, 그 시각에 해당하는
혼잡도 표 값을 조회한다. 두 슬롯 표 채점(`score_slot_table`)은 링크(구간) 단위, 열차 표
채점(`score_train_table`)은 `RESOLUTION_LADDER.md` §1.2 "경로에 적용하는 규칙" 그대로 노드
단위다 — 탑승·경유 노드는 `load_dep_est`, leg의 마지막(하차/환승) 노드는 `load_arr_est`.
결측은 채우지 않는다(원칙 8) — 값이 없으면 NaN이고 `coverage`로 비율만 낸다.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app.CROWD.pipeline.disaggregate import SLOT_MINUTES, minutes_to_slot30, to_minutes


def slot_of(minute) -> str:
    """분 → 30분 슬롯 라벨('05:30'…'00:30'). 1440분 이상(자정 이후)은 `minutes_to_slot30`이
    운행일 기준으로 접는다(`app.CROWD.pipeline.disaggregate.allocate_to_trains`와 같은 규칙)."""
    floored = (int(minute) // SLOT_MINUTES) * SLOT_MINUTES
    return minutes_to_slot30(floored)


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    total_weight = float(weights.sum())
    if total_weight <= 0:
        return float(np.mean(values)) if values.size else float("nan")
    return float(np.average(values, weights=weights))


def score_slot_table(legs: list[dict], slot_table_for_date: pd.DataFrame) -> dict:
    """승차 leg의 각 링크(`stations[i] → stations[i+1]`)에 슬롯 표 `congestion_pct`를 붙인다.

    조회 키는 `(station_no=stations[i], direction=leg["direction"],
    time_slot_30min=slot_of(node_times[i]))`다. 키에 걸리는 행이 여럿이면(강동처럼 세그먼트가
    겹치는 역) 값이 큰 쪽을 쓰고 `duplicate_keys`에 몇 번 그랬는지 남긴다. 행이 아예 없거나
    값이 NaN이면 그 링크는 결측으로 센다.

    반환: `mean_tw`(결측 아닌 링크의 시간 가중 평균, 가중치=링크 소요분), `max`(결측 아닌 링크
    중 최댓값), `coverage`(결측 아닌 링크 / 전체 링크), `n_links`, `missing`, `duplicate_keys`.
    `coverage == 0`이면 `mean_tw`·`max`는 NaN이다.
    """
    values: list[float] = []
    weights: list[float] = []
    duplicate_keys = 0
    for leg in legs:
        if leg.get("kind") != "ride":
            continue
        stations = leg["stations"]
        node_times = leg["node_times"]
        direction = leg["direction"]
        for i in range(len(stations) - 1):
            slot = slot_of(node_times[i])
            match = slot_table_for_date[
                (slot_table_for_date["station_no"] == stations[i])
                & (slot_table_for_date["direction"] == direction)
                & (slot_table_for_date["time_slot_30min"] == slot)
            ]
            if len(match) == 0:
                value = float("nan")
            else:
                if len(match) > 1:
                    duplicate_keys += 1
                value = float(match["congestion_pct"].max())
            values.append(value)
            weights.append(node_times[i + 1] - node_times[i])

    return _finalize_score(values, weights, extra={"duplicate_keys": duplicate_keys})


def score_train_table(
    legs: list[dict], train_table_for_date: pd.DataFrame, *, board_buffer_min: float = 0.0
) -> dict:
    """승차 leg를 노드 단위(탑승·경유 = `load_dep_est`, leg 마지막 = `load_arr_est`)로 채점한다.

    탑승역에서 `pass_time`(분, `to_minutes`로 접은 값) ≥ `node_times[0] + board_buffer_min`인
    첫 열차를 고르고(`(station_no, direction)` 매칭), 이후 leg 안에서는 같은
    `(line, train_id, run_id)`를 따라간다. 열차를 못 찾으면 leg 전체가 NaN, 열차는 있어도
    특정 역에 그 열차 행이 없으면 그 노드만 NaN이다(원칙 8 — 채우지 않는다). 가중치는 각
    노드에 인접한 링크의 소요분이다.

    반환은 `score_slot_table`과 같은 키(`mean_tw`·`max`·`coverage`·`n_links`·`missing`) +
    `trains`(leg마다 고른 `train_id`, 못 골랐으면 `None`).
    """
    values: list[float] = []
    weights: list[float] = []
    trains: list = []
    for leg in legs:
        if leg.get("kind") != "ride":
            continue
        stations = leg["stations"]
        node_times = leg["node_times"]
        direction = leg["direction"]
        line = leg["line"]
        n = len(stations)
        board_time = node_times[0] + board_buffer_min

        cand = train_table_for_date[
            (train_table_for_date["station_no"] == stations[0])
            & (train_table_for_date["direction"] == direction)
        ].copy()
        if not cand.empty:
            cand["_pass_min"] = to_minutes(cand["pass_time"])
            cand = cand[cand["_pass_min"] >= board_time].sort_values("_pass_min")

        if cand.empty:
            trains.append(None)
            for i in range(n - 1):
                values.append(float("nan"))
                weights.append(node_times[i + 1] - node_times[i])
            values.append(float("nan"))
            weights.append(node_times[-1] - node_times[-2] if n > 1 else 1.0)
            continue

        chosen = cand.iloc[0]
        train_id, run_id = chosen["train_id"], chosen["run_id"]
        trains.append(train_id)
        run_rows = train_table_for_date[
            (train_table_for_date["line"] == line)
            & (train_table_for_date["train_id"] == train_id)
            & (train_table_for_date["run_id"] == run_id)
        ].copy()
        # 2호선 순환처럼 한 런이 같은 역을 두 번 지나면 station_no가 중복된다 — 탑승 시각 이후
        # 첫 통과만 남겨 역당 한 행으로 만든다(사용자가 탄 뒤 처음 만나는 그 역).
        run_rows["_pass_min"] = to_minutes(run_rows["pass_time"])
        by_station = (
            run_rows[run_rows["_pass_min"] >= board_time]
            .sort_values("_pass_min", kind="mergesort")
            .drop_duplicates("station_no", keep="first")
            .set_index("station_no")
        )

        for i in range(n - 1):
            st = stations[i]
            weights.append(node_times[i + 1] - node_times[i])
            if st in by_station.index:
                v = by_station.loc[st, "load_dep_est"]
                values.append(float(v) if pd.notna(v) else float("nan"))
            else:
                values.append(float("nan"))

        last_st = stations[-1]
        weights.append(node_times[-1] - node_times[-2] if n > 1 else 1.0)
        if last_st in by_station.index:
            v = by_station.loc[last_st, "load_arr_est"]
            values.append(float(v) if pd.notna(v) else float("nan"))
        else:
            values.append(float("nan"))

    return _finalize_score(values, weights, extra={"trains": trains})


def _finalize_score(values: list[float], weights: list[float], extra: dict) -> dict:
    arr_values = np.asarray(values, dtype=float)
    arr_weights = np.asarray(weights, dtype=float)
    n_links = int(arr_values.size)
    known = ~np.isnan(arr_values)
    missing = int((~known).sum())
    coverage = float(known.sum() / n_links) if n_links else float("nan")
    if known.any():
        mean_tw = _weighted_mean(arr_values[known], arr_weights[known])
        max_val = float(np.max(arr_values[known]))
    else:
        mean_tw = float("nan")
        max_val = float("nan")
    return {
        "mean_tw": mean_tw,
        "max": max_val,
        "coverage": coverage,
        "n_links": n_links,
        "missing": missing,
        **extra,
    }


def rank(
    candidates_scores: list[dict], key: str = "mean_tw", min_coverage: float = 0.5
) -> list[int]:
    """`candidates_scores`의 인덱스를 `key` 오름차순으로 정렬한다(값이 작을수록 좋음, 즉 덜 붐빔).

    `coverage < min_coverage`이거나 `key` 값이 NaN인 후보는 비교 불가로 보고 뒤로 보낸다 —
    각 dict에 `comparable`(bool)을 제자리에서 채워 넣는다(부수효과, 반환값은 인덱스 목록뿐).
    """
    comparable_flags: list[bool] = []
    for d in candidates_scores:
        value = d.get(key)
        is_nan = value is None or (isinstance(value, float) and math.isnan(value))
        ok = (d.get("coverage", 0.0) >= min_coverage) and not is_nan
        d["comparable"] = ok
        comparable_flags.append(ok)

    idx = list(range(len(candidates_scores)))

    def sort_key(i: int) -> tuple[int, float]:
        if comparable_flags[i]:
            return (0, candidates_scores[i][key])
        return (1, 0.0)

    idx.sort(key=sort_key)
    return idx
