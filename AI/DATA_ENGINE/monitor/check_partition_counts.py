"""Check whether completed hourly partitions have enough snapshot files."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from DATA_ENGINE.collect.common import KST

AI_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BIKE_BASE = Path("data/BIKE/raw/realtime")
DEFAULT_WEATHER_BASE = Path("data/EXTERNAL/weather/raw/nowcast")
DEFAULT_HOURS = 1
DEFAULT_BIKE_MIN_COUNT = 10
DEFAULT_WEATHER_MIN_COUNT = 5
KAFKA_WEATHER_MIN_COUNT = 1


@dataclass(frozen=True)
class HourSlot:
    dt: str
    hh: str


@dataclass(frozen=True)
class PartitionCheck:
    name: str
    base_path: Path
    min_count: int
    required_column: str | None = None


@dataclass(frozen=True)
class PartitionResult:
    name: str
    path: Path
    slot: HourSlot
    count: int
    min_count: int
    ok: bool
    status: str
    message: str


def completed_hour_slots(hours: int, *, now: datetime | None = None) -> list[HourSlot]:
    """Return the latest completed KST hour slots, newest first."""
    if hours <= 0:
        raise ValueError("hours must be positive")

    if now is None:
        now = datetime.now(KST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    else:
        now = now.astimezone(KST)

    latest_completed = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    return [
        HourSlot(
            dt=(latest_completed - timedelta(hours=offset)).strftime("%Y-%m-%d"),
            hh=(latest_completed - timedelta(hours=offset)).strftime("%H"),
        )
        for offset in range(hours)
    ]


def partition_path(base_path: Path, slot: HourSlot) -> Path:
    return base_path / f"dt={slot.dt}" / f"hh={slot.hh}"


def count_partition_snapshots(
    base_path: Path, slot: HourSlot, required_column: str | None = None
) -> int:
    path = partition_path(base_path, slot)
    if not path.exists():
        return 0
    files = (item for item in path.glob("snapshot_*.parquet") if item.is_file())
    if required_column is None:
        return sum(1 for _ in files)
    import pyarrow.parquet as pq

    return sum(required_column in pq.read_schema(item).names for item in files)


def check_partition(check: PartitionCheck, slot: HourSlot) -> PartitionResult:
    if check.min_count <= 0:
        raise ValueError("min_count must be positive")

    path = partition_path(check.base_path, slot)
    count = count_partition_snapshots(check.base_path, slot, check.required_column)
    if count == 0:
        return PartitionResult(
            name=check.name,
            path=path,
            slot=slot,
            count=count,
            min_count=check.min_count,
            ok=False,
            status="missing",
            message=(
                f"FAIL {check.name} partition missing: "
                f"dt={slot.dt} hh={slot.hh} count=0 min={check.min_count} path={path}"
            ),
        )

    if count < check.min_count:
        return PartitionResult(
            name=check.name,
            path=path,
            slot=slot,
            count=count,
            min_count=check.min_count,
            ok=False,
            status="low",
            message=(
                f"FAIL {check.name} partition count low: "
                f"dt={slot.dt} hh={slot.hh} count={count} min={check.min_count} path={path}"
            ),
        )

    return PartitionResult(
        name=check.name,
        path=path,
        slot=slot,
        count=count,
        min_count=check.min_count,
        ok=True,
        status="ok",
        message=(
            f"OK {check.name} partition count: "
            f"dt={slot.dt} hh={slot.hh} count={count} min={check.min_count} path={path}"
        ),
    )


def check_partitions(
    checks: Iterable[PartitionCheck],
    slots: Iterable[HourSlot],
) -> list[PartitionResult]:
    return [check_partition(check, slot) for check in checks for slot in slots]


def build_partition_checks(
    ai_root: Path,
    bike_min_count: int,
    weather_min_count: int,
    weather_source: str = "poller",
) -> list[PartitionCheck]:
    if weather_source not in {"poller", "kafka"}:
        raise ValueError("weather_source must be poller or kafka")
    return [
        PartitionCheck(
            name="bike",
            base_path=ai_root / DEFAULT_BIKE_BASE,
            min_count=bike_min_count,
        ),
        PartitionCheck(
            name="weather",
            base_path=ai_root / DEFAULT_WEATHER_BASE,
            min_count=weather_min_count,
            required_column="kafka_topic" if weather_source == "kafka" else None,
        ),
    ]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check DATA_ENGINE completed hourly partition snapshot counts.",
    )
    parser.add_argument(
        "--ai-root",
        type=Path,
        default=AI_ROOT,
        help="AI project root. Defaults to the root inferred from this file.",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=DEFAULT_HOURS,
        help="Number of completed KST hourly partitions to check.",
    )
    parser.add_argument(
        "--bike-min-count",
        type=int,
        default=DEFAULT_BIKE_MIN_COUNT,
        help="Minimum bike snapshots per completed hour.",
    )
    parser.add_argument(
        "--weather-min-count",
        type=int,
        default=None,
        help="Minimum weather snapshots per completed hour.",
    )
    parser.add_argument("--weather-source", choices=["poller", "kafka"], default="poller")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    slots = completed_hour_slots(args.hours)
    checks = build_partition_checks(
        args.ai_root,
        bike_min_count=args.bike_min_count,
        weather_min_count=(
            args.weather_min_count
            if args.weather_min_count is not None
            else (
                KAFKA_WEATHER_MIN_COUNT
                if args.weather_source == "kafka"
                else DEFAULT_WEATHER_MIN_COUNT
            )
        ),
        weather_source=args.weather_source,
    )
    results = check_partitions(checks, slots)
    for result in results:
        print(result.message)
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
