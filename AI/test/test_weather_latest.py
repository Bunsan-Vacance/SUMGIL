from __future__ import annotations

import pandas as pd

from DATA_ENGINE.stream.kafka_events import parse_kafka_event
from DATA_ENGINE.stream.weather_latest import latest_weather_path, update_weather_latest


def weather_event(
    *,
    event_id: str,
    base_time: str = "1000",
    forecast_time: str | None = None,
    nx: int = 60,
    value: str = "23",
):
    payload = {
        "baseDate": "20260918", "baseTime": base_time, "category": "T1H",
        "nx": nx, "ny": 127,
    }
    if forecast_time is None:
        payload["obsrValue"] = value
    else:
        payload.update(fcstDate="20260918", fcstTime=forecast_time, fcstValue=value)
    return parse_kafka_event(
        {
            "event_id": event_id,
            "source": "weather.nowcast",
            "entity_id": f"{nx}:127:T1H",
            "source_generated_at": f"2026-09-18T{base_time[:2]}:{base_time[2:]}:00+09:00",
            "ingested_at": "2026-09-18T10:55:00+09:00",
            "poll_run_at": "2026-09-18T10:54:00+09:00",
            "payload": payload,
        },
        topic="weather.nowcast",
    )


def test_update_weather_latest_preserves_grid_kind_and_forecast_horizons(tmp_path):
    events = [
        weather_event(event_id="observed", value="23"),
        weather_event(event_id="other-grid", nx=61, value="19"),
        weather_event(event_id="forecast-11", forecast_time="1100", value="24"),
        weather_event(event_id="forecast-12", forecast_time="1200", value="25"),
    ]

    path = update_weather_latest(events, ai_root=tmp_path)

    assert path == latest_weather_path(ai_root=tmp_path)
    frame = pd.read_parquet(path)
    assert len(frame) == 4
    assert set(frame["nx"]) == {60, 61}
    assert set(frame["weather_source"]) == {"observed", "forecast"}
    assert set(frame.loc[frame["weather_source"] == "forecast", "forecast_datetime"].dt.hour) == {
        11, 12,
    }


def test_update_weather_latest_ignores_older_observation(tmp_path):
    newer = weather_event(event_id="newer", base_time="1100", value="25")
    older = weather_event(event_id="older", base_time="1000", value="23")

    update_weather_latest([newer], ai_root=tmp_path)
    update_weather_latest([older], ai_root=tmp_path)

    frame = pd.read_parquet(latest_weather_path(ai_root=tmp_path))
    assert frame[["event_id", "weather_value"]].to_dict("records") == [
        {"event_id": "newer", "weather_value": "25"}
    ]


def test_update_weather_latest_replaces_old_forecast_issue(tmp_path):
    old = weather_event(event_id="old", base_time="1000", forecast_time="1200")
    new = weather_event(event_id="new", base_time="1100", forecast_time="1200")

    update_weather_latest([old], ai_root=tmp_path)
    update_weather_latest([new], ai_root=tmp_path)

    frame = pd.read_parquet(latest_weather_path(ai_root=tmp_path))
    assert frame["event_id"].tolist() == ["new"]


def test_update_weather_latest_skips_invalid_payload(tmp_path, caplog):
    event = weather_event(event_id="invalid")
    bad = parse_kafka_event(
        {
            "event_id": event.event_id,
            "source": event.source,
            "entity_id": event.entity_id,
            "source_generated_at": event.source_generated_at.isoformat(),
            "ingested_at": event.ingested_at.isoformat(),
            "poll_run_at": event.poll_run_at.isoformat(),
            "payload": {"category": "T1H"},
        },
        topic="weather.nowcast",
    )

    assert update_weather_latest([bad], ai_root=tmp_path) is None
    assert "Skipped 1 invalid Kafka weather events" in caplog.text
    assert not latest_weather_path(ai_root=tmp_path).exists()
