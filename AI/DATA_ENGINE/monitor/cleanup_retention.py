"""Clean up old DATA_ENGINE realtime raw snapshot files."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from DATA_ENGINE.collect.common import KST

AI_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RETENTION_HOURS = 48
DEFAULT_BIKE_BASE = Path("data/BIKE/raw/realtime")
DEFAULT_WEATHER_BASE = Path("data/EXTERNAL/weather/raw/nowcast")
SNAPSHOT_PATTERN = "dt=*/hh=*/snapshot_*.parquet"


@dataclass(frozen=True)
class RetentionTarget:
    name: str
    base_path: Path


@dataclass(frozen=True)
class CleanupCandidate:
    target_name: str
    path: Path
    size_bytes: int
    age_hours: float


@dataclass(frozen=True)
class CleanupResult:
    dry_run: bool
    retention_hours: float
    candidates: list[CleanupCandidate]
    deleted_count: int
    deleted_bytes: int

    @property
    def candidate_bytes(self) -> int:
        return sum(candidate.size_bytes for candidate in self.candidates)


def current_kst_partition(*, now: datetime | None = None) -> tuple[str, str]:
    if now is None:
        now = datetime.now(KST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    else:
        now = now.astimezone(KST)
    return now.strftime("%Y-%m-%d"), now.strftime("%H")


def format_bytes(size_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)}B"
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size_bytes}B"


def is_safe_snapshot_path(
    target: RetentionTarget,
    path: Path,
    *,
    current_slot: tuple[str, str] | None = None,
) -> bool:
    """Return whether path is a whitelisted completed-hour snapshot file."""
    if path.name == "latest.parquet":
        return False
    if not path.match("snapshot_*.parquet"):
        return False

    try:
        relative = path.resolve().relative_to(target.base_path.resolve())
    except ValueError:
        return False

    if len(relative.parts) != 3:
        return False

    dt_part, hh_part, filename = relative.parts
    if filename != path.name:
        return False
    if not (dt_part.startswith("dt=") and hh_part.startswith("hh=")):
        return False

    dt = dt_part.removeprefix("dt=")
    hh = hh_part.removeprefix("hh=")
    return not (current_slot is not None and (dt, hh) == current_slot)


def build_retention_targets(ai_root: Path) -> list[RetentionTarget]:
    return [
        RetentionTarget("bike", ai_root / DEFAULT_BIKE_BASE),
        RetentionTarget("weather", ai_root / DEFAULT_WEATHER_BASE),
    ]


def find_cleanup_candidates(
    targets: Iterable[RetentionTarget],
    *,
    retention_hours: float,
    now_ts: float | None = None,
    current_slot: tuple[str, str] | None = None,
) -> list[CleanupCandidate]:
    if retention_hours <= 0:
        raise ValueError("retention_hours must be positive")

    if now_ts is None:
        now_ts = time.time()
    if current_slot is None:
        current_slot = current_kst_partition()

    candidates: list[CleanupCandidate] = []
    for target in targets:
        if not target.base_path.exists():
            continue
        for path in target.base_path.glob(SNAPSHOT_PATTERN):
            if not path.is_file():
                continue
            if not is_safe_snapshot_path(target, path, current_slot=current_slot):
                continue

            stat = path.stat()
            age_hours = max(0.0, (now_ts - stat.st_mtime) / 3600)
            if age_hours <= retention_hours:
                continue

            candidates.append(
                CleanupCandidate(
                    target_name=target.name,
                    path=path,
                    size_bytes=stat.st_size,
                    age_hours=age_hours,
                )
            )

    return sorted(candidates, key=lambda candidate: str(candidate.path))


def cleanup_candidates(
    candidates: Iterable[CleanupCandidate],
    *,
    yes: bool,
) -> tuple[int, int]:
    if not yes:
        return 0, 0

    deleted_count = 0
    deleted_bytes = 0
    for candidate in candidates:
        candidate.path.unlink()
        deleted_count += 1
        deleted_bytes += candidate.size_bytes
    return deleted_count, deleted_bytes


def run_cleanup(
    targets: Iterable[RetentionTarget],
    *,
    retention_hours: float,
    yes: bool,
    now_ts: float | None = None,
    current_slot: tuple[str, str] | None = None,
) -> CleanupResult:
    candidates = find_cleanup_candidates(
        targets,
        retention_hours=retention_hours,
        now_ts=now_ts,
        current_slot=current_slot,
    )
    deleted_count, deleted_bytes = cleanup_candidates(candidates, yes=yes)
    return CleanupResult(
        dry_run=not yes,
        retention_hours=retention_hours,
        candidates=candidates,
        deleted_count=deleted_count,
        deleted_bytes=deleted_bytes,
    )


def print_cleanup_result(result: CleanupResult) -> None:
    print(
        "DATA_ENGINE retention cleanup "
        f"dry_run={str(result.dry_run).lower()} "
        f"retention_hours={result.retention_hours:g} "
        f"candidates={len(result.candidates)} "
        f"candidate_size={format_bytes(result.candidate_bytes)} "
        f"deleted={result.deleted_count} "
        f"deleted_size={format_bytes(result.deleted_bytes)}"
    )
    for candidate in result.candidates:
        print(
            f"{'DRY_RUN' if result.dry_run else 'DELETE'} "
            f"{candidate.target_name} "
            f"age={candidate.age_hours:.1f}h "
            f"size={format_bytes(candidate.size_bytes)} "
            f"path={candidate.path}"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean up old DATA_ENGINE realtime raw snapshot parquet files.",
    )
    parser.add_argument(
        "--ai-root",
        type=Path,
        default=AI_ROOT,
        help="AI project root. Defaults to the root inferred from this file.",
    )
    parser.add_argument(
        "--retention-hours",
        type=float,
        default=DEFAULT_RETENTION_HOURS,
        help="Keep realtime raw snapshots newer than this many hours.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete cleanup candidates. Omitted by default for dry-run.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    targets = build_retention_targets(args.ai_root)
    result = run_cleanup(
        targets,
        retention_hours=args.retention_hours,
        yes=args.yes,
    )
    print_cleanup_result(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
