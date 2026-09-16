"""Discover completed DATA_ENGINE raw partitions for archive upload."""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from DATA_ENGINE.collect.common import KST

DEFAULT_BIKE_BASE = Path("data/BIKE/raw/realtime")
DEFAULT_WEATHER_BASE = Path("data/EXTERNAL/weather/raw/nowcast")
DEFAULT_SUBWAY_BASE = Path("data/SUBWAY/raw/arrival")
SNAPSHOT_PATTERN = "snapshot_*.parquet"


@dataclass(frozen=True)
class ArchiveDataset:
    name: str
    base_path: Path
    archive_prefix: Path


@dataclass(frozen=True)
class ArchiveTarget:
    dataset: str
    local_path: Path
    archive_path: str
    dt: str
    hh: str
    file_count: int
    total_bytes: int


def current_kst_partition(*, now: datetime | None = None) -> tuple[str, str]:
    if now is None:
        now = datetime.now(KST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    else:
        now = now.astimezone(KST)
    return now.strftime("%Y-%m-%d"), now.strftime("%H")


def build_archive_datasets(ai_root: Path) -> list[ArchiveDataset]:
    return [
        ArchiveDataset(
            name="bike",
            base_path=ai_root / DEFAULT_BIKE_BASE,
            archive_prefix=Path("BIKE/raw/realtime"),
        ),
        ArchiveDataset(
            name="weather",
            base_path=ai_root / DEFAULT_WEATHER_BASE,
            archive_prefix=Path("EXTERNAL/weather/raw/nowcast"),
        ),
        ArchiveDataset(
            name="subway",
            base_path=ai_root / DEFAULT_SUBWAY_BASE,
            archive_prefix=Path("SUBWAY/raw/arrival"),
        ),
    ]


def filter_datasets(datasets: Iterable[ArchiveDataset], dataset: str) -> list[ArchiveDataset]:
    if dataset == "all":
        return list(datasets)
    filtered = [item for item in datasets if item.name == dataset]
    if not filtered:
        raise ValueError("dataset must be one of: all, bike, weather, subway")
    return filtered


def parse_partition_dir(path: Path) -> tuple[str, str] | None:
    if len(path.parts) < 2:
        return None
    dt_part = path.parts[-2]
    hh_part = path.parts[-1]
    if not (dt_part.startswith("dt=") and hh_part.startswith("hh=")):
        return None

    dt = dt_part.removeprefix("dt=")
    hh = hh_part.removeprefix("hh=")
    if len(dt) != 10 or len(hh) != 2:
        return None
    return dt, hh


def is_old_enough(snapshot_files: list[Path], *, now_ts: float, older_than_hours: float) -> bool:
    if older_than_hours < 0:
        raise ValueError("older_than_hours must be non-negative")
    newest_mtime = max(path.stat().st_mtime for path in snapshot_files)
    return newest_mtime <= now_ts - (older_than_hours * 3600)


def discover_archive_targets(
    datasets: Iterable[ArchiveDataset],
    *,
    older_than_hours: float = 1,
    current_slot: tuple[str, str] | None = None,
    now_ts: float | None = None,
) -> list[ArchiveTarget]:
    if older_than_hours < 0:
        raise ValueError("older_than_hours must be non-negative")
    if current_slot is None:
        current_slot = current_kst_partition()
    if now_ts is None:
        now_ts = time.time()

    targets: list[ArchiveTarget] = []
    for dataset in datasets:
        if not dataset.base_path.exists():
            continue
        for partition_dir in dataset.base_path.glob("dt=*/hh=*"):
            if not partition_dir.is_dir():
                continue

            parsed = parse_partition_dir(partition_dir)
            if parsed is None:
                continue
            dt, hh = parsed
            if (dt, hh) == current_slot:
                continue

            snapshot_files = sorted(
                path for path in partition_dir.glob(SNAPSHOT_PATTERN) if path.is_file()
            )
            if not snapshot_files:
                continue
            if not is_old_enough(
                snapshot_files,
                now_ts=now_ts,
                older_than_hours=older_than_hours,
            ):
                continue

            archive_path = dataset.archive_prefix / f"dt={dt}" / f"hh={hh}"
            targets.append(
                ArchiveTarget(
                    dataset=dataset.name,
                    local_path=partition_dir,
                    archive_path=archive_path.as_posix(),
                    dt=dt,
                    hh=hh,
                    file_count=len(snapshot_files),
                    total_bytes=sum(path.stat().st_size for path in snapshot_files),
                )
            )

    return sorted(targets, key=lambda target: (target.dt, target.hh, target.dataset))
