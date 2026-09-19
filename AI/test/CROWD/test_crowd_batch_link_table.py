"""244 — 배치가 만드는 링크(from/to) 표(`predictions_link_*.parquet` + BE CSV)의 순수 로직 검증.

실제 데이터 파일 없이 순수 pandas + `congestion.py`의 실제 상수(`ASCENDING`·`DESCENDING`·
`CIRCULAR_LABELS`)로 세 가지 세그먼트 모양을 만들어 `to_link_table`을 부른다
(`test_crowd_batch_train_table.py`의 합성 데이터 형태를 참고했다 — 테스트 파일명이 리포 전체에서
유일해야 해서 픽스처는 가져오지 않고 패턴만 복제했다).

확인하는 것은 (1) 선형 세그먼트에서 경계(종점) 링크가 조인에서 자동으로 빠지는지, (2) 순환
세그먼트는 모든 역이 양방향 타깃을 가져 행이 하나도 빠지지 않는지, (3) 강동류 분기점에서 세그먼트
수만큼 서로 다른 `to_station_no`를 가진 별개 행이 나오고 `link_ambiguous` 컬럼 자체가 없는지,
(4) 배율표 결측(NaN) 행도 실제 이웃이 있으면 버려지지 않는지, (5) `write_link_csv`가 BE가 확정한
헤더·슬롯 인덱스·결측 표현으로 CSV를 쓰는지, (6) `validated_meta`가 새 메타 키 2개를 요구하는지,
(7) 9호선 2·3단계 행이 `pred_source`·`predictor_version` 양쪽에서 모델 행과 구분되는지다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.CROWD.pipeline.batch_predict import (
    LINE9_PRED_SOURCE,
    LINE9_PREDICTOR_VERSION,
    META_KEYS,
    _congestion_table_full,
    _slot30_to_index,
    to_link_table,
    validated_meta,
    write_link_csv,
)
from app.CROWD.pipeline.congestion import ASCENDING, CIRCULAR_LABELS, DESCENDING

# ── 1·4. 선형 세그먼트(분기 없음) — 159는 배율표에서 뺀다(no_calibration 케이스 겸용) ──
CAPACITY = {"car_capacity": 160, "cars_per_train": {"1호선": 10}}
STATIONS = [150, 151, 158, 159]
DATE = pd.Timestamp("2025-10-08")  # 수요일(평일)


def _predicted() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": DATE,
            "station_no": STATIONS,
            "station_name": ["서울역", "시청", "청량리", "왕십리"],
            "line": "1호선",
            "time_slot": "08-09",
            "day_type": "평일",
            "boarding": [300.0, 100.0, 80.0, 40.0],
            "alighting": [0.0, 100.0, 30.0, 20.0],
            "boarding_pred": [300.0, 100.0, 80.0, 40.0],
            "alighting_pred": [0.0, 100.0, 30.0, 20.0],
            "boarding_lookup": [280.0, 110.0, 75.0, 35.0],
            "alighting_lookup": [5.0, 90.0, 28.0, 12.0],
        }
    )


def _calibration() -> pd.DataFrame:
    """159는 일부러 뺀다 — 배율표 결측(`no_calibration`) 케이스를 만들기 위해서다."""
    rows = []
    for s in STATIONS:
        if s == 159:
            continue
        for d in ("하선", "상선"):
            for t in ("08:00", "08:30"):
                rows.append(
                    {
                        "station_no": s,
                        "direction": d,
                        "day_type": "평일",
                        "time_slot": t,
                        "ratio": 0.25,
                    }
                )
    return pd.DataFrame(rows)


def _segments() -> list[dict]:
    return [{"line": "1호선", "segment": "본선", "stations": STATIONS}]


@pytest.fixture
def full() -> pd.DataFrame:
    return _congestion_table_full(
        _predicted(), _segments(), CAPACITY, _calibration(), [50.0, 100.0]
    )


def test_linear_segment_targets_present_and_boundaries_absent(full):
    """4역 선형 구간 — 종점 링크(159 하선·150 상선)는 조인에서 자동으로 빠진다."""
    link_tbl, stats = to_link_table(full, _segments(), "lightgbm:test")
    got = {(row.from_station_no, row.direction, row.to_station_no) for row in link_tbl.itertuples()}
    assert (150, "하선", 151) in got
    assert (151, "하선", 158) in got
    assert (158, "하선", 159) in got
    assert not any(fr == 159 and d == "하선" for fr, d, _ in got)  # 마지막 역 — 다음 역 없음
    assert not any(fr == 150 and d == "상선" for fr, d, _ in got)  # 첫 역 — 이전 역 없음
    assert (151, "상선", 150) in got
    assert (158, "상선", 151) in got
    assert (159, "상선", 158) in got
    assert (link_tbl["predictor_version"] == "lightgbm:test").all()
    assert stats["link_rows"] == len(link_tbl)


def test_missing_calibration_row_kept_when_it_has_a_real_neighbor(full):
    """159 상선(→158)은 배율표 결측(NaN)이지만 실제 이웃이 있어 버려지지 않는다 — 경계와
    다르다."""
    link_tbl, _ = to_link_table(full, _segments(), "lightgbm:test")
    row = link_tbl[(link_tbl["from_station_no"] == 159) & (link_tbl["direction"] == "상선")]
    assert len(row) == 2  # 08:00·08:30 두 슬롯
    assert (row["to_station_no"] == 158).all()
    assert row["congestion_pct"].isna().all()
    assert (row["data_status"] == "no_calibration").all()


# ── 2. 순환 세그먼트(합성, 2호선-정확할 필요 없음) ──
CIRC_STATIONS = [901, 902, 903, 904]
CIRC_CAPACITY = {"car_capacity": 160, "cars_per_train": {"순환선": 8}}
CIRC_DATE = pd.Timestamp("2025-10-08")


def _circular_segments() -> list[dict]:
    return [{"line": "순환선", "segment": "본선", "stations": CIRC_STATIONS, "circular": True}]


def _circular_predicted() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": CIRC_DATE,
            "station_no": CIRC_STATIONS,
            "station_name": [f"역{s}" for s in CIRC_STATIONS],
            "line": "순환선",
            "time_slot": "08-09",
            "day_type": "평일",
            "boarding": [50.0, 40.0, 30.0, 20.0],
            "alighting": [20.0, 30.0, 40.0, 50.0],
            "boarding_pred": [50.0, 40.0, 30.0, 20.0],
            "alighting_pred": [20.0, 30.0, 40.0, 50.0],
            "boarding_lookup": [45.0, 38.0, 28.0, 18.0],
            "alighting_lookup": [18.0, 28.0, 38.0, 48.0],
        }
    )


def _circular_calibration() -> pd.DataFrame:
    rows = []
    for s in CIRC_STATIONS:
        for d in (CIRCULAR_LABELS[ASCENDING], CIRCULAR_LABELS[DESCENDING]):
            for t in ("08:00", "08:30"):
                rows.append(
                    {
                        "station_no": s,
                        "direction": d,
                        "day_type": "평일",
                        "time_slot": t,
                        "ratio": 0.25,
                    }
                )
    return pd.DataFrame(rows)


@pytest.fixture
def circular_full() -> pd.DataFrame:
    return _congestion_table_full(
        _circular_predicted(),
        _circular_segments(),
        CIRC_CAPACITY,
        _circular_calibration(),
        [50.0, 100.0],
    )


def test_circular_segment_every_station_has_both_targets_no_drops(circular_full):
    """순환 세그먼트는 경계가 없다 — 역마다 내선·외선 타깃이 다 있고(줄바꿈 쌍 포함), 행이
    하나도 안 빠진다."""
    link_tbl, stats = to_link_table(circular_full, _circular_segments(), "lightgbm:test")
    assert len(link_tbl) == len(circular_full)  # 경계가 없어 하나도 안 빠진다
    assert stats["boundary_dropped_keys"] == 0

    n = len(CIRC_STATIONS)
    asc_label, desc_label = CIRCULAR_LABELS[ASCENDING], CIRCULAR_LABELS[DESCENDING]
    for i, s in enumerate(CIRC_STATIONS):
        asc_to = CIRC_STATIONS[(i + 1) % n]
        desc_to = CIRC_STATIONS[(i - 1) % n]
        asc_rows = link_tbl[
            (link_tbl["from_station_no"] == s) & (link_tbl["direction"] == asc_label)
        ]
        desc_rows = link_tbl[
            (link_tbl["from_station_no"] == s) & (link_tbl["direction"] == desc_label)
        ]
        assert (asc_rows["to_station_no"] == asc_to).all() and len(asc_rows) > 0
        assert (desc_rows["to_station_no"] == desc_to).all() and len(desc_rows) > 0
    # 줄바꿈 쌍(마지막 역 ↔ 첫 역)도 포함돼 있다.
    assert (CIRC_STATIONS[-1], asc_label, CIRC_STATIONS[0]) in {
        (row.from_station_no, row.direction, row.to_station_no) for row in link_tbl.itertuples()
    }
    assert (CIRC_STATIONS[0], desc_label, CIRC_STATIONS[-1]) in {
        (row.from_station_no, row.direction, row.to_station_no) for row in link_tbl.itertuples()
    }


# ── 3. 분기점(강동류) — 본선[1,2,3] → 지선A[3,4,5]·지선B[3,6,7] ──
JUNCTION_STATIONS = [1, 2, 3, 4, 5, 6, 7]
JUNCTION_DATE = pd.Timestamp("2025-10-08")
JUNCTION_CAPACITY = {"car_capacity": 160, "cars_per_train": {"5호선": 10}}


def _junction_segments() -> list[dict]:
    return [
        {"line": "5호선", "segment": "본선", "stations": [1, 2, 3]},
        {"line": "5호선", "segment": "지선A", "stations": [3, 4, 5]},
        {"line": "5호선", "segment": "지선B", "stations": [3, 6, 7]},
    ]


def _junction_predicted() -> pd.DataFrame:
    n = len(JUNCTION_STATIONS)
    return pd.DataFrame(
        {
            "date": JUNCTION_DATE,
            "station_no": JUNCTION_STATIONS,
            "station_name": [f"역{s}" for s in JUNCTION_STATIONS],
            "line": "5호선",
            "time_slot": "08-09",
            "day_type": "평일",
            "boarding": [100.0] * n,
            "alighting": [0.0] * n,
            "boarding_pred": [100.0] * n,
            "alighting_pred": [0.0] * n,
            "boarding_lookup": [90.0] * n,
            "alighting_lookup": [5.0] * n,
        }
    )


def _junction_calibration() -> pd.DataFrame:
    rows = []
    for s in JUNCTION_STATIONS:
        for d in ("하선", "상선"):
            for t in ("08:00", "08:30"):
                rows.append(
                    {
                        "station_no": s,
                        "direction": d,
                        "day_type": "평일",
                        "time_slot": t,
                        "ratio": 0.25,
                    }
                )
    return pd.DataFrame(rows)


@pytest.fixture
def junction_full() -> pd.DataFrame:
    return _congestion_table_full(
        _junction_predicted(),
        _junction_segments(),
        JUNCTION_CAPACITY,
        _junction_calibration(),
        [50.0, 100.0],
    )


def test_junction_station_gets_one_row_per_branch_no_ambiguous_column(junction_full):
    """강동류 분기역(3)은 세그먼트마다(본선·지선A·지선B) 독립적으로 조회돼 서로 다른
    `to_station_no`를 가진 별개 행이 된다 — 모호성 플래그 없이도 중복 키 문제가 풀린다."""
    link_tbl, _ = to_link_table(junction_full, _junction_segments(), "lightgbm:test")
    assert "link_ambiguous" not in link_tbl.columns

    at_3 = link_tbl[(link_tbl["from_station_no"] == 3) & (link_tbl["time_slot_30min"] == "08:00")]
    assert len(at_3) == 3
    down = at_3[at_3["direction"] == "하선"]
    up = at_3[at_3["direction"] == "상선"]
    assert set(down["to_station_no"]) == {4, 6}
    assert len(down) == 2
    assert set(up["to_station_no"]) == {2}
    assert len(up) == 1


# ── 5. write_link_csv ──


def test_write_link_csv_header_slot_index_and_nan_handling(tmp_path):
    link_table = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-10-08"] * 4),
            "line": ["1호선"] * 4,
            "from_station_no": [150, 150, 150, 150],
            "to_station_no": [151, 151, 151, 151],
            "direction": ["하선"] * 4,
            "time_slot_30min": ["00:00", "00:30", "08:30", "23:30"],
            "congestion_pct": [12.3, np.nan, 45.6, 78.9],
            "data_status": ["ok", "no_calibration", "ok", "ok"],
            "pred_source": ["model"] * 4,
            "predictor_version": ["lightgbm:test"] * 4,
        }
    )
    path = tmp_path / "predictions_link_2025-10-08_120000.csv"
    rows_written = write_link_csv(link_table, path)
    assert rows_written == 4

    result = pd.read_csv(path)
    assert list(result.columns) == [
        "pred_date",
        "line",
        "from_station_no",
        "to_station_no",
        "direction",
        "time_slot",
        "level",
        "data_status",
        "pred_source",
        "predictor_version",
    ]
    assert result["time_slot"].tolist() == [0, 1, 17, 47]
    assert (result["pred_date"] == "2025-10-08").all()
    assert result.loc[0, "level"] == pytest.approx(12.3)
    assert result.loc[result["data_status"] == "no_calibration", "level"].isna().all()
    assert result["level"].isna().sum() == 1


@pytest.mark.parametrize(
    ("slot30", "expected"),
    [("00:00", 0), ("00:30", 1), ("08:30", 17), ("23:30", 47)],
)
def test_slot30_to_index_matches_be_formula(slot30, expected):
    """`disaggregate.slot30_start_minutes`(운행일 정렬용, hh<4에 1440을 더함)와 달리 여기는
    BE가 기대하는 0~47 인덱스를 직접 계산한다."""
    assert _slot30_to_index(slot30) == expected


# ── 6. validated_meta ──


def _full_meta() -> dict:
    return dict.fromkeys(META_KEYS)


def test_validated_meta_accepts_link_table_keys_and_rejects_missing_one():
    meta = _full_meta()
    assert validated_meta(meta) == meta  # 값이 전부 None이어도 키만 맞으면 통과한다

    missing = dict(meta)
    del missing["link_csv_rows"]
    with pytest.raises(RuntimeError):
        validated_meta(missing)

    missing_other = dict(meta)
    del missing_other["link_table"]
    with pytest.raises(RuntimeError):
        validated_meta(missing_other)


# ── 7. 9호선 2·3단계 — lookup 전용 행의 출처 표시 ──
# 역 목록을 **역번호 내림차순**으로 둔다: `line_topology.yaml`의 9호선이 그렇게 돼 있어서
# "리스트상 다음"(= ASCENDING = 하선)이 역번호 감소 방향이 된다. 실측 산출물에서
# 종합운동장(4130) → 봉은사(4129)가 하선으로 나오는 것과 같은 배치다.
LINE9_STATIONS = [4130, 4129, 4128]
LINE9_CAPACITY = {"car_capacity": 160, "cars_per_train": {"9호선": 6}}


def _line9_segments() -> list[dict]:
    return [{"line": "9호선", "segment": "2·3단계", "stations": LINE9_STATIONS}]


def _line9_predicted() -> pd.DataFrame:
    """`alighting_pred`에 음수를 하나 심는다 — 음수 대체(`lookup_negative`)와 9호선 표시가
    부딪칠 때 9호선 쪽이 이겨야 한다(둘 다 lookup이지만 출처가 다르다)."""
    return pd.DataFrame(
        {
            "date": DATE,
            "station_no": LINE9_STATIONS,
            "station_name": ["종합운동장", "봉은사", "삼성중앙"],
            "line": "9호선",
            "time_slot": "08-09",
            "day_type": "평일",
            "boarding": [200.0, 120.0, 90.0],
            "alighting": [10.0, 80.0, 60.0],
            "boarding_pred": [200.0, 120.0, 90.0],
            "alighting_pred": [10.0, -5.0, 60.0],
            "boarding_lookup": [190.0, 115.0, 85.0],
            "alighting_lookup": [12.0, 75.0, 55.0],
        }
    )


def _line9_calibration() -> pd.DataFrame:
    rows = []
    for s in LINE9_STATIONS:
        for d in (ASCENDING, DESCENDING):
            for slot in ("08:00", "08:30"):
                rows.append(
                    {
                        "station_no": s,
                        "direction": d,
                        "day_type": "평일",
                        "time_slot": slot,
                        "ratio": 0.3,
                    }
                )
    return pd.DataFrame(rows)


@pytest.fixture
def line9_full() -> pd.DataFrame:
    return _congestion_table_full(
        _line9_predicted(), _line9_segments(), LINE9_CAPACITY, _line9_calibration(), [50.0, 100.0]
    )


def test_line9_rows_are_marked_lookup_line9_even_when_negative_substituted(line9_full):
    """9호선 행은 음수 대체 여부와 무관하게 전부 `lookup_line9`다 — 모델을 타지 않으니까."""
    assert (line9_full["pred_source"] == LINE9_PRED_SOURCE).all()
    assert "lookup_negative" not in set(line9_full["pred_source"])
    assert "model" not in set(line9_full["pred_source"])


def test_line9_link_rows_carry_lookup_version_not_model_artifact(line9_full):
    """링크 표의 `predictor_version`은 행 단위다 — 9호선 행에 모델 아티팩트 이름이 새면 안 된다."""
    link_tbl, _ = to_link_table(line9_full, _line9_segments(), "lightgbm:test")
    assert len(link_tbl)
    assert (link_tbl["predictor_version"] == LINE9_PREDICTOR_VERSION).all()
    assert "lightgbm:test" not in set(link_tbl["predictor_version"])
    # 내림차순 목록이라 "다음 역"이 역번호 감소 방향(하선)이다 — 실측 4130→4129 하선과 같다.
    got = {(r.from_station_no, r.direction, r.to_station_no) for r in link_tbl.itertuples()}
    assert (4130, ASCENDING, 4129) in got


def test_link_predictor_version_is_per_row_when_lines_are_mixed(full, line9_full):
    """1~8호선과 9호선이 한 표에 섞여도 각 행이 자기 출처를 갖는다(스칼라 브로드캐스트 아님)."""
    mixed = pd.concat([full, line9_full], ignore_index=True, sort=False)
    segments = _segments() + _line9_segments()
    link_tbl, _ = to_link_table(mixed, segments, "lightgbm:test")
    by_line = link_tbl.groupby("line")["predictor_version"].unique()
    assert list(by_line["1호선"]) == ["lightgbm:test"]
    assert list(by_line["9호선"]) == [LINE9_PREDICTOR_VERSION]
