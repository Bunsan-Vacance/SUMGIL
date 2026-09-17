"""Clean up old DATA_ENGINE realtime raw snapshot files."""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from DATA_ENGINE.archive.manifest import (
    DEFAULT_ARCHIVE_BACKEND,
    DEFAULT_MANIFEST_PATH,
    has_successful_archive,
)
from DATA_ENGINE.archive.storage.drive_client import (
    DRIVE_FOLDER_MIME_TYPE,
    build_drive_service,
    file_md5,
    find_folder_path,
    list_folder_files,
)
from DATA_ENGINE.archive.targets import build_archive_datasets
from DATA_ENGINE.archive.upload_raw_partitions import (
    build_drive_root_folder_ids,
    drive_destination_for_partition,
)
from DATA_ENGINE.collect.common import KST

AI_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RETENTION_HOURS = 48
DEFAULT_BIKE_BASE = Path("data/BIKE/raw/realtime")
DEFAULT_WEATHER_BASE = Path("data/EXTERNAL/weather/raw/nowcast")
DEFAULT_SUBWAY_BASE = Path("data/SUBWAY/raw/arrival")
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
    mtime_ns: int | None = None
    verified_md5: str | None = None

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


@dataclass(frozen=True)
class ArchiveFileVerification:
    reason: str | None
    md5: str | None = None


class DriveArchiveVerifier:
    def __init__(self, ai_root: Path):
        self.ai_root = ai_root
        self.service = None
        self.folder_files: dict[tuple[str, str, str], list[dict[str, str]]] = {}
        self.prefixes = {
            dataset.name: dataset.archive_prefix.as_posix()
            for dataset in build_archive_datasets(ai_root)
        }

    def __call__(self, dataset: str, dt: str, hh: str, path: Path) -> ArchiveFileVerification:
        if self.service is None:
            auth_mode = os.environ.get("DATA_ENGINE_DRIVE_AUTH_MODE", "service_account")
            service_account = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "")
            oauth_token = os.environ.get("GOOGLE_OAUTH_TOKEN_FILE", "")
            self.service = build_drive_service(
                auth_mode=auth_mode,
                service_account_file=Path(service_account) if service_account else None,
                oauth_token_file=Path(oauth_token) if oauth_token else None,
            )

        key = (dataset, dt, hh)
        if key not in self.folder_files:
            archive_path = f"{self.prefixes[dataset]}/dt={dt}/hh={hh}"
            root_id, relative_path = drive_destination_for_partition(
                dataset, archive_path, build_drive_root_folder_ids()
            )
            if not root_id:
                return ArchiveFileVerification("archive_root_missing")
            folder_id = find_folder_path(self.service, root_id, relative_path)
            self.folder_files[key] = list_folder_files(self.service, folder_id) if folder_id else []

        matches = [
            item
            for item in self.folder_files[key]
            if item.get("name") == path.name and item.get("mimeType") != DRIVE_FOLDER_MIME_TYPE
        ]
        if not matches:
            return ArchiveFileVerification("archive_file_missing")
        if len(matches) != 1:
            return ArchiveFileVerification("archive_file_ambiguous")
        remote = matches[0]
        if "size" not in remote or int(remote["size"]) != path.stat().st_size:
            return ArchiveFileVerification("archive_size_mismatch")
        remote_md5 = remote.get("md5Checksum")
        if not remote_md5:
            return ArchiveFileVerification("archive_checksum_missing")
        local_md5 = file_md5(path)
        if local_md5 != remote_md5:
            return ArchiveFileVerification("archive_checksum_mismatch")
        return ArchiveFileVerification(None, local_md5)


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
        RetentionTarget("subway", ai_root / DEFAULT_SUBWAY_BASE),
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
    ai_root: Path = AI_ROOT,
    verify_archive_file: Callable[[str, str, str, Path], ArchiveFileVerification] | None = None,
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
    if require_archive_success and verify_archive_file is None:
        verify_archive_file = DriveArchiveVerifier(ai_root)
    archive_success: dict[tuple[str, str, str], bool] = {}
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
            partition_key = (target.name, dt, hh)
            if require_archive_success and partition_key not in archive_success:
                archive_success[partition_key] = has_successful_archive(
                    manifest_path, target.name, dt, hh, backend=archive_backend
                )
            if require_archive_success and not archive_success[partition_key]:
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

            verification = ArchiveFileVerification(None)
            if require_archive_success:
                if archive_backend != "drive":
                    verification = ArchiveFileVerification("archive_backend_unsupported")
                else:
                    try:
                        verification = verify_archive_file(target.name, dt, hh, path)
                    except Exception:  # noqa: BLE001 - A failed check must never permit deletion.
                        verification = ArchiveFileVerification("archive_verification_error")
                if verification.reason is not None:
                    skips.append(CleanupSkip(target.name, dt, hh, path, verification.reason))
                    continue

            candidates.append(
                CleanupCandidate(
                    dataset=target.name,
                    dt=dt,
                    hh=hh,
                    path=path,
                    size_bytes=stat.st_size,
                    age_hours=age_hours,
                    mtime_ns=stat.st_mtime_ns,
                    verified_md5=verification.md5,
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
        try:
            current = candidate.path.stat()
            if current.st_size != candidate.size_bytes:
                continue
            if candidate.mtime_ns is not None and current.st_mtime_ns != candidate.mtime_ns:
                continue
            if (
                candidate.verified_md5 is not None
                and file_md5(candidate.path) != candidate.verified_md5
            ):
                continue
        except OSError:
            continue
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
    ai_root: Path = AI_ROOT,
    verify_archive_file: Callable[[str, str, str, Path], ArchiveFileVerification] | None = None,
) -> CleanupResult:
    candidates, skips = find_cleanup_candidates(
        targets,
        retention_hours=retention_hours,
        require_archive_success=require_archive_success,
        manifest_path=manifest_path,
        archive_backend=archive_backend,
        now_ts=now_ts,
        current_slot=current_slot,
        ai_root=ai_root,
        verify_archive_file=verify_archive_file,
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
    load_dotenv(args.ai_root / ".env")
    targets = build_retention_targets(args.ai_root)
    manifest_path = resolve_project_path(args.ai_root, args.manifest_path)
    result = run_cleanup(
        targets,
        retention_hours=args.retention_hours,
        yes=args.yes,
        require_archive_success=args.require_archive_success,
        manifest_path=manifest_path,
        archive_backend=args.archive_backend,
        ai_root=args.ai_root,
    )
    print_cleanup_result(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
