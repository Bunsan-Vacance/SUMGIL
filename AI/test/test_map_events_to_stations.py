import numpy as np
import pandas as pd

from DATA_ENGINE.eda.map_events_to_stations import haversine_km, nearest_stations


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
