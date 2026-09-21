"""Check whether realtime collection latest parquet files are fresh."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
from pyarrow import ArrowException

from DATA_ENGINE.collect.common import KST

AI_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BIKE_LATEST = Path("data/BIKE/raw/realtime/latest_stock.parquet")
DEFAULT_WEATHER_LATEST = Path("data/EXTERNAL/weather/raw/nowcast/latest_by_grid.parquet")
DEFAULT_BIKE_MAX_AGE_MIN = 10.0
DEFAULT_WEATHER_MAX_AGE_MIN = 90.0


@dataclass(frozen=True)
class FreshnessCheck:
    name: str
    path: Path
    max_age_min: float
    timestamp_column: str


@dataclass(frozen=True)
class FreshnessResult:
    name: str
    path: Path
    ok: bool
    status: str
    message: str
    age_min: float | None = None


def _format_age(age_min: float) -> str:
    return f"{age_min:.1f}m"


def check_latest_file(
    name: str,
    path: Path,
    max_age_min: float,
    timestamp_column: str,
    *,
    now_ts: float | None = None,
) -> FreshnessResult:
    """Return freshness status using the newest timestamp stored in a latest file."""
    if now_ts is None:
        now_ts = time.time()

    if max_age_min <= 0:
        raise ValueError("max_age_min must be positive")

    if not path.exists():
        return FreshnessResult(
            name=name,
            path=path,
            ok=False,
            status="missing",
            message=f"FAIL {name} latest missing: path={path}",
        )

    try:
        frame = pd.read_parquet(path, columns=[timestamp_column])
        latest = pd.to_datetime(frame[timestamp_column], errors="coerce").max()
    except (ArrowException, KeyError, OSError, TypeError, ValueError) as exc:
        return FreshnessResult(
            name=name,
            path=path,
            ok=False,
            status="invalid",
            message=(
                f"FAIL {name} latest invalid: column={timestamp_column} "
                f"error={type(exc).__name__} path={path}"
            ),
        )

    if pd.isna(latest):
        return FreshnessResult(
            name=name,
            path=path,
            ok=False,
            status="invalid",
            message=(
                f"FAIL {name} latest invalid: column={timestamp_column} "
                f"reason=no_valid_timestamp path={path}"
            ),
        )

    latest = pd.Timestamp(latest)
    if latest.tzinfo is None:
        latest = latest.tz_localize(KST)
    else:
        latest = latest.tz_convert(KST)
    now = datetime.fromtimestamp(now_ts, tz=KST)
    age_min = max(0.0, (now - latest.to_pydatetime()).total_seconds() / 60.0)
    if age_min > max_age_min:
        return FreshnessResult(
            name=name,
            path=path,
            ok=False,
            status="stale",
            age_min=age_min,
            message=(
                f"FAIL {name} latest stale: "
                f"age={_format_age(age_min)} max={max_age_min:g}m "
                f"basis={timestamp_column} path={path}"
            ),
        )

    return FreshnessResult(
        name=name,
        path=path,
        ok=True,
        status="fresh",
        age_min=age_min,
        message=(
            f"OK {name} latest fresh: "
            f"age={_format_age(age_min)} max={max_age_min:g}m "
            f"basis={timestamp_column} path={path}"
        ),
    )


def check_freshness(
    checks: Iterable[FreshnessCheck],
    *,
    now_ts: float | None = None,
) -> list[FreshnessResult]:
    """Run freshness checks and return all results."""
    if now_ts is None:
        now_ts = time.time()
    return [
        check_latest_file(
            check.name,
            check.path,
            check.max_age_min,
            check.timestamp_column,
            now_ts=now_ts,
        )
        for check in checks
    ]


def build_checks(
    ai_root: Path,
    bike_max_age_min: float,
    weather_max_age_min: float,
) -> list[FreshnessCheck]:
    return [
        FreshnessCheck(
            name="bike",
            path=ai_root / DEFAULT_BIKE_LATEST,
            max_age_min=bike_max_age_min,
            timestamp_column="updated_at",
        ),
        FreshnessCheck(
            name="weather",
            path=ai_root / DEFAULT_WEATHER_LATEST,
            max_age_min=weather_max_age_min,
            timestamp_column="ingested_at",
        ),
    ]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check DATA_ENGINE latest parquet freshness.",
    )
    parser.add_argument(
        "--ai-root",
        type=Path,
        default=AI_ROOT,
        help="AI project root. Defaults to the root inferred from this file.",
    )
    parser.add_argument(
        "--bike-max-age-min",
        type=float,
        default=DEFAULT_BIKE_MAX_AGE_MIN,
        help="Maximum allowed bike latest age in minutes.",
    )
    parser.add_argument(
        "--weather-max-age-min",
        type=float,
        default=DEFAULT_WEATHER_MAX_AGE_MIN,
        help="Maximum allowed weather latest age in minutes.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    checks = build_checks(
        args.ai_root,
        bike_max_age_min=args.bike_max_age_min,
        weather_max_age_min=args.weather_max_age_min,
    )
    results = check_freshness(checks)
    for result in results:
        print(result.message)
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
