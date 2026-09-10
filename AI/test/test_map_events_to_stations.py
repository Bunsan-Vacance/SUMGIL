import numpy as np
import pandas as pd

from DATA_ENGINE.eda.map_events_to_stations import (
    SPIKE_MAX_DAYS,
    aggregate_festival_rows,
    haversine_km,
    nearest_stations,
)


def _stations():
    return pd.DataFrame(
        {
            "station_no": [218, 2620, 434],
            "station_name": ["종합운동장", "월드컵경기장", "남태령"],
            "line": ["2호선", "6호선", "4호선"],
            "lat": [37.5109, 37.5682, 37.4636],
            "lon": [127.0733, 126.8974, 126.9894],
        }
    )


def test_haversine_km_zero_for_same_point():
    assert (
        haversine_km(np.array([37.5]), np.array([127.0]), np.array([37.5]), np.array([127.0]))[0]
        == 0.0
    )


def test_haversine_km_matches_known_distance():
    """서울시청~강남역은 대략 8~9km다."""
    d = haversine_km(
        np.array([37.5663]), np.array([126.9779]), np.array([37.4979]), np.array([127.0276])
    )
    assert 8.0 < d[0] < 9.5


def test_nearest_stations_finds_expected_station_within_radius():
    venues = pd.DataFrame({"stadium": ["잠실"], "lat": [37.5121], "lon": [127.0719]})

    within, summary = nearest_stations(venues, _stations(), radius_km=1.5)

    assert summary.iloc[0]["최근접역"] == "종합운동장"
    assert summary.iloc[0]["반경내"]
    assert list(within["station_no"]) == [218]


def test_nearest_stations_reports_out_of_radius_without_linking():
    """반경 밖이어도 최근접 요약은 나오지만 연결 목록에는 안 들어간다."""
    venues = pd.DataFrame({"stadium": ["문학"], "lat": [37.4367], "lon": [126.6906]})

    within, summary = nearest_stations(venues, _stations(), radius_km=1.5)

    assert not summary.iloc[0]["반경내"]
    assert summary.iloc[0]["거리_km"] > 1.5
    assert within.empty


def test_nearest_stations_links_every_station_inside_radius():
    """반경 안에 역이 여럿이면 전부 연결된다 — 최근접 하나만 쓰지 않는다."""
    venues = pd.DataFrame({"stadium": ["가상"], "lat": [37.5109], "lon": [127.0733]})
    stations = _stations()

    within, _ = nearest_stations(venues, stations, radius_km=100.0)

    assert len(within) == 3


def _fest_events():
    """같은 역·날짜에 단기 축제 1건과 장기 기획전 1건이 겹친 상황."""
    return pd.DataFrame(
        {
            "festival_id": ["spike", "standing", "spike2"],
            "station_no": [218, 218, 2620],
            "date": pd.to_datetime(["2024-10-05", "2024-10-05", "2024-10-05"]),
            "duration_days": [1, 184, 3],
        }
    )


def test_aggregate_festival_rows_splits_count_by_duration():
    """단기·장기를 나눠 세지 않으면 상설 기획전이 단기 축제 신호를 덮는다."""
    rows = aggregate_festival_rows(_fest_events()).set_index("station_no")

    assert rows.loc[218, "festival_count"] == 2
    assert rows.loc[218, "festival_short_count"] == 1
    assert rows.loc[218, "festival_long_count"] == 1


def test_aggregate_festival_rows_keeps_short_and_long_summing_to_count():
    rows = aggregate_festival_rows(_fest_events())

    total = rows["festival_short_count"] + rows["festival_long_count"]
    assert (total == rows["festival_count"]).all()


def test_aggregate_festival_rows_takes_shortest_duration():
    """연속값은 그 날 가장 짧게 열리는 축제 기준 — 스파이크성이 가장 강한 쪽을 본다."""
    rows = aggregate_festival_rows(_fest_events()).set_index("station_no")

    assert rows.loc[218, "festival_min_duration_days"] == 1
    assert rows.loc[2620, "festival_min_duration_days"] == 3


def test_aggregate_festival_rows_treats_boundary_duration_as_short():
    """SPIKE_MAX_DAYS 경계값(3일)은 단기에 포함된다."""
    df = _fest_events().assign(duration_days=[SPIKE_MAX_DAYS, SPIKE_MAX_DAYS + 1, 1])

    rows = aggregate_festival_rows(df).set_index("station_no")

    assert rows.loc[218, "festival_short_count"] == 1
    assert rows.loc[218, "festival_long_count"] == 1
