import pandas as pd

from DATA_ENGINE.eda.diagnose_transfer_leakage import (
    compare_ratio_dispersion,
    load_transfer_pairs,
    transfer_station_numbers,
)


def test_load_transfer_pairs_drops_non_numeric_korail_codes(tmp_path):
    """ "100C" 같은 코레일 구간 코드는 우리 station_no 체계 밖이라 걸러져야 한다."""
    csv_path = tmp_path / "transfer.csv"
    csv_path.write_text(
        "고유번호,환승시작역,환승시작 코드,환승시작 호선,하차 열차 방면,하차위치(호차),"
        "하차위치(문),환승종료역,환승 열차 방면,환승 승차위치(호차),환승 승차위치(문),소요시간\n"
        "1,서울역,150,1,시청 방면,10,4,427,숙대입구 방면,1,1,03:34\n"
        "2,용산,100C,경의선,왕십리 방면,1,1,150,서울역 방면,1,1,05:00\n",
        encoding="utf-8-sig",
    )

    result = load_transfer_pairs(csv_path)

    assert len(result) == 1
    assert result.iloc[0]["환승시작_station_no"] == 150
    assert result.iloc[0]["환승종료_station_no"] == 427


def test_load_transfer_pairs_drops_duplicate_relations(tmp_path):
    """같은 (역, station_no 쌍)이 문·호차 조합만 다르게 여러 행 있으면 관계 하나로 합친다."""
    csv_path = tmp_path / "transfer.csv"
    csv_path.write_text(
        "고유번호,환승시작역,환승시작 코드,환승시작 호선,하차 열차 방면,하차위치(호차),"
        "하차위치(문),환승종료역,환승 열차 방면,환승 승차위치(호차),환승 승차위치(문),소요시간\n"
        "1,서울역,150,1,시청 방면,10,4,427,숙대입구 방면,1,1,03:34\n"
        "2,서울역,150,1,남영 방면,1,2,427,숙대입구 방면,1,1,03:40\n",
        encoding="utf-8-sig",
    )

    result = load_transfer_pairs(csv_path)

    assert len(result) == 1


def test_transfer_station_numbers_includes_both_directions():
    """시작역·종료역 양쪽 다 station_no 집합에 들어가야 한다 — 방향을 안 가린다."""
    pairs = pd.DataFrame(
        {
            "환승시작_station_no": [150, 201],
            "환승종료_station_no": [427, 243],
        }
    )

    result = transfer_station_numbers(pairs, available={150, 427, 201, 999})

    assert result == {150, 427, 201}  # 243은 available 밖이라 빠진다


def test_compare_ratio_dispersion_flags_wider_spread_at_transfer_stations():
    """환승역 쪽 IQR/중앙값이 더 크면 그대로 더 크게 나와야 한다(단순 산출 검증)."""
    rows = []
    for station_no, ratios in [(150, [0.1, 0.1, 0.1, 0.1]), (999, [0.05, 0.1, 0.15, 0.5])]:
        for r in ratios:
            rows.append({"line": "1호선", "station_no": station_no, "ratio": r})
    calibration = pd.DataFrame(rows)

    result = compare_ratio_dispersion(calibration, transfer_stations={999})
    result = result.set_index("is_transfer")

    assert result.loc[False, "IQR_중앙값비"] == 0.0  # 전부 같은 값이라 산포 없음
    assert result.loc[True, "IQR_중앙값비"] > 0.0


def test_compare_ratio_dispersion_drops_missing_ratio_rows():
    calibration = pd.DataFrame(
        {
            "line": ["1호선", "1호선"],
            "station_no": [150, 150],
            "ratio": [0.1, None],
        }
    )

    result = compare_ratio_dispersion(calibration, transfer_stations=set())

    assert result["n"].iloc[0] == 1
