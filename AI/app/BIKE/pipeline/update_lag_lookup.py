"""D-1/D-7 lag lookup 상시 갱신(Phase 2 Job B).

`snapshot_stock_history.py`(Job A, 30분마다)가 쌓은 날짜별 관측 로그를 station×date×
time_slot으로 집계해서, `lag_features.attach_lag()`가 기대하는 기존 스키마
(od_station_id·lag_date·lag_time_slot·lag_stock)로 그대로 저장한다 — 이 스키마를
지키는 이유는, 서빙 시점(Phase 5)에 `attach_lag()`를 코드 수정 없이 재사용하기 위해서다.

하루 1회 실행 전제(cron, 예: 매일 00:10 — 전날치가 다 쌓인 뒤). 보관 기간
(`bike_lag_lookup_retention_days`, 기본 10일)보다 오래된 관측 로그 파일은 이 스크립트가
같이 정리한다 — D-7까지만 필요하므로 무한정 쌓아둘 필요가 없다.

실행:
    cd AI
    python -m app.BIKE.pipeline.update_lag_lookup
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from app.BIKE.pipeline.atomic_io import atomic_write_parquet
from app.core.config import get_settings

LOOKUP_COLS = ["od_station_id", "lag_date", "lag_time_slot", "lag_stock"]
OBSERVATION_EMPTY_COLS = ["od_station_id", "date", "time_slot", "stock", "observed_at"]


def _iter_history_files(history_dir: Path):
    history_dir = Path(history_dir)
    if not history_dir.exists():
        return
    for path in sorted(history_dir.glob("dt=*.parquet")):
        day_str = path.stem.removeprefix("dt=")
        try:
            day = pd.Timestamp(day_str)
        except ValueError:
            continue
        yield path, day


def load_recent_observations(history_dir: Path, retention_days: int) -> pd.DataFrame:
    """보관기간 안의 `dt=*.parquet` 관측 로그를 전부 모아 하나로 합친다."""
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=retention_days)
    frames = [
        pd.read_parquet(path) for path, day in _iter_history_files(history_dir) if day >= cutoff
    ]
    if not frames:
        return pd.DataFrame(columns=OBSERVATION_EMPTY_COLS)
    return pd.concat(frames, ignore_index=True)


def build_lookup(observations: pd.DataFrame) -> pd.DataFrame:
    """관측 로그 -> `lag_features.attach_lag()` 호환 lookup(station×date×slot 평균)."""
    if observations.empty:
        return pd.DataFrame(columns=LOOKUP_COLS)
    grouped = (
        observations.groupby(["od_station_id", "date", "time_slot"])["stock"].mean().reset_index()
    )
    return grouped.rename(
        columns={"date": "lag_date", "time_slot": "lag_time_slot", "stock": "lag_stock"}
    )[LOOKUP_COLS]


def prune_old_history(history_dir: Path, retention_days: int) -> list[Path]:
    """보관기간 지난 관측 로그 파일을 삭제한다."""
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=retention_days)
    removed = []
    for path, day in _iter_history_files(history_dir):
        if day < cutoff:
            path.unlink()
            removed.append(path)
    return removed


def run() -> Path:
    settings = get_settings()
    observations = load_recent_observations(
        settings.bike_stock_history_dir, settings.bike_lag_lookup_retention_days
    )
    lookup = build_lookup(observations)
    out_path = atomic_write_parquet(lookup, Path(settings.bike_lag_lookup_path))
    removed = prune_old_history(
        settings.bike_stock_history_dir, settings.bike_lag_lookup_retention_days
    )
    print(
        f"[lag_lookup] {out_path.name} 갱신 ({len(lookup):,}행), "
        f"오래된 관측 로그 {len(removed)}개 정리",
        flush=True,
    )
    return out_path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.parse_args(argv)
    run()


if __name__ == "__main__":
    main(sys.argv[1:])
