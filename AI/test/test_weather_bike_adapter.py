from __future__ import annotations

import pandas as pd

from DATA_ENGINE.stream.kafka_events import parse_kafka_event
from DATA_ENGINE.stream.kafka_sink import write_events
from DATA_ENGINE.stream.weather_bike_adapter import bike_weather_path


def weather_event(
    category: str,
    value: str,
    *,
    base_time: str = "1000",
    nx: int = 60,
    forecast: bool = False,
):
    payload = {
        "baseDate": "20260918", "baseTime": base_time,
        "category": category, "nx": nx, "ny": 127,
    }
    if forecast:
        payload.update(fcstDate="20260918", fcstTime="1100", fcstValue=value)
    else:
        payload["obsrValue"] = value
    return parse_kafka_event(
        {
            "event_id": f"{category}-{base_time}-{nx}-{forecast}-{value}",
            "source": "weather.nowcast",
            "entity_id": f"{nx}:127:{category}",
            "source_generated_at": f"2026-09-18T{base_time[:2]}:{base_time[2:]}:00+09:00",
            "ingested_at": "2026-09-18T10:55:00+09:00",
            "poll_run_at": "2026-09-18T10:54:00+09:00",
            "payload": payload,
        },
        topic="weather.nowcast",
    )


def test_bike_weather_uses_complete_observation_not_forecast(tmp_path):
    paths = write_events(
        [
            weather_event("T1H", "22.5"),
            weather_event("RN1", "0.6"),
            weather_event("T1H", "99", forecast=True),
        ],
        ai_root=tmp_path,
    )

    path = bike_weather_path(ai_root=tmp_path)
    assert path in paths
    frame = pd.read_parquet(path)
    assert frame.to_dict("records") == [
        {"temp": 22.5, "is_rain": True, "updated_at": pd.Timestamp("2026-09-18 10:00:00")}
    ]


def test_bike_weather_keeps_previous_until_new_observation_is_complete(tmp_path):
    write_events(
        [weather_event("T1H", "22"), weather_event("RN1", "0")],
        ai_root=tmp_path,
    )
    path = bike_weather_path(ai_root=tmp_path)
    write_events([weather_event("T1H", "25", base_time="1100")], ai_root=tmp_path)

    frame = pd.read_parquet(path)
    assert frame.loc[0, "temp"] == 22
    assert frame.loc[0, "updated_at"] == pd.Timestamp("2026-09-18 10:00:00")

    write_events([weather_event("RN1", "강수없음", base_time="1100")], ai_root=tmp_path)
    frame = pd.read_parquet(path)
    assert frame.loc[0, "temp"] == 25
    assert not bool(frame.loc[0, "is_rain"])
    assert frame.loc[0, "updated_at"] == pd.Timestamp("2026-09-18 11:00:00")


def test_bike_weather_ignores_other_grid_and_invalid_observation(tmp_path):
    write_events(
        [weather_event("T1H", "21", nx=61), weather_event("RN1", "1", nx=61)],
        ai_root=tmp_path,
    )
    assert not bike_weather_path(ai_root=tmp_path).exists()

    write_events(
        [weather_event("T1H", "22"), weather_event("RN1", "unknown")],
        ai_root=tmp_path,
    )
    assert not bike_weather_path(ai_root=tmp_path).exists()


def test_bike_weather_does_not_regress_for_late_old_events(tmp_path):
    write_events(
        [weather_event("T1H", "25", base_time="1100"),
         weather_event("RN1", "1", base_time="1100")],
        ai_root=tmp_path,
    )
    write_events(
        [weather_event("T1H", "20"), weather_event("RN1", "0")],
        ai_root=tmp_path,
    )

    frame = pd.read_parquet(bike_weather_path(ai_root=tmp_path))
    assert frame.loc[0, "temp"] == 25
    assert frame.loc[0, "updated_at"] == pd.Timestamp("2026-09-18 11:00:00")
