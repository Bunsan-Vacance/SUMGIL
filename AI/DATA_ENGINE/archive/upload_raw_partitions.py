"""Upload completed DATA_ENGINE raw partitions to archive storage."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from DATA_ENGINE.archive.manifest import (
    DEFAULT_ARCHIVE_BACKEND,
    DEFAULT_MANIFEST_PATH,
    ArchiveManifestRecord,
    append_manifest_record,
    has_successful_archive,
    load_manifest_records,
)
from DATA_ENGINE.archive.storage.drive_client import match_local_file
from DATA_ENGINE.archive.targets import (
    ArchiveTarget,
    build_archive_datasets,
    discover_archive_targets,
    filter_datasets,
)
from DATA_ENGINE.collect.common import AI_ROOT, KST
from DATA_ENGINE.monitor.notify_discord import notify_failure

ARCHIVE_ALERT_TITLE = "[DATA_ENGINE] Drive archive 업로드 실패"
MAX_ALERT_LINES = 10

DATASET_ROOT_ENV_KEYS = {
    "bike": "GOOGLE_DRIVE_BIKE_ARCHIVE_ROOT_FOLDER_ID",
    "weather": "GOOGLE_DRIVE_WEATHER_ARCHIVE_ROOT_FOLDER_ID",
    "subway": "GOOGLE_DRIVE_SUBWAY_ARCHIVE_ROOT_FOLDER_ID",
}

DATASET_ARCHIVE_PREFIXES = {
    "bike": "BIKE/",
    "weather": "EXTERNAL/weather/",
    "subway": "SUBWAY/",
}

DATASET_ROOT_LEVEL_ENV_KEYS = {
    "bike": "GOOGLE_DRIVE_BIKE_ARCHIVE_ROOT_LEVEL",
    "weather": "GOOGLE_DRIVE_WEATHER_ARCHIVE_ROOT_LEVEL",
    "subway": "GOOGLE_DRIVE_SUBWAY_ARCHIVE_ROOT_LEVEL",
}

DATASET_ROOT_LEVEL_PREFIXES = {
    "bike": {
        "domain": "BIKE/",
        "raw": "BIKE/raw/",
        "realtime": "BIKE/raw/realtime/",
    },
    "weather": {
        "domain": "EXTERNAL/weather/",
        "raw": "EXTERNAL/weather/raw/",
        "nowcast": "EXTERNAL/weather/raw/nowcast/",
    },
    "subway": {
        "domain": "SUBWAY/",
        "raw": "SUBWAY/raw/",
        "arrival": "SUBWAY/raw/arrival/",
    },
}


@dataclass(frozen=True)
class PlannedTarget:
    target: ArchiveTarget
    is_backfill: bool


@dataclass
class PartitionSyncOutcome:
    uploaded: list[str] = field(default_factory=list)
    verified: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.conflicts and not self.failures


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
    archive_path: str | None = None,
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
        archive_path=archive_path or target.archive_path,
        file_count=target.file_count,
        total_bytes=target.total_bytes,
        status=status,
        uploaded_at=datetime.now(KST).isoformat(),
        error=error,
    )


def print_targets(
    new_targets: Sequence[ArchiveTarget],
    backfill_candidates: Sequence[ArchiveTarget],
    *,
    dry_run: bool,
    backend: str,
    drive_root_folder_ids: dict[str, str],
) -> None:
    print(
        "DATA_ENGINE archive upload "
        f"dry_run={str(dry_run).lower()} "
        f"backend={backend} "
        f"targets={len(new_targets)} "
        f"backfill_candidates={len(backfill_candidates)}"
    )
    for target in new_targets:
        _, archive_path = drive_destination_for_target(target, drive_root_folder_ids)
        prefix = "DRY_RUN" if dry_run else "UPLOAD"
        print(
            f"{prefix} {target.dataset} "
            f"dt={target.dt} hh={target.hh} "
            f"files={target.file_count} "
            f"size={format_bytes(target.total_bytes)} "
            f"local={target.local_path} "
            f"archive={archive_path}"
        )
    for target in backfill_candidates:
        _, archive_path = drive_destination_for_target(target, drive_root_folder_ids)
        # 이미 success로 기록된 파티션이라 여기서는 Drive를 조회하지 않는다(드라이런은
        # 자격 증명 없이도 동작해야 함) — 실제 누락 파일 여부는 --yes 실행에서만 확인한다.
        prefix = "BACKFILL_DRY_RUN" if dry_run else "BACKFILL_CHECK"
        print(
            f"{prefix} {target.dataset} "
            f"dt={target.dt} hh={target.hh} "
            f"files={target.file_count} "
            f"size={format_bytes(target.total_bytes)} "
            f"local={target.local_path} "
            f"archive={archive_path}"
        )


def strip_archive_prefix(archive_path: str, prefix: str) -> str:
    return archive_path.removeprefix(prefix)


def dataset_root_level(dataset: str) -> str:
    env_key = DATASET_ROOT_LEVEL_ENV_KEYS[dataset]
    return os.environ.get(env_key, "domain")


def dataset_archive_prefix(dataset: str) -> str:
    root_level = dataset_root_level(dataset)
    try:
        return DATASET_ROOT_LEVEL_PREFIXES[dataset][root_level]
    except KeyError as exc:
        allowed = ", ".join(sorted(DATASET_ROOT_LEVEL_PREFIXES[dataset]))
        raise ValueError(
            f"{DATASET_ROOT_LEVEL_ENV_KEYS[dataset]} must be one of: {allowed}"
        ) from exc


def drive_destination_for_target(
    target: ArchiveTarget,
    drive_root_folder_ids: dict[str, str],
) -> tuple[str, str]:
    return drive_destination_for_partition(
        target.dataset, target.archive_path, drive_root_folder_ids
    )


def drive_destination_for_partition(
    dataset: str,
    archive_path: str,
    drive_root_folder_ids: dict[str, str],
) -> tuple[str, str]:
    dataset_root = drive_root_folder_ids.get(dataset, "")
    if dataset_root:
        prefix = dataset_archive_prefix(dataset)
        return dataset_root, strip_archive_prefix(archive_path, prefix)
    return drive_root_folder_ids.get("default", ""), archive_path


def build_drive_root_folder_ids() -> dict[str, str]:
    root_ids = {"default": os.environ.get("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID", "")}
    for dataset, env_key in DATASET_ROOT_ENV_KEYS.items():
        value = os.environ.get(env_key, "")
        if value:
            root_ids[dataset] = value
    return root_ids


def sync_partition_to_drive(
    service,
    target: ArchiveTarget,
    drive_root_folder_ids: dict[str, str],
) -> PartitionSyncOutcome:
    """로컬 파티션의 파일들을 Drive와 대조해 누락된 파일만 올린다.

    이름이 같지만 크기·체크섬이 다른 파일은 정상 백업으로 보지 않고 conflicts에 남긴다
    (동일 이름으로 다시 올리면 Drive에 중복 객체가 생기므로 자동 업로드하지 않는다).
    """
    from DATA_ENGINE.archive.storage.drive_client import (
        ensure_folder_path,
        find_folder_path,
        list_folder_files,
        upload_file,
    )

    drive_root_folder_id, archive_path = drive_destination_for_target(target, drive_root_folder_ids)
    if not drive_root_folder_id:
        raise RuntimeError(f"Drive root folder id is empty for dataset={target.dataset}")

    existing_folder_id = find_folder_path(service, drive_root_folder_id, archive_path)
    remote_files = list_folder_files(service, existing_folder_id) if existing_folder_id else []

    outcome = PartitionSyncOutcome()
    to_upload: list[Path] = []
    for local_file in snapshot_files(target):
        status = match_local_file(local_file, remote_files)
        if status == "missing":
            to_upload.append(local_file)
        elif status == "verified":
            outcome.verified.append(local_file.name)
        else:
            outcome.conflicts.append(f"{local_file.name}:{status}")

    if to_upload:
        folder_id = ensure_folder_path(service, drive_root_folder_id, archive_path)
        for local_file in to_upload:
            try:
                upload_file(service, folder_id, local_file)
                outcome.uploaded.append(local_file.name)
            except Exception as exc:  # noqa: BLE001
                outcome.failures.append(f"{local_file.name}: {exc}")

    return outcome


def upload_targets(
    planned_targets: Sequence[PlannedTarget],
    *,
    ai_root: Path,
    manifest_path: Path,
    drive_auth_mode: str,
    service_account_file: Path | None,
    oauth_token_file: Path | None,
    drive_root_folder_ids: dict[str, str],
    backend: str,
) -> int:
    from DATA_ENGINE.archive.storage.drive_client import build_drive_service

    service = build_drive_service(
        auth_mode=drive_auth_mode,
        service_account_file=service_account_file,
        oauth_token_file=oauth_token_file,
    )
    failures = 0
    for planned in planned_targets:
        target = planned.target
        label = "BACKFILL" if planned.is_backfill else "UPLOAD"
        _, archive_path = drive_destination_for_target(target, drive_root_folder_ids)
        try:
            outcome = sync_partition_to_drive(service, target, drive_root_folder_ids)
        except Exception as exc:  # noqa: BLE001
            # One failed partition should be recorded and let the remaining partitions continue.
            failures += 1
            append_manifest_record(
                manifest_path,
                build_manifest_record(
                    target,
                    ai_root=ai_root,
                    backend=backend,
                    archive_path=archive_path,
                    status="failed",
                    error=str(exc),
                ),
            )
            print(
                f"FAIL {target.dataset} dt={target.dt} hh={target.hh} error={exc}",
                file=sys.stderr,
            )
            continue

        # 이미 success로 기록된 파티션인데 새로 올린 파일도, 새로 발견된 충돌도 없으면
        # manifest에 다시 쓰지 않는다 — 매번 같은 기록을 반복해 manifest가 불어나는 것을 막는다.
        if (
            planned.is_backfill
            and not outcome.uploaded
            and not outcome.conflicts
            and not outcome.failures
        ):
            print(
                f"{label}_SKIP {target.dataset} dt={target.dt} hh={target.hh} "
                f"already_verified={len(outcome.verified)}"
            )
            continue

        status = "success" if outcome.ok else "failed"
        if status == "failed":
            failures += 1
        append_manifest_record(
            manifest_path,
            build_manifest_record(
                target,
                ai_root=ai_root,
                backend=backend,
                archive_path=archive_path,
                status=status,
                error="; ".join(outcome.conflicts + outcome.failures) or None,
            ),
        )
        print(
            f"{label} {target.dataset} dt={target.dt} hh={target.hh} "
            f"uploaded={len(outcome.uploaded)} verified={len(outcome.verified)} "
            f"conflicts={len(outcome.conflicts)} failures={len(outcome.failures)}"
        )
    return failures


def build_failure_alert(manifest_path: Path, run_started: datetime, failures: int) -> str:
    """List the partitions this run recorded as failed (read back from the manifest)."""
    started = run_started.isoformat()
    lines = [
        f"{record.dataset} dt={record.dt} hh={record.hh} archive={record.archive_path} "
        f"error={record.error}"
        for record in load_manifest_records(manifest_path)
        if record.status == "failed" and record.uploaded_at >= started
    ]
    shown = lines[:MAX_ALERT_LINES]
    if len(lines) > len(shown):
        shown.append(f"... 외 {len(lines) - len(shown)}개 파티션")
    return (
        f"Drive archive 업로드 실패 {failures}건 (manifest에 failed 기록, 다음 실행에서 재시도)\n"
        + "\n".join(shown)
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload completed DATA_ENGINE raw snapshot partitions to Google Drive.",
    )
    parser.add_argument("--ai-root", type=Path, default=AI_ROOT)
    parser.add_argument("--dataset", choices=["all", "bike", "weather", "subway"], default="all")
    parser.add_argument("--older-than-hours", type=float, default=1)
    parser.add_argument("--max-partitions", type=int, default=24)
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually upload to Drive and append manifest records. Omitted by default for dry-run.",
    )
    parser.add_argument(
        "--notify-discord",
        action="store_true",
        help="Send a Discord alert when a partition fails to upload. Silent when all succeed.",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
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

    new_targets: list[ArchiveTarget] = []
    backfill_candidates: list[ArchiveTarget] = []
    for target in discovered:
        if has_successful_archive(
            manifest_path, target.dataset, target.dt, target.hh, backend=backend
        ):
            backfill_candidates.append(target)
        else:
            new_targets.append(target)
    new_targets = new_targets[: args.max_partitions]
    backfill_candidates = backfill_candidates[: args.max_partitions]

    drive_root_folder_ids = build_drive_root_folder_ids()

    print_targets(
        new_targets,
        backfill_candidates,
        dry_run=not args.yes,
        backend=backend,
        drive_root_folder_ids=drive_root_folder_ids,
    )
    if not args.yes:
        return 0

    drive_auth_mode = os.environ.get("DATA_ENGINE_DRIVE_AUTH_MODE", "service_account")
    service_account = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    oauth_token = os.environ.get("GOOGLE_OAUTH_TOKEN_FILE", "")
    if drive_auth_mode == "service_account" and not service_account:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_FILE is empty")
    if drive_auth_mode == "oauth" and not oauth_token:
        raise RuntimeError("GOOGLE_OAUTH_TOKEN_FILE is empty")
    if not any(drive_root_folder_ids.values()):
        raise RuntimeError("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID is empty")

    planned_targets = [PlannedTarget(target, is_backfill=False) for target in new_targets] + [
        PlannedTarget(target, is_backfill=True) for target in backfill_candidates
    ]
    run_started = datetime.now(KST)
    failures = upload_targets(
        planned_targets,
        ai_root=ai_root,
        manifest_path=manifest_path,
        drive_auth_mode=drive_auth_mode,
        service_account_file=Path(service_account) if service_account else None,
        oauth_token_file=Path(oauth_token) if oauth_token else None,
        drive_root_folder_ids=drive_root_folder_ids,
        backend=backend,
    )
    if failures and args.notify_discord:
        notify_failure(
            build_failure_alert(manifest_path, run_started, failures),
            title=ARCHIVE_ALERT_TITLE,
        )
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except Exception as exc:  # 설정 누락·인증 실패 등 전체 중단도 알린 뒤 그대로 올린다.
        if args.notify_discord and args.yes:
            notify_failure(
                f"Drive archive 업로드 중단: {type(exc).__name__}: {exc}",
                title=ARCHIVE_ALERT_TITLE,
            )
        raise


if __name__ == "__main__":
    sys.exit(main())
