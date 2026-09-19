"""LightGBM anchor+horizon 서빙용 D-1/D-7 lag 재료 만들기 1단계(Phase 2 Job A).

Kafka 원본 이벤트(payload_json) 필드명이 아직 확정 전이라, 이미 검증된
`latest_stock.parquet`(rental_id·current_stock·updated_at)을 주기적으로 스냅샷 떠서
날짜별 관측 로그에 쌓는 방식을 쓴다. 30분마다 실행 전제(cron) — 각 행의 `updated_at`
기준으로 date/time_slot을 계산해 그 날짜의 로그 파일에 station×time_slot 단위로
upsert한다(전체 덮어쓰기 금지 — 이번 실행에 없는 station·slot 조합은 기존 값 유지).

집계(하루 단위로 묶어 lag_lookup 스키마로 변환)는 `update_lag_lookup.py`(Job B, 하루
1회)가 한다 — 이 스크립트는 원시 관측치를 쌓기만 한다.

실행:
    cd AI
    python -m app.BIKE.pipeline.snapshot_stock_history
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.BIKE.pipeline.atomic_io import atomic_write_parquet
from app.core.config import get_settings

OBSERVATION_COLS = ["od_station_id", "date", "time_slot", "stock", "observed_at"]


def _time_slot(when: pd.Series) -> pd.Series:
    """hour*2 + (minute>=30) — calendar.dow_type_and_time_slot과 동일 공식."""
    half_hour = (when.dt.minute >= 30).astype("int64")
    return when.dt.hour * 2 + half_hour


def build_observations(live: pd.DataFrame) -> pd.DataFrame:
    """latest_stock.parquet(rental_id·current_stock·updated_at) -> 관측 로그 행.

    시각 기준은 스냅샷을 뜬 지금(now)이 아니라 각 행의 `updated_at`이다 — 역마다
    실제로 마지막 갱신된 시점이 조금씩 다를 수 있어서, 그 시점 그대로 date/time_slot을
    매긴다.
    """
    updated_at = pd.to_datetime(live["updated_at"])
    return pd.DataFrame(
        {
            "od_station_id": live["rental_id"].astype(str),
            "date": updated_at.dt.normalize(),
            "time_slot": _time_slot(updated_at),
            "stock": live["current_stock"].astype("int64"),
            "observed_at": updated_at,
        }
    )


def _history_path(history_dir: Path, day: pd.Timestamp) -> Path:
    return Path(history_dir) / f"dt={day:%Y-%m-%d}.parquet"


def upsert_day(history_dir: Path, day: pd.Timestamp, new_rows: pd.DataFrame) -> Path:
    """`new_rows`(그 날짜분)를 그 날짜 관측 로그 파일에 station×time_slot 단위로 upsert한다.

    같은 station×slot에 값이 여러 번 들어오면(스냅샷 주기가 겹칠 때) 가장 최근
    `observed_at`인 값만 남긴다.
    """
    path = _history_path(history_dir, day)
    if path.exists():
        existing = pd.read_parquet(path)
        combined = pd.concat([existing, new_rows], ignore_index=True)
    else:
        combined = new_rows
    combined = combined.sort_values("observed_at").drop_duplicates(
        subset=["od_station_id", "time_slot"], keep="last"
    )
    atomic_write_parquet(combined[OBSERVATION_COLS], path)
    return path


def run(now: datetime | None = None) -> list[Path]:
    settings = get_settings()
    live_path = Path(settings.bike_live_stock_path)
    if not live_path.exists():
        print(f"[snapshot] {live_path} 없음 - 스킵", flush=True)
        return []

    live = pd.read_parquet(live_path)
    if live.empty:
        print("[snapshot] latest_stock.parquet이 비어있음 - 스킵", flush=True)
        return []

    observations = build_observations(live)

    history_dir = Path(settings.bike_stock_history_dir)
    written = []
    for day, day_rows in observations.groupby("date"):
        path = upsert_day(history_dir, pd.Timestamp(day), day_rows)
        written.append(path)
        print(f"[snapshot] {path.name} upsert ({len(day_rows):,}행)", flush=True)
    return written


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.parse_args(argv)
    run()


if __name__ == "__main__":
    main(sys.argv[1:])
