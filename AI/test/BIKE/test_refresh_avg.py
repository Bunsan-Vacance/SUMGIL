"""Recent bike snapshots refresh the avg profile without replacing it on missing input."""

from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from app.BIKE.pipeline import refresh_avg


def _snapshot(root, day: date, minute: int, stock: int, station: str = "ST-1") -> None:
    path = root / f"dt={day.isoformat()}" / "hh=00" / f"snapshot_{station}_{minute:02d}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "stationId": station,
                "parkingBikeTotCnt": stock,
                "rackTotCnt": 4,
                "collected_at": pd.Timestamp(day, tz="Asia/Seoul") + pd.Timedelta(minutes=minute),
            }
        ]
    ).to_parquet(path, index=False)


def _baseline(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "od_station_id": "ST-1",
                "dow_type": 0,
                "time_slot": 0,
                "exp_bikes": 10.0,
                "p_empty": 0.1,
                "p_full": 0.2,
            },
            {
                "od_station_id": "ST-1",
                "dow_type": 0,
                "time_slot": 1,
                "exp_bikes": 8.0,
                "p_empty": 0.3,
                "p_full": 0.1,
            },
        ]
    ).to_parquet(path, index=False)


def test_refresh_blends_recent_snapshots_and_deduplicates_5m_slots(tmp_path):
    day = date(2026, 9, 16)
    raw = tmp_path / "raw"
    baseline = tmp_path / "baseline" / "stock_profile_avg.parquet"
    _baseline(baseline)
    for minute, stock in zip(range(0, 30, 5), [0, 4, 4, 4, 4, 4]):
        _snapshot(raw, day, minute, stock)
    _snapshot(raw, day, 1, 0)  # Same 5-minute slot: the later observation wins.
    for minute in range(0, 30, 5):
        _snapshot(raw, day, minute, 2, station="ST-2")

    output = refresh_avg.run(baseline, raw, tmp_path / "daily", tmp_path / "refreshed", day)
    profile = pd.read_parquet(output).set_index(["od_station_id", "time_slot"])
    first = profile.loc[("ST-1", 0)]
    assert first["exp_bikes"] == pytest.approx((10 * 48 + 20) / 54)
    assert first["p_empty"] == pytest.approx((0.1 * 48 + 1) / 54)
    assert first["p_full"] == pytest.approx((0.2 * 48 + 5) / 54)
    assert profile.loc[("ST-1", 1), "exp_bikes"] == 8
    assert profile.loc[("ST-2", 0), "exp_bikes"] == 2

    meta = json.loads((output.parent / "meta.json").read_text(encoding="utf-8"))
    assert meta["as_of"] == day.isoformat()
    assert meta["source_days"] == [day.isoformat()]
    assert meta["rows"] == 3


def test_missing_previous_day_keeps_published_profile(tmp_path):
    day = date(2026, 9, 16)
    baseline = tmp_path / "baseline" / "stock_profile_avg.parquet"
    _baseline(baseline)
    output_dir = tmp_path / "refreshed"
    output_dir.mkdir()
    published = output_dir / "stock_profile_avg.parquet"
    published.write_bytes(b"previous-good-profile")

    with pytest.raises(FileNotFoundError, match="기존 서빙 파일 유지"):
        refresh_avg.run(baseline, tmp_path / "raw", tmp_path / "daily", output_dir, day)

    assert published.read_bytes() == b"previous-good-profile"
    assert not (output_dir / "meta.json").exists()
