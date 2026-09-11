"""DATA_ENGINE/eda/parsers_timetable.py — 합성 CSV로 컬럼·요일·역 매핑·궤적 기반 방향 추론."""

from __future__ import annotations

import pandas as pd
import pytest

from DATA_ENGINE.eda import parsers_timetable as pt

STATIONS = pd.DataFrame(
    {
        "station_no": [150, 151, 152, 201, 202, 243],
        "station_name": ["서울역", "시청", "종각", "시청", "을지로입구", "충정로"],
        "line": ["1호선", "1호선", "1호선", "2호선", "2호선", "2호선"],
    }
)
COLS = [
    "고유번호",
    "호선",
    "역사코드",
    "역사명",
    "주중주말",
    "방향",
    "급행여부",
    "열차코드",
    "열차도착시간",
    "열차출발시간",
    "출발역",
    "도착역",
]


def _csv(tmp_path, rows):
    path = tmp_path / "timetable.csv"
    pd.DataFrame(rows, columns=COLS).to_csv(path, index=False, encoding="cp949")
    return path


def _train(line, code, day, train, stops):
    """stops: [(역사코드, 역명, 도착, 출발)]. 첫 정거장은 도착 없음(출발역)."""
    rows = []
    for i, (sc, name, arr, dep) in enumerate(stops):
        rows.append(
            [
                i,
                line,
                sc,
                name,
                day,
                code,
                "0",
                train,
                None if i == 0 else arr,
                dep,
                stops[0][1],
                stops[-1][1],
            ]
        )
    return rows


@pytest.fixture
def small_topology(monkeypatch):
    def fake_load_topology(path=None):
        return [
            {"line": "1호선", "segment": "본선", "stations": [150, 151, 152]},
            {"line": "2호선", "segment": "본선", "circular": True, "stations": [201, 202, 243]},
        ]

    monkeypatch.setattr(pt, "load_topology", fake_load_topology)


def test_direction_inferred_from_trajectory_not_code(tmp_path, small_topology):
    rows = []
    # 1호선 "UP"이 역번호 증가 방향(서울역→종각) → 우리 하선
    rows += _train(
        "1",
        "UP",
        "DAY",
        "K1",
        [
            ("0150", "서울역", None, "05:20:00"),
            ("0151", "시청", "05:22:00", "05:22:30"),
            ("0152", "종각", "05:24:00", "05:24:30"),
        ],
    )
    rows += _train(
        "1",
        "UP",
        "DAY",
        "K3",
        [
            ("0150", "서울역", None, "05:30:00"),
            ("0151", "시청", "05:32:00", "05:32:30"),
            ("0152", "종각", "05:34:00", "05:34:30"),
        ],
    )
    # 1호선 "DOWN"은 감소 → 상선
    rows += _train(
        "1",
        "DOWN",
        "DAY",
        "K2",
        [
            ("0152", "종각", None, "05:21:00"),
            ("0151", "시청", "05:23:00", "05:23:30"),
            ("0150", "서울역", "05:25:00", "05:25:30"),
        ],
    )
    # 2호선 "IN"이 202→201→243 (감소, wrap 포함) → 외선
    rows += _train(
        "2",
        "IN",
        "DAY",
        "2013",
        [
            ("0202", "을지로입구", None, "05:30:00"),
            ("0201", "시청", "05:31:30", "05:32:00"),
            ("0243", "충정로", "05:33:30", "05:34:00"),
        ],
    )
    # 2호선 "OUT"이 243→201→202 (증가) → 내선
    rows += _train(
        "2",
        "OUT",
        "DAY",
        "2014",
        [
            ("0243", "충정로", None, "05:30:00"),
            ("0201", "시청", "05:31:30", "05:32:00"),
            ("0202", "을지로입구", "05:33:30", "05:34:00"),
        ],
    )
    # 미매핑 역(코레일)
    rows += _train(
        "1",
        "UP",
        "SAT",
        "K9",
        [
            ("1002", "구로", None, "05:00:00"),
            ("0150", "서울역", "05:20:00", "05:20:30"),
            ("0151", "시청", "05:22:00", "05:22:30"),
        ],
    )

    long, unmapped, dir_map = pt.build_timetable_long(_csv(tmp_path, rows), STATIONS)
    m = dir_map.set_index(["line", "direction_code"])["direction"]
    assert m[("1호선", "UP")] == "하선" and m[("1호선", "DOWN")] == "상선"
    assert m[("2호선", "IN")] == "외선" and m[("2호선", "OUT")] == "내선"
    assert (dir_map["agree_ratio"] == 1.0).all()
    assert list(unmapped["station_code"]) == ["1002"]
    # 출발역은 도착시간이 없어 출발시간이 pass_time
    first = long[(long["train_id"] == "K1") & (long["station_no"] == 150)].iloc[0]
    assert first["pass_time"] == "05:20:00"
    assert set(long["day_type"]) == {"평일", "토요일"}


def test_mixed_direction_within_code_raises(tmp_path, small_topology):
    rows = []
    rows += _train(
        "1",
        "UP",
        "DAY",
        "A",
        [("0150", "서울역", None, "05:20:00"), ("0151", "시청", "05:22:00", "05:22:30")],
    )
    rows += _train(
        "1",
        "UP",
        "DAY",
        "B",
        [("0151", "시청", None, "05:20:00"), ("0150", "서울역", "05:22:00", "05:22:30")],
    )
    with pytest.raises(ValueError):
        pt.build_timetable_long(_csv(tmp_path, rows), STATIONS)


def test_normalizers_and_holiday_mapping():
    assert list(pt.normalize_line(pd.Series(["2", "02", "9호선"]))) == ["2호선", "2호선", "9호선"]
    assert pt.day_type_to_timetable("휴일") == "일요일"
    assert pt.day_type_to_timetable("평일") == "평일"
