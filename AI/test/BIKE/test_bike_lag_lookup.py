"""update_lag_lookup.py(Phase 2 Job B) 검증 — 관측 로그 집계와 보관기간 정리."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from app.BIKE.pipeline import update_lag_lookup as lag
from app.core.config import Settings

# update_lag_lookup.py 자체가 naive datetime(서버=KST 가정)을 쓰므로 테스트도 맞춘다.
TODAY = pd.Timestamp(datetime.now().date())  # noqa: DTZ005


def _write_history_day(history_dir, day: pd.Timestamp, rows: list[dict]) -> None:
    history_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(history_dir / f"dt={day:%Y-%m-%d}.parquet", index=False)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    s = Settings(
        bike_stock_history_dir=tmp_path / "stock_history",
        bike_lag_lookup_path=tmp_path / "lag_lookup_live.parquet",
        bike_lag_lookup_retention_days=10,
    )
    monkeypatch.setattr(lag, "get_settings", lambda: s)
    return s


def test_build_lookup_averages_same_station_date_slot():
    day = pd.Timestamp("2026-09-16")
    observations = pd.DataFrame(
        [
            {
                "od_station_id": "ST-1",
                "date": day,
                "time_slot": 28,
                "stock": 4,
                "observed_at": datetime(2026, 9, 16, 14, 5),  # noqa: DTZ001
            },
            {
                "od_station_id": "ST-1",
                "date": day,
                "time_slot": 28,
                "stock": 6,
                "observed_at": datetime(2026, 9, 16, 14, 20),  # noqa: DTZ001
            },
        ]
    )
    lookup = lag.build_lookup(observations)
    assert len(lookup) == 1
    row = lookup.iloc[0]
    assert row["od_station_id"] == "ST-1"
    assert row["lag_date"] == day
    assert row["lag_time_slot"] == 28
    assert row["lag_stock"] == 5.0  # (4+6)/2
    assert list(lookup.columns) == ["od_station_id", "lag_date", "lag_time_slot", "lag_stock"]


def test_build_lookup_empty_observations_returns_empty_with_right_columns():
    lookup = lag.build_lookup(pd.DataFrame(columns=lag.OBSERVATION_EMPTY_COLS))
    assert lookup.empty
    assert list(lookup.columns) == lag.LOOKUP_COLS


def test_load_recent_observations_excludes_files_older_than_retention(tmp_path):
    history_dir = tmp_path / "stock_history"
    old_day = TODAY - timedelta(days=15)
    recent_day = TODAY - timedelta(days=2)
    _write_history_day(
        history_dir,
        old_day,
        [
            {
                "od_station_id": "ST-1",
                "date": old_day,
                "time_slot": 10,
                "stock": 3,
                "observed_at": old_day,
            }
        ],
    )
    _write_history_day(
        history_dir,
        recent_day,
        [
            {
                "od_station_id": "ST-1",
                "date": recent_day,
                "time_slot": 10,
                "stock": 7,
                "observed_at": recent_day,
            }
        ],
    )

    observations = lag.load_recent_observations(history_dir, retention_days=10)
    assert set(observations["date"]) == {recent_day}


def test_prune_old_history_removes_only_files_past_retention(tmp_path):
    history_dir = tmp_path / "stock_history"
    old_day = TODAY - timedelta(days=15)
    recent_day = TODAY - timedelta(days=2)
    _write_history_day(
        history_dir,
        old_day,
        [
            {
                "od_station_id": "ST-1",
                "date": old_day,
                "time_slot": 10,
                "stock": 3,
                "observed_at": old_day,
            }
        ],
    )
    _write_history_day(
        history_dir,
        recent_day,
        [
            {
                "od_station_id": "ST-1",
                "date": recent_day,
                "time_slot": 10,
                "stock": 7,
                "observed_at": recent_day,
            }
        ],
    )

    removed = lag.prune_old_history(history_dir, retention_days=10)

    assert [p.name for p in removed] == [f"dt={old_day:%Y-%m-%d}.parquet"]
    remaining = sorted(p.name for p in history_dir.glob("dt=*.parquet"))
    assert remaining == [f"dt={recent_day:%Y-%m-%d}.parquet"]


def test_run_writes_lookup_schema_compatible_with_attach_lag(settings):
    day = TODAY
    _write_history_day(
        settings.bike_stock_history_dir,
        day,
        [
            {
                "od_station_id": "ST-1",
                "date": day,
                "time_slot": 28,
                "stock": 5,
                "observed_at": day,
            }
        ],
    )

    out_path = lag.run()
    result = pd.read_parquet(out_path)
    assert list(result.columns) == ["od_station_id", "lag_date", "lag_time_slot", "lag_stock"]
    assert len(result) == 1

    # lag_features.attach_lag()가 이 lookup을 그대로 조인할 수 있는지 확인(Phase 5에서
    # 실제로 이렇게 쓰일 예정).
    from app.BIKE.pipeline.lag_features import attach_lag

    target = pd.DataFrame(
        [{"od_station_id": "ST-1", "date": day + pd.Timedelta(days=1), "time_slot": 28}]
    )
    attached = attach_lag(target, result, days=1, out_col="lag1d_stock")
    assert attached["lag1d_stock"].iloc[0] == 5.0
    assert attached["lag1d_stock_available"].iloc[0] == 1


def test_run_with_no_history_writes_empty_lookup(settings):
    out_path = lag.run()
    result = pd.read_parquet(out_path)
    assert result.empty
    assert list(result.columns) == ["od_station_id", "lag_date", "lag_time_slot", "lag_stock"]
