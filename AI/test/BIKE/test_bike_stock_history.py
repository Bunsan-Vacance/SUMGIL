"""snapshot_stock_history.py(Phase 2 Job A) 검증 — latest_stock.parquet 스냅샷을
날짜별 관측 로그에 upsert하는 로직."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from app.BIKE.pipeline import snapshot_stock_history as snap
from app.core.config import Settings


def _live(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    live_path = tmp_path / "latest_stock.parquet"
    history_dir = tmp_path / "stock_history"
    s = Settings(
        bike_live_stock_path=live_path,
        bike_stock_history_dir=history_dir,
    )
    monkeypatch.setattr(snap, "get_settings", lambda: s)
    return s


def test_build_observations_maps_columns_and_time_slot():
    live = _live(
        [
            {
                "rental_id": "ST-1",
                "current_stock": 5,
                "updated_at": datetime(2026, 9, 16, 14, 38),  # noqa: DTZ001
            },
            {
                "rental_id": "ST-2",
                "current_stock": 9,
                "updated_at": datetime(2026, 9, 16, 14, 5),  # noqa: DTZ001
            },
        ]
    )
    obs = snap.build_observations(live)
    row1 = obs[obs["od_station_id"] == "ST-1"].iloc[0]
    row2 = obs[obs["od_station_id"] == "ST-2"].iloc[0]
    assert row1["time_slot"] == 29  # 14:38 -> minute>=30 -> 14*2+1
    assert row2["time_slot"] == 28  # 14:05 -> minute<30 -> 14*2+0
    assert row1["stock"] == 5
    assert row1["date"] == pd.Timestamp("2026-09-16")


def test_upsert_day_keeps_latest_observation_per_station_slot(tmp_path):
    day = pd.Timestamp("2026-09-16")
    first = pd.DataFrame(
        [
            {
                "od_station_id": "ST-1",
                "date": day,
                "time_slot": 28,
                "stock": 5,
                "observed_at": datetime(2026, 9, 16, 14, 10),  # noqa: DTZ001
            }
        ]
    )
    snap.upsert_day(tmp_path, day, first)

    second = pd.DataFrame(
        [
            {
                "od_station_id": "ST-1",
                "date": day,
                "time_slot": 28,
                "stock": 7,  # 같은 station·slot, 더 최근 관측
                "observed_at": datetime(2026, 9, 16, 14, 20),  # noqa: DTZ001
            },
            {
                "od_station_id": "ST-2",
                "date": day,
                "time_slot": 30,
                "stock": 3,
                "observed_at": datetime(2026, 9, 16, 15, 5),  # noqa: DTZ001
            },
        ]
    )
    path = snap.upsert_day(tmp_path, day, second)
    result = pd.read_parquet(path)

    assert len(result) == 2  # ST-1은 덮어써짐(2행 아님), ST-2는 새로 추가
    st1 = result[result["od_station_id"] == "ST-1"].iloc[0]
    assert st1["stock"] == 7  # 최신 값으로 남음, 5로 남지 않음


def test_upsert_day_does_not_drop_other_stations_not_in_this_batch(tmp_path):
    day = pd.Timestamp("2026-09-16")
    first = pd.DataFrame(
        [
            {
                "od_station_id": "ST-1",
                "date": day,
                "time_slot": 28,
                "stock": 5,
                "observed_at": datetime(2026, 9, 16, 14, 10),  # noqa: DTZ001
            }
        ]
    )
    snap.upsert_day(tmp_path, day, first)

    # 이번 배치엔 ST-1이 안 들어옴 -> 기존 값이 사라지면 안 됨(전체 덮어쓰기 금지)
    second = pd.DataFrame(
        [
            {
                "od_station_id": "ST-2",
                "date": day,
                "time_slot": 30,
                "stock": 3,
                "observed_at": datetime(2026, 9, 16, 15, 5),  # noqa: DTZ001
            }
        ]
    )
    path = snap.upsert_day(tmp_path, day, second)
    result = pd.read_parquet(path)

    assert set(result["od_station_id"]) == {"ST-1", "ST-2"}


def test_run_splits_observations_across_day_boundaries(settings):
    live = _live(
        [
            {
                "rental_id": "ST-1",
                "current_stock": 5,
                "updated_at": datetime(2026, 9, 15, 23, 55),  # noqa: DTZ001
            },
            {
                "rental_id": "ST-1",
                "current_stock": 6,
                "updated_at": datetime(2026, 9, 16, 0, 5),  # noqa: DTZ001
            },
        ]
    )
    live.to_parquet(settings.bike_live_stock_path, index=False)

    written = snap.run()
    names = {p.name for p in written}
    assert names == {"dt=2026-09-15.parquet", "dt=2026-09-16.parquet"}


def test_run_skips_when_live_file_missing(settings):
    written = snap.run()
    assert written == []


def test_run_skips_when_live_file_empty(settings):
    pd.DataFrame(columns=["rental_id", "current_stock", "updated_at"]).to_parquet(
        settings.bike_live_stock_path, index=False
    )
    written = snap.run()
    assert written == []
