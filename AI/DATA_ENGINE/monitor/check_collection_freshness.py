"""Check whether realtime collection latest parquet files are fresh."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
from pyarrow import ArrowException

from DATA_ENGINE.collect.common import KST
from DATA_ENGINE.monitor.operating_window import (
    OperatingWindow,
    parse_hhmm,
    subway_window_from_env,
)

AI_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BIKE_LATEST = Path("data/BIKE/raw/realtime/latest_stock.parquet")
DEFAULT_WEATHER_LATEST = Path("data/EXTERNAL/weather/raw/nowcast/latest_by_grid.parquet")
DEFAULT_BIKE_MAX_AGE_MIN = 10.0
DEFAULT_WEATHER_MAX_AGE_MIN = 90.0
DEFAULT_BIKE_ROW_MAX_AGE_MIN = 30.0
DEFAULT_SUBWAY_BASE = Path("data/SUBWAY/raw/arrival")
DEFAULT_SUBWAY_MAX_AGE_MIN = 10.0
SUBWAY_TOPIC = "subway.arrival"
SUBWAY_ENVELOPE_COLUMNS = ("kafka_topic", "source_generated_at", "ingested_at", "poll_run_at")
SUBWAY_SCAN_LIMIT = 30


@dataclass(frozen=True)
class FreshnessCheck:
    name: str
    path: Path
    max_age_min: float
    timestamp_column: str
    row_max_age_min: float | None = None


@dataclass(frozen=True)
class FreshnessResult:
    name: str
    path: Path
    ok: bool
    status: str
    message: str
    age_min: float | None = None
    stale_rows: int | None = None


def _format_age(age_min: float) -> str:
    return f"{age_min:.1f}m"


def check_latest_file(
    name: str,
    path: Path,
    max_age_min: float,
    timestamp_column: str,
    row_max_age_min: float | None = None,
    *,
    now_ts: float | None = None,
) -> FreshnessResult:
    """Return freshness status using the newest timestamp stored in a latest file."""
    if now_ts is None:
        now_ts = time.time()

    if max_age_min <= 0:
        raise ValueError("max_age_min must be positive")
    if row_max_age_min is not None and row_max_age_min <= 0:
        raise ValueError("row_max_age_min must be positive")

    if not path.exists():
        return FreshnessResult(
            name=name,
            path=path,
            ok=False,
            status="missing",
            message=f"FAIL {name} latest missing: path={path}",
        )

    try:
        table = pq.read_table(path, columns=[timestamp_column], use_threads=False)
        timestamps = pd.Series(
            pd.to_datetime(table.column(timestamp_column).to_pylist(), errors="coerce")
        )
        latest = timestamps.max()
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

    stale_rows = None
    if row_max_age_min is not None:
        if timestamps.dt.tz is None:
            timestamps = timestamps.dt.tz_localize(KST)
        else:
            timestamps = timestamps.dt.tz_convert(KST)
        cutoff = now - timedelta(minutes=row_max_age_min)
        stale_rows = int((timestamps < cutoff).sum())
        if stale_rows:
            return FreshnessResult(
                name=name,
                path=path,
                ok=False,
                status="stale_rows",
                age_min=age_min,
                stale_rows=stale_rows,
                message=(
                    f"FAIL {name} latest contains stale rows: count={stale_rows} "
                    f"row_max={row_max_age_min:g}m basis={timestamp_column} path={path}"
                ),
            )

    return FreshnessResult(
        name=name,
        path=path,
        ok=True,
        status="fresh",
        age_min=age_min,
        stale_rows=stale_rows,
        message=(
            f"OK {name} latest fresh: "
            f"age={_format_age(age_min)} max={max_age_min:g}m "
            f"basis={timestamp_column} path={path}"
        ),
    )


def _to_kst(value: object) -> pd.Timestamp | None:
    stamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(stamp):
        return None
    stamp = pd.Timestamp(stamp)
    return stamp.tz_localize(KST) if stamp.tzinfo is None else stamp.tz_convert(KST)


def _newest_subway_envelope(base_path: Path) -> tuple[dict[str, pd.Timestamp | None], Path] | None:
    """Read envelope times from the newest snapshot that holds ``subway.arrival`` rows.

    Only Kafka envelope columns are read; payload fields are never interpreted.
    """
    files = sorted(
        (item for item in base_path.glob("dt=*/hh=*/snapshot_*.parquet") if item.is_file()),
        key=lambda item: (item.parent.parent.name, item.parent.name, item.name),
        reverse=True,
    )
    for item in files[:SUBWAY_SCAN_LIMIT]:
        names = pq.read_schema(item).names
        columns = [column for column in SUBWAY_ENVELOPE_COLUMNS if column in names]
        if "kafka_topic" not in columns:
            continue
        frame = pq.read_table(item, columns=columns, use_threads=False).to_pandas()
        frame = frame.loc[frame["kafka_topic"] == SUBWAY_TOPIC]
        if frame.empty:
            continue
        times = {
            column: _to_kst(frame[column].max()) if column in frame else None
            for column in SUBWAY_ENVELOPE_COLUMNS[1:]
        }
        return times, item
    return None


def check_subway_freshness(
    base_path: Path,
    max_age_min: float,
    window: OperatingWindow,
    *,
    now_ts: float | None = None,
) -> FreshnessResult:
    """Fail when no fresh subway snapshot arrived while the producer should be running."""
    if max_age_min <= 0:
        raise ValueError("max_age_min must be positive")
    now = datetime.fromtimestamp(time.time() if now_ts is None else now_ts, tz=KST)
    name = "subway"

    if not window.contains(now):
        return FreshnessResult(
            name=name,
            path=base_path,
            ok=True,
            status="outside_window",
            message=f"SKIP {name} latest outside operating window: path={base_path}",
        )

    try:
        found = _newest_subway_envelope(base_path)
    except (ArrowException, OSError, TypeError, ValueError) as exc:
        return FreshnessResult(
            name=name,
            path=base_path,
            ok=False,
            status="invalid",
            message=f"FAIL {name} latest invalid: error={type(exc).__name__} path={base_path}",
        )
    if found is None:
        return FreshnessResult(
            name=name,
            path=base_path,
            ok=False,
            status="missing",
            message=f"FAIL {name} latest missing: topic={SUBWAY_TOPIC} path={base_path}",
        )

    times, snapshot = found
    basis = times["poll_run_at"] or times["ingested_at"]
    if basis is None:
        return FreshnessResult(
            name=name,
            path=snapshot,
            ok=False,
            status="invalid",
            message=(
                f"FAIL {name} latest invalid: reason=no_valid_timestamp "
                f"topic={SUBWAY_TOPIC} path={snapshot}"
            ),
        )

    # 운영 시작 직후에는 전날 마지막 수집분이 남아 있으므로 개장 시각 이후로 age를 잰다.
    reference = max(basis.to_pydatetime(), window.last_open(now))
    age_min = max(0.0, (now - reference).total_seconds() / 60.0)
    detail = " ".join(f"{key}={value}" for key, value in times.items())
    stale = age_min > max_age_min
    return FreshnessResult(
        name=name,
        path=snapshot,
        ok=not stale,
        status="stale" if stale else "fresh",
        age_min=age_min,
        message=(
            f"{'FAIL' if stale else 'OK'} {name} latest {'stale' if stale else 'fresh'}: "
            f"age={_format_age(age_min)} max={max_age_min:g}m "
            f"basis=poll_run_at topic={SUBWAY_TOPIC} {detail} path={snapshot}"
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
            check.row_max_age_min,
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
            row_max_age_min=DEFAULT_BIKE_ROW_MAX_AGE_MIN,
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
    parser.add_argument(
        "--subway-max-age-min",
        type=float,
        default=DEFAULT_SUBWAY_MAX_AGE_MIN,
        help="Maximum allowed subway snapshot age in minutes during operating hours.",
    )
    parser.add_argument(
        "--subway-window-start",
        default=None,
        help="Subway operating window start HH:MM (env SUBWAY_OPERATING_START).",
    )
    parser.add_argument(
        "--subway-window-end",
        default=None,
        help="Subway operating window end HH:MM (env SUBWAY_OPERATING_END).",
    )
    parser.add_argument(
        "--no-subway",
        action="store_true",
        help="Skip the subway.arrival check.",
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
    if not args.no_subway:
        default = subway_window_from_env()
        window = OperatingWindow(
            parse_hhmm(args.subway_window_start) if args.subway_window_start else default.start_min,
            parse_hhmm(args.subway_window_end) if args.subway_window_end else default.end_min,
        )
        results.append(
            check_subway_freshness(
                args.ai_root / DEFAULT_SUBWAY_BASE, args.subway_max_age_min, window
            )
        )
    for result in results:
        print(result.message)
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
