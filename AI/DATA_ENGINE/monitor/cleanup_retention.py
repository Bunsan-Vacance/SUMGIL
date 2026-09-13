"""Clean up old DATA_ENGINE realtime raw snapshot files."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from DATA_ENGINE.archive.manifest import (
    DEFAULT_ARCHIVE_BACKEND,
    DEFAULT_MANIFEST_PATH,
    has_successful_archive,
)
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
    dataset: str
    dt: str
    hh: str
    path: Path
    size_bytes: int
    age_hours: float

    @property
    def target_name(self) -> str:
        return self.dataset


@dataclass(frozen=True)
class CleanupSkip:
    dataset: str
    dt: str
    hh: str
    path: Path
    reason: str


@dataclass(frozen=True)
class CleanupResult:
    dry_run: bool
    retention_hours: float
    require_archive_success: bool
    candidates: list[CleanupCandidate]
    skips: list[CleanupSkip]
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


def parse_snapshot_partition(
    target: RetentionTarget,
    path: Path,
) -> tuple[str, str] | None:
    try:
        relative = path.resolve().relative_to(target.base_path.resolve())
    except ValueError:
        return None

    if len(relative.parts) != 3:
        return None

    dt_part, hh_part, filename = relative.parts
    if filename != path.name:
        return None
    if not (dt_part.startswith("dt=") and hh_part.startswith("hh=")):
        return None

    return dt_part.removeprefix("dt="), hh_part.removeprefix("hh=")


def build_retention_targets(ai_root: Path) -> list[RetentionTarget]:
    return [
        RetentionTarget("bike", ai_root / DEFAULT_BIKE_BASE),
        RetentionTarget("weather", ai_root / DEFAULT_WEATHER_BASE),
    ]


def find_cleanup_candidates(
    targets: Iterable[RetentionTarget],
    *,
    retention_hours: float,
    require_archive_success: bool = False,
    manifest_path: Path | None = None,
    archive_backend: str = DEFAULT_ARCHIVE_BACKEND,
    now_ts: float | None = None,
    current_slot: tuple[str, str] | None = None,
) -> tuple[list[CleanupCandidate], list[CleanupSkip]]:
    if retention_hours <= 0:
        raise ValueError("retention_hours must be positive")
    if require_archive_success and manifest_path is None:
        raise ValueError("manifest_path is required when require_archive_success is true")

    if now_ts is None:
        now_ts = time.time()
    if current_slot is None:
        current_slot = current_kst_partition()

    candidates: list[CleanupCandidate] = []
    skips: list[CleanupSkip] = []
    for target in targets:
        if not target.base_path.exists():
            continue
        for path in target.base_path.glob(SNAPSHOT_PATTERN):
            if not path.is_file():
                continue
            if not is_safe_snapshot_path(target, path, current_slot=current_slot):
                continue
            partition = parse_snapshot_partition(target, path)
            if partition is None:
                continue
            dt, hh = partition

            stat = path.stat()
            age_hours = max(0.0, (now_ts - stat.st_mtime) / 3600)
            if age_hours <= retention_hours:
                continue
            if require_archive_success and not has_successful_archive(
                manifest_path,
                target.name,
                dt,
                hh,
                backend=archive_backend,
            ):
                skips.append(
                    CleanupSkip(
                        dataset=target.name,
                        dt=dt,
                        hh=hh,
                        path=path,
                        reason="archive_not_success",
                    )
                )
                continue

            candidates.append(
                CleanupCandidate(
                    dataset=target.name,
                    dt=dt,
                    hh=hh,
                    path=path,
                    size_bytes=stat.st_size,
                    age_hours=age_hours,
                )
            )

    return (
        sorted(candidates, key=lambda candidate: str(candidate.path)),
        sorted(skips, key=lambda skip: str(skip.path)),
    )


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
    require_archive_success: bool = False,
    manifest_path: Path | None = None,
    archive_backend: str = DEFAULT_ARCHIVE_BACKEND,
    now_ts: float | None = None,
    current_slot: tuple[str, str] | None = None,
) -> CleanupResult:
    candidates, skips = find_cleanup_candidates(
        targets,
        retention_hours=retention_hours,
        require_archive_success=require_archive_success,
        manifest_path=manifest_path,
        archive_backend=archive_backend,
        now_ts=now_ts,
        current_slot=current_slot,
    )
    deleted_count, deleted_bytes = cleanup_candidates(candidates, yes=yes)
    return CleanupResult(
        dry_run=not yes,
        retention_hours=retention_hours,
        require_archive_success=require_archive_success,
        candidates=candidates,
        skips=skips,
        deleted_count=deleted_count,
        deleted_bytes=deleted_bytes,
    )


def print_cleanup_result(result: CleanupResult) -> None:
    print(
        "DATA_ENGINE retention cleanup "
        f"dry_run={str(result.dry_run).lower()} "
        f"retention_hours={result.retention_hours:g} "
        f"require_archive_success={str(result.require_archive_success).lower()} "
        f"candidates={len(result.candidates)} "
        f"skipped={len(result.skips)} "
        f"candidate_size={format_bytes(result.candidate_bytes)} "
        f"deleted={result.deleted_count} "
        f"deleted_size={format_bytes(result.deleted_bytes)}"
    )
    for candidate in result.candidates:
        print(
            f"{'DRY_RUN' if result.dry_run else 'DELETE'} "
            f"{candidate.dataset} "
            f"dt={candidate.dt} "
            f"hh={candidate.hh} "
            f"age={candidate.age_hours:.1f}h "
            f"size={format_bytes(candidate.size_bytes)} "
            f"path={candidate.path}"
        )
    for skip in result.skips:
        print(
            f"SKIP {skip.dataset} "
            f"dt={skip.dt} "
            f"hh={skip.hh} "
            f"reason={skip.reason} "
            f"path={skip.path}"
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
    parser.add_argument(
        "--require-archive-success",
        action="store_true",
        help="Delete only partitions whose latest archive manifest status is success.",
    )
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="Archive upload manifest path. Relative paths are resolved from --ai-root.",
    )
    parser.add_argument(
        "--archive-backend",
        default=DEFAULT_ARCHIVE_BACKEND,
        help="Archive backend name to match in the manifest.",
    )
    return parser.parse_args(argv)


def resolve_project_path(ai_root: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    return ai_root / path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    targets = build_retention_targets(args.ai_root)
    manifest_path = resolve_project_path(args.ai_root, args.manifest_path)
    result = run_cleanup(
        targets,
        retention_hours=args.retention_hours,
        yes=args.yes,
        require_archive_success=args.require_archive_success,
        manifest_path=manifest_path,
        archive_backend=args.archive_backend,
    )
    print_cleanup_result(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
