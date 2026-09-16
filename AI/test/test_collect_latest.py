from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from DATA_ENGINE.collect import bike_realtime, weather_nowcast


def test_bike_run_once_writes_snapshot_and_latest(tmp_path, monkeypatch):
    collected_at = datetime(2026, 3, 5, 14, 30, tzinfo=ZoneInfo("Asia/Seoul"))
    df = pd.DataFrame(
        {
            "stationId": ["ST-1"],
            "parkingBikeTotCnt": [3],
            "collected_at": [collected_at],
            "source": ["direct_poll"],
        }
    )

    monkeypatch.setattr(bike_realtime, "BIKE_RAW", tmp_path / "BIKE" / "raw")
    monkeypatch.setattr(bike_realtime, "fetch_snapshot", lambda: df)

    bike_realtime.run_once()

    snapshot_paths = list((tmp_path / "BIKE" / "raw" / "realtime").glob("dt=*/hh=*/*.parquet"))
    latest_path = tmp_path / "BIKE" / "raw" / "realtime" / "latest.parquet"

    assert len(snapshot_paths) == 1
    assert latest_path.exists()
    assert pd.read_parquet(latest_path).equals(df)


def test_weather_run_once_writes_snapshot_and_latest(tmp_path, monkeypatch):
    collected_at = datetime(2026, 3, 5, 14, 30, tzinfo=ZoneInfo("Asia/Seoul"))
    df = pd.DataFrame(
        {
            "category": ["T1H"],
            "obsrValue": ["7.5"],
            "source": ["observed"],
            "collected_at": [collected_at],
        }
    )

    monkeypatch.setattr(weather_nowcast, "EXTERNAL_WEATHER_RAW", tmp_path / "weather" / "raw")
    monkeypatch.setattr(weather_nowcast, "fetch_snapshot", lambda nx=60, ny=127: df)

    weather_nowcast.run_once()

    snapshot_paths = list((tmp_path / "weather" / "raw" / "nowcast").glob("dt=*/hh=*/*.parquet"))
    latest_path = tmp_path / "weather" / "raw" / "nowcast" / "latest.parquet"

    assert len(snapshot_paths) == 1
    assert latest_path.exists()
    assert pd.read_parquet(latest_path).equals(df)
