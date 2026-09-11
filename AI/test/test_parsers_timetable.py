"""DATA_ENGINE/eda/parsers_timetable.py — 합성 CSV로 컬럼·방향·요일·역 매핑."""

from __future__ import annotations

import pandas as pd
import pytest

from DATA_ENGINE.eda.parsers_timetable import (
    build_timetable_long,
    day_type_to_timetable,
    normalize_direction,
    normalize_line,
)

STATIONS = pd.DataFrame(
    {
        "station_no": [222, 223, 330],
        "station_name": ["강남", "교대", "교대"],
        "line": ["2호선", "2호선", "3호선"],
    }
)


def _csv(tmp_path, rows):
    cols = [
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
    frame = pd.DataFrame(rows, columns=cols)
    path = tmp_path / "timetable.csv"
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def test_parse_maps_by_code_then_by_name_and_reports_unmapped(tmp_path):
    path = _csv(
        tmp_path,
        [
            [
                1,
                "2",
                "222",
                "강남",
                "DAY",
                "내선",
                "N",
                "S1001",
                "08:02:00",
                "08:02:30",
                "성수",
                "성수",
            ],
            [
                2,
                "3",
                "9999",
                "교대",
                "SAT",
                "상행",
                "N",
                "S3001",
                "08:10:00",
                "08:10:30",
                "대화",
                "오금",
            ],
            [
                3,
                "2",
                "8888",
                "없는역",
                "END",
                "외선",
                "N",
                "S1002",
                "08:20:00",
                "08:20:30",
                "성수",
                "성수",
            ],
        ],
    )
    long, unmapped = build_timetable_long(path, STATIONS)
    assert list(long["station_no"]) == [222, 330]  # 코드 일치, (호선, 역명) 일치
    assert list(long["direction"]) == [
        "내선",
        "상선",
    ]
    assert list(long["day_type"]) == ["평일", "토요일"]
    assert len(unmapped) == 1 and unmapped.iloc[0]["station_name"] == "없는역"


def test_normalizers_and_holiday_mapping():
    assert list(normalize_line(pd.Series(["2", "02", "9호선"]))) == ["2호선", "2호선", "9호선"]
    assert list(normalize_direction(pd.Series(["하행", "외선순환"]))) == ["하선", "외선"]
    with pytest.raises(ValueError):
        normalize_direction(pd.Series(["순환"]))
    assert day_type_to_timetable("휴일") == "일요일"
    assert day_type_to_timetable("평일") == "평일"
