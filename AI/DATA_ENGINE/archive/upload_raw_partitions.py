"""Upload completed DATA_ENGINE raw partitions to archive storage."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from DATA_ENGINE.archive.manifest import (
    DEFAULT_ARCHIVE_BACKEND,
    DEFAULT_MANIFEST_PATH,
    ArchiveManifestRecord,
    append_manifest_record,
    has_successful_archive,
)
from DATA_ENGINE.archive.targets import (
    ArchiveTarget,
    build_archive_datasets,
    discover_archive_targets,
    filter_datasets,
)
from DATA_ENGINE.collect.common import AI_ROOT, KST


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


def snapshot_files(target: ArchiveTarget) -> list[Path]:
    return sorted(path for path in target.local_path.glob("snapshot_*.parquet") if path.is_file())


def resolve_project_path(ai_root: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    return ai_root / path


def build_manifest_record(
    target: ArchiveTarget,
    *,
    ai_root: Path,
    backend: str,
    status: str,
    error: str | None = None,
) -> ArchiveManifestRecord:
    try:
        local_path = target.local_path.relative_to(ai_root).as_posix()
    except ValueError:
        local_path = target.local_path.as_posix()
    return ArchiveManifestRecord(
        dataset=target.dataset,
        dt=target.dt,
        hh=target.hh,
        local_path=local_path,
        archive_backend=backend,
        archive_path=target.archive_path,
        file_count=target.file_count,
        total_bytes=target.total_bytes,
        status=status,
        uploaded_at=datetime.now(KST).isoformat(),
        error=error,
    )


def print_targets(
    targets: Sequence[ArchiveTarget],
    *,
    dry_run: bool,
    backend: str,
    skipped_success: int,
) -> None:
    print(
        "DATA_ENGINE archive upload "
        f"dry_run={str(dry_run).lower()} "
        f"backend={backend} "
        f"targets={len(targets)} "
        f"skipped_success={skipped_success}"
    )
    for target in targets:
        prefix = "DRY_RUN" if dry_run else "UPLOAD"
        print(
            f"{prefix} {target.dataset} "
            f"dt={target.dt} hh={target.hh} "
            f"files={target.file_count} "
            f"size={format_bytes(target.total_bytes)} "
            f"local={target.local_path} "
            f"archive={target.archive_path}"
        )


def upload_targets(
    targets: Sequence[ArchiveTarget],
    *,
    ai_root: Path,
    manifest_path: Path,
    service_account_file: Path,
    drive_root_folder_id: str,
    backend: str,
) -> int:
    from DATA_ENGINE.archive.storage.drive_client import (
        build_drive_service,
        ensure_folder_path,
        upload_file,
    )

    service = build_drive_service(service_account_file)
    failures = 0
    for target in targets:
        try:
            folder_id = ensure_folder_path(service, drive_root_folder_id, target.archive_path)
            for file_path in snapshot_files(target):
                upload_file(service, folder_id, file_path)
            append_manifest_record(
                manifest_path,
                build_manifest_record(target, ai_root=ai_root, backend=backend, status="success"),
            )
        except Exception as exc:  # noqa: BLE001
            # One failed partition should be recorded and let the remaining partitions continue.
            failures += 1
            append_manifest_record(
                manifest_path,
                build_manifest_record(
                    target,
                    ai_root=ai_root,
                    backend=backend,
                    status="failed",
                    error=str(exc),
                ),
            )
            print(
                f"FAIL {target.dataset} dt={target.dt} hh={target.hh} "
                f"archive={target.archive_path} error={exc}",
                file=sys.stderr,
            )
    return failures


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload completed DATA_ENGINE raw snapshot partitions to Google Drive.",
    )
    parser.add_argument("--ai-root", type=Path, default=AI_ROOT)
    parser.add_argument("--dataset", choices=["all", "bike", "weather"], default="all")
    parser.add_argument("--older-than-hours", type=float, default=1)
    parser.add_argument("--max-partitions", type=int, default=24)
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually upload to Drive and append manifest records. Omitted by default for dry-run.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.max_partitions <= 0:
        raise ValueError("max_partitions must be positive")

    ai_root = args.ai_root.resolve()
    load_dotenv(ai_root / ".env")

    backend = (
        os.environ.get("DATA_ENGINE_ARCHIVE_STORAGE")
        or os.environ.get("DATA_ENGINE_ARCHIVE_BACKEND")
        or DEFAULT_ARCHIVE_BACKEND
    )
    if backend != "drive":
        raise ValueError("DATA_ENGINE_ARCHIVE_STORAGE must be drive")

    manifest_path = resolve_project_path(ai_root, args.manifest_path)
    datasets = filter_datasets(build_archive_datasets(ai_root), args.dataset)
    discovered = discover_archive_targets(datasets, older_than_hours=args.older_than_hours)

    skipped_success = 0
    targets: list[ArchiveTarget] = []
    for target in discovered:
        if has_successful_archive(
            manifest_path, target.dataset, target.dt, target.hh, backend=backend
        ):
            skipped_success += 1
            continue
        targets.append(target)
        if len(targets) >= args.max_partitions:
            break

    print_targets(targets, dry_run=not args.yes, backend=backend, skipped_success=skipped_success)
    if not args.yes:
        return 0

    service_account = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    drive_root = os.environ.get("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID", "")
    if not service_account:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_FILE is empty")
    if not drive_root:
        raise RuntimeError("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID is empty")

    failures = upload_targets(
        targets,
        ai_root=ai_root,
        manifest_path=manifest_path,
        service_account_file=Path(service_account),
        drive_root_folder_id=drive_root,
        backend=backend,
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
