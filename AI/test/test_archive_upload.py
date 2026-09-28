import re
import time
from pathlib import Path

import pytest

from DATA_ENGINE.archive.manifest import append_manifest_record, has_successful_archive
from DATA_ENGINE.archive.storage import drive_client
from DATA_ENGINE.archive.targets import ArchiveDataset, discover_archive_targets
from DATA_ENGINE.archive.upload_raw_partitions import (
    build_manifest_record,
    drive_destination_for_target,
    main,
    snapshot_files,
    sync_partition_to_drive,
)

DRIVE_ENV_KEYS = [
    "DATA_ENGINE_DRIVE_AUTH_MODE",
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    "GOOGLE_OAUTH_TOKEN_FILE",
    "GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID",
    "GOOGLE_DRIVE_BIKE_ARCHIVE_ROOT_FOLDER_ID",
    "GOOGLE_DRIVE_WEATHER_ARCHIVE_ROOT_FOLDER_ID",
    "GOOGLE_DRIVE_SUBWAY_ARCHIVE_ROOT_FOLDER_ID",
    "GOOGLE_DRIVE_BIKE_ARCHIVE_ROOT_LEVEL",
    "GOOGLE_DRIVE_WEATHER_ARCHIVE_ROOT_LEVEL",
    "GOOGLE_DRIVE_SUBWAY_ARCHIVE_ROOT_LEVEL",
]


@pytest.fixture(autouse=True)
def _fake_media_upload(monkeypatch):
    """실제 googleapiclient `MediaFileUpload` 대신 로컬 Path를 그대로 media_body로
    넘긴다 — FakeDriveService.create()가 업로드된 파일의 size/md5를 계산하려면
    로컬 경로가 필요하다(test_drive_client.py의 기존 패턴과 동일)."""
    monkeypatch.setattr(drive_client, "_media_file_upload", lambda path: Path(path))


@pytest.fixture(autouse=True)
def _isolated_drive_env(monkeypatch):
    """개발 머신 상위 폴더의 실제 `.env`(`DATA_ENGINE.collect.common`이 import 시점에
    무조건 `load_dotenv()`로 읽어들인다)가 os.environ을 오염시켜, 이 값들을 명시적으로
    지우지 않는 테스트가 실제 Drive 폴더 ID를 보게 되는 문제가 있었다. 매 테스트마다
    관련 키를 전부 지워 환경에 관계없이 결정적으로 동작하게 한다."""
    for key in DRIVE_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


class FakeRequest:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class FakeDriveFilesResource:
    def __init__(self):
        self.next_id = 1
        self.children: dict[str, list[dict]] = {}

    def new_id(self) -> str:
        file_id = f"id-{self.next_id}"
        self.next_id += 1
        return file_id

    def list(
        self,
        *,
        q,
        spaces,
        includeItemsFromAllDrives,
        supportsAllDrives,
        fields,
        pageSize,
        pageToken=None,
    ):
        parent = re.search(r"'([^']*)' in parents", q).group(1)
        name_match = re.search(r"name = '([^']*)'", q)
        mime_match = re.search(r"mimeType = '([^']*)'", q)
        items = list(self.children.get(parent, []))
        if name_match:
            items = [item for item in items if item["name"] == name_match.group(1)]
        if mime_match:
            items = [item for item in items if item.get("mimeType") == mime_match.group(1)]
        return FakeRequest({"files": items})

    def create(self, *, body, supportsAllDrives, fields, media_body=None):
        file_id = self.new_id()
        name = body["name"]
        parent = body["parents"][0]
        record: dict[str, str] = {"id": file_id, "name": name}
        mime_type = body.get("mimeType")
        if mime_type:
            record["mimeType"] = mime_type
        if media_body is not None:
            local_path = Path(media_body)
            record["size"] = str(local_path.stat().st_size)
            record["md5Checksum"] = drive_client.file_md5(local_path)
        self.children.setdefault(parent, []).append(record)
        return FakeRequest({"id": file_id, "name": name})


class FakeDriveService:
    def __init__(self):
        self.files_resource = FakeDriveFilesResource()

    def files(self):
        return self.files_resource


def seed_folder_path(service: FakeDriveService, root_id: str, relative_path: str) -> str:
    parent_id = root_id
    for part in Path(relative_path).parts:
        existing = next(
            (
                item
                for item in service.files_resource.children.get(parent_id, [])
                if item["name"] == part
                and item.get("mimeType") == drive_client.DRIVE_FOLDER_MIME_TYPE
            ),
            None,
        )
        if existing is None:
            file_id = service.files_resource.new_id()
            record = {
                "id": file_id,
                "name": part,
                "mimeType": drive_client.DRIVE_FOLDER_MIME_TYPE,
            }
            service.files_resource.children.setdefault(parent_id, []).append(record)
            service.files_resource.children.setdefault(file_id, [])
            parent_id = file_id
        else:
            parent_id = existing["id"]
    return parent_id


def seed_file(service: FakeDriveService, folder_id: str, local_path: Path) -> None:
    service.files_resource.children.setdefault(folder_id, []).append(
        {
            "id": service.files_resource.new_id(),
            "name": local_path.name,
            "size": str(local_path.stat().st_size),
            "md5Checksum": drive_client.file_md5(local_path),
        }
    )


def discover_single_target(
    dataset_name: str,
    base_path: Path,
    archive_prefix: str,
    *,
    current_slot: tuple[str, str] = ("2026-09-13", "05"),
):
    return discover_archive_targets(
        [ArchiveDataset(dataset_name, base_path, Path(archive_prefix))],
        older_than_hours=0,
        current_slot=current_slot,
    )[0]


@pytest.fixture(autouse=True)
def _stable_archive_clock(monkeypatch):
    """이 파일의 테스트는 전부 `older_than_hours=0`으로 방금 쓴 파일의 mtime과
    now_ts를 여유 없이 비교한다 — 파일시스템 mtime 해상도·clock skew로 아주
    드물게 mtime이 now_ts를 앞질러 파티션이 통째로 걸러지는 레이스가 있었다
    (S15P21A104-132 도입 당시 플레이키, S15P21A104-195 병합 중 발견).
    now_ts가 호출 시점마다 실제 현재 시각보다 5초 미래로 이동해 그 레이스를 없앤다.
    패치 전에 원본 time.time을 real_time으로 캡처해둔다 — targets.py의 time과
    이 파일의 time은 같은 모듈 객체라, 패치 후 lambda 안에서 time.time()을 다시
    부르면 패치된 자기 자신을 호출하는 무한 재귀가 된다."""
    real_time = time.time
    monkeypatch.setattr(
        "DATA_ENGINE.archive.targets.time.time",
        lambda: real_time() + 5,
    )


def write_snapshot(path: Path, *, size: int = 10) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_snapshot_files_returns_only_snapshot_parquet(tmp_path):
    partition = tmp_path / "dt=2026-09-13/hh=04"
    first = write_snapshot(partition / "snapshot_1.parquet")
    write_snapshot(partition / "other.parquet")

    class Target:
        local_path = partition

    assert snapshot_files(Target()) == [first]


def test_build_manifest_record_uses_ai_relative_local_path(tmp_path):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet", size=7)
    target = ArchiveDataset("bike", base_path, Path("BIKE/raw/realtime"))
    discovered = __import__(
        "DATA_ENGINE.archive.targets",
        fromlist=["discover_archive_targets"],
    ).discover_archive_targets([target], older_than_hours=0, current_slot=("2026-09-13", "05"),)[0]

    record = build_manifest_record(discovered, ai_root=tmp_path, backend="drive", status="success")

    assert record.local_path == "data/BIKE/raw/realtime/dt=2026-09-13/hh=04"
    assert record.archive_backend == "drive"
    assert record.status == "success"


def test_drive_destination_uses_dataset_root_and_strips_bike_prefix(tmp_path):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet", size=7)
    target = __import__(
        "DATA_ENGINE.archive.targets",
        fromlist=["discover_archive_targets"],
    ).discover_archive_targets(
        [ArchiveDataset("bike", base_path, Path("BIKE/raw/realtime"))],
        older_than_hours=0,
        current_slot=("2026-09-13", "05"),
    )[
        0
    ]

    root_id, archive_path = drive_destination_for_target(
        target,
        {"default": "data-root", "bike": "bike-root"},
    )

    assert root_id == "bike-root"
    assert archive_path == "raw/realtime/dt=2026-09-13/hh=04"


def test_drive_destination_supports_bike_raw_root_level(tmp_path, monkeypatch):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet", size=7)
    target = __import__(
        "DATA_ENGINE.archive.targets",
        fromlist=["discover_archive_targets"],
    ).discover_archive_targets(
        [ArchiveDataset("bike", base_path, Path("BIKE/raw/realtime"))],
        older_than_hours=0,
        current_slot=("2026-09-13", "05"),
    )[
        0
    ]
    monkeypatch.setenv("GOOGLE_DRIVE_BIKE_ARCHIVE_ROOT_LEVEL", "raw")

    root_id, archive_path = drive_destination_for_target(
        target,
        {"default": "data-root", "bike": "bike-raw-root"},
    )

    assert root_id == "bike-raw-root"
    assert archive_path == "realtime/dt=2026-09-13/hh=04"


def test_drive_destination_supports_bike_realtime_root_level(tmp_path, monkeypatch):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet", size=7)
    target = __import__(
        "DATA_ENGINE.archive.targets",
        fromlist=["discover_archive_targets"],
    ).discover_archive_targets(
        [ArchiveDataset("bike", base_path, Path("BIKE/raw/realtime"))],
        older_than_hours=0,
        current_slot=("2026-09-13", "05"),
    )[
        0
    ]
    monkeypatch.setenv("GOOGLE_DRIVE_BIKE_ARCHIVE_ROOT_LEVEL", "realtime")

    root_id, archive_path = drive_destination_for_target(
        target,
        {"default": "data-root", "bike": "bike-realtime-root"},
    )

    assert root_id == "bike-realtime-root"
    assert archive_path == "dt=2026-09-13/hh=04"


def test_drive_destination_supports_subway_arrival_root_level(tmp_path, monkeypatch):
    base_path = tmp_path / "data/SUBWAY/raw/arrival"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet", size=7)
    target = __import__(
        "DATA_ENGINE.archive.targets",
        fromlist=["discover_archive_targets"],
    ).discover_archive_targets(
        [ArchiveDataset("subway", base_path, Path("SUBWAY/raw/arrival"))],
        older_than_hours=0,
        current_slot=("2026-09-13", "05"),
    )[
        0
    ]
    monkeypatch.setenv("GOOGLE_DRIVE_SUBWAY_ARCHIVE_ROOT_LEVEL", "arrival")

    root_id, archive_path = drive_destination_for_target(
        target,
        {"default": "data-root", "subway": "subway-arrival-root"},
    )

    assert root_id == "subway-arrival-root"
    assert archive_path == "dt=2026-09-13/hh=04"


def test_drive_destination_falls_back_to_default_root(tmp_path):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet", size=7)
    target = __import__(
        "DATA_ENGINE.archive.targets",
        fromlist=["discover_archive_targets"],
    ).discover_archive_targets(
        [ArchiveDataset("bike", base_path, Path("BIKE/raw/realtime"))],
        older_than_hours=0,
        current_slot=("2026-09-13", "05"),
    )[
        0
    ]

    root_id, archive_path = drive_destination_for_target(target, {"default": "data-root"})

    assert root_id == "data-root"
    assert archive_path == "BIKE/raw/realtime/dt=2026-09-13/hh=04"


def test_main_dry_run_does_not_require_drive_env_or_manifest_write(tmp_path, monkeypatch, capsys):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet")
    manifest_path = tmp_path / "data/manifest/archive_uploads.jsonl"
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.delenv("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID", raising=False)

    result = main(
        [
            "--ai-root",
            str(tmp_path),
            "--dataset",
            "bike",
            "--older-than-hours",
            "0",
            "--manifest-path",
            str(manifest_path),
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "dry_run=true" in output
    assert "DRY_RUN bike" in output
    assert not manifest_path.exists()


def test_main_treats_success_partition_as_backfill_candidate_in_dry_run(tmp_path, capsys):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet")
    manifest_path = tmp_path / "archive_uploads.jsonl"
    target = discover_single_target("bike", base_path, "BIKE/raw/realtime")
    append_manifest_record(
        manifest_path,
        build_manifest_record(target, ai_root=tmp_path, backend="drive", status="success"),
    )

    result = main(
        [
            "--ai-root",
            str(tmp_path),
            "--dataset",
            "bike",
            "--older-than-hours",
            "0",
            "--manifest-path",
            str(manifest_path),
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    # 드라이런은 자격 증명 없이 동작해야 해서 Drive를 조회하지 않는다 — 이미 성공
    # 기록된 파티션은 "보강 대상"으로만 구분해 보여주고, 실제 누락 파일 여부는
    # --yes 실행에서만 확인한다.
    assert "targets=0" in output
    assert "backfill_candidates=1" in output
    assert "BACKFILL_DRY_RUN bike" in output


def test_main_upload_records_success_manifest(tmp_path, monkeypatch):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet")
    manifest_path = tmp_path / "archive_uploads.jsonl"
    uploaded = []

    def fake_upload_targets(
        planned_targets,
        *,
        ai_root,
        manifest_path,
        drive_auth_mode,
        service_account_file,
        oauth_token_file,
        drive_root_folder_ids,
        backend,
    ):
        assert drive_auth_mode == "service_account"
        assert service_account_file == tmp_path / "service-account.json"
        assert oauth_token_file is None
        assert drive_root_folder_ids == {"default": "root"}
        uploaded.extend(planned_targets)
        for planned in planned_targets:
            append_manifest_record(
                manifest_path,
                build_manifest_record(
                    planned.target, ai_root=ai_root, backend=backend, status="success"
                ),
            )
        return 0

    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(tmp_path / "service-account.json"))
    monkeypatch.setenv("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID", "root")
    monkeypatch.setattr(
        "DATA_ENGINE.archive.upload_raw_partitions.upload_targets", fake_upload_targets
    )

    result = main(
        [
            "--ai-root",
            str(tmp_path),
            "--dataset",
            "bike",
            "--older-than-hours",
            "0",
            "--manifest-path",
            str(manifest_path),
            "--yes",
        ]
    )

    assert result == 0
    assert len(uploaded) == 1
    assert has_successful_archive(manifest_path, "bike", "2026-09-13", "04")


def test_main_upload_returns_failure_when_upload_fails(tmp_path, monkeypatch):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet")
    manifest_path = tmp_path / "archive_uploads.jsonl"

    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(tmp_path / "service-account.json"))
    monkeypatch.setenv("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID", "root")
    monkeypatch.setattr(
        "DATA_ENGINE.archive.upload_raw_partitions.upload_targets", lambda *args, **kwargs: 1
    )

    result = main(
        [
            "--ai-root",
            str(tmp_path),
            "--dataset",
            "bike",
            "--older-than-hours",
            "0",
            "--manifest-path",
            str(manifest_path),
            "--yes",
        ]
    )

    assert result == 1


def test_main_requires_drive_env_only_for_yes(tmp_path, monkeypatch):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet")
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.setenv("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID", "root")

    with pytest.raises(RuntimeError, match="GOOGLE_SERVICE_ACCOUNT_FILE is empty"):
        main(
            [
                "--ai-root",
                str(tmp_path),
                "--dataset",
                "bike",
                "--older-than-hours",
                "0",
                "--yes",
            ]
        )


def test_main_supports_oauth_token_file_for_yes(tmp_path, monkeypatch):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet")
    manifest_path = tmp_path / "archive_uploads.jsonl"
    seen = {}

    def fake_upload_targets(
        targets,
        *,
        ai_root,
        manifest_path,
        drive_auth_mode,
        service_account_file,
        oauth_token_file,
        drive_root_folder_ids,
        backend,
    ):
        seen["target_count"] = len(targets)
        seen["drive_auth_mode"] = drive_auth_mode
        seen["service_account_file"] = service_account_file
        seen["oauth_token_file"] = oauth_token_file
        seen["drive_root_folder_ids"] = drive_root_folder_ids
        return 0

    monkeypatch.setenv("DATA_ENGINE_DRIVE_AUTH_MODE", "oauth")
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_FILE", str(tmp_path / "token.json"))
    monkeypatch.setenv("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID", "root")
    monkeypatch.setattr(
        "DATA_ENGINE.archive.upload_raw_partitions.upload_targets", fake_upload_targets
    )

    result = main(
        [
            "--ai-root",
            str(tmp_path),
            "--dataset",
            "bike",
            "--older-than-hours",
            "0",
            "--manifest-path",
            str(manifest_path),
            "--yes",
        ]
    )

    assert result == 0
    assert seen["target_count"] == 1
    assert seen["drive_auth_mode"] == "oauth"
    assert seen["service_account_file"] is None
    assert seen["oauth_token_file"] == tmp_path / "token.json"
    assert seen["drive_root_folder_ids"] == {"default": "root"}


def test_main_passes_bike_dataset_root_folder_id(tmp_path, monkeypatch, capsys):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet")

    monkeypatch.setenv("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID", "data-root")
    monkeypatch.setenv("GOOGLE_DRIVE_BIKE_ARCHIVE_ROOT_FOLDER_ID", "bike-root")

    result = main(
        [
            "--ai-root",
            str(tmp_path),
            "--dataset",
            "bike",
            "--older-than-hours",
            "0",
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "archive=raw/realtime/dt=2026-09-13/hh=04" in output


def test_main_passes_subway_dataset_root_folder_id(tmp_path, monkeypatch, capsys):
    base_path = tmp_path / "data/SUBWAY/raw/arrival"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet")

    monkeypatch.setenv("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID", "data-root")
    monkeypatch.setenv("GOOGLE_DRIVE_SUBWAY_ARCHIVE_ROOT_FOLDER_ID", "subway-root")

    result = main(
        [
            "--ai-root",
            str(tmp_path),
            "--dataset",
            "subway",
            "--older-than-hours",
            "0",
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "DRY_RUN subway" in output
    assert "archive=raw/arrival/dt=2026-09-13/hh=04" in output


def test_sync_partition_uploads_missing_files_and_creates_folder(tmp_path):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet")
    target = discover_single_target("bike", base_path, "BIKE/raw/realtime")
    service = FakeDriveService()

    outcome = sync_partition_to_drive(service, target, {"default": "root"})

    assert outcome.uploaded == ["snapshot_1.parquet"]
    assert outcome.verified == []
    assert outcome.conflicts == []
    assert outcome.ok


def test_sync_partition_skips_file_already_verified_on_drive(tmp_path):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    local_file = write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet")
    target = discover_single_target("bike", base_path, "BIKE/raw/realtime")
    service = FakeDriveService()
    folder_id = seed_folder_path(service, "root", "BIKE/raw/realtime/dt=2026-09-13/hh=04")
    seed_file(service, folder_id, local_file)

    outcome = sync_partition_to_drive(service, target, {"default": "root"})

    assert outcome.uploaded == []
    assert outcome.verified == ["snapshot_1.parquet"]
    assert outcome.ok
    # 이미 검증된 파일을 다시 올리지 않아 Drive에 중복 객체가 생기지 않는다.
    assert len(service.files_resource.children[folder_id]) == 1


def test_sync_partition_uploads_only_missing_file_in_partially_backed_up_partition(tmp_path):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    backed_up = write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet", size=10)
    missing = write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_2.parquet", size=20)
    target = discover_single_target("bike", base_path, "BIKE/raw/realtime")
    service = FakeDriveService()
    folder_id = seed_folder_path(service, "root", "BIKE/raw/realtime/dt=2026-09-13/hh=04")
    seed_file(service, folder_id, backed_up)

    outcome = sync_partition_to_drive(service, target, {"default": "root"})

    assert outcome.uploaded == [missing.name]
    assert outcome.verified == [backed_up.name]
    assert outcome.ok


def test_sync_partition_flags_conflict_without_reuploading(tmp_path):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet", size=10)
    target = discover_single_target("bike", base_path, "BIKE/raw/realtime")
    service = FakeDriveService()
    folder_id = seed_folder_path(service, "root", "BIKE/raw/realtime/dt=2026-09-13/hh=04")
    # 이름은 같지만 크기가 다른 파일이 이미 Drive에 있는 상황(충돌).
    service.files_resource.children[folder_id].append(
        {"id": "conflict-id", "name": "snapshot_1.parquet", "size": "999", "md5Checksum": "x"}
    )

    outcome = sync_partition_to_drive(service, target, {"default": "root"})

    assert outcome.uploaded == []
    assert outcome.conflicts == ["snapshot_1.parquet:size_mismatch"]
    assert not outcome.ok
    # 충돌을 안전 백업으로 간주하지 않지만, 같은 이름으로 다시 올려 중복 객체를
    # 만들지도 않는다.
    assert len(service.files_resource.children[folder_id]) == 1


def test_main_full_upload_then_rerun_is_idempotent_and_backfills_new_file(tmp_path, monkeypatch):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet")
    manifest_path = tmp_path / "archive_uploads.jsonl"
    service = FakeDriveService()

    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(tmp_path / "service-account.json"))
    monkeypatch.setenv("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID", "root")
    monkeypatch.setattr(
        "DATA_ENGINE.archive.storage.drive_client.build_drive_service", lambda **_: service
    )

    argv = [
        "--ai-root",
        str(tmp_path),
        "--dataset",
        "bike",
        "--older-than-hours",
        "0",
        "--manifest-path",
        str(manifest_path),
        "--yes",
    ]

    # 1) 최초 업로드 → 성공 기록.
    assert main(argv) == 0
    assert has_successful_archive(manifest_path, "bike", "2026-09-13", "04")
    records_after_first_upload = manifest_path.read_text(encoding="utf-8").splitlines()
    assert len(records_after_first_upload) == 1
    folder_id = seed_folder_path(service, "root", "BIKE/raw/realtime/dt=2026-09-13/hh=04")
    assert len(service.files_resource.children[folder_id]) == 1

    # 2) 재실행(변경 없음) → 이미 success 파티션이고 새로 올릴 파일도 없으니
    #    manifest에 다시 쓰지 않는다.
    assert main(argv) == 0
    records_after_noop_rerun = manifest_path.read_text(encoding="utf-8").splitlines()
    assert len(records_after_noop_rerun) == 1

    # 3) 같은 파티션에 파일 추가 후 재실행 → 추가된 파일만 백필 업로드되고
    #    manifest에 success가 다시 기록된다.
    write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_2.parquet")
    assert main(argv) == 0
    records_after_backfill = manifest_path.read_text(encoding="utf-8").splitlines()
    assert len(records_after_backfill) == 2
    assert has_successful_archive(manifest_path, "bike", "2026-09-13", "04")
    assert len(service.files_resource.children[folder_id]) == 2

    # 4) 중복 없는 재실행 — 두 파일 다 이미 검증되어 있으니 Drive에 새 객체가
    #    생기지 않고 manifest도 늘어나지 않는다.
    assert main(argv) == 0
    records_after_final_rerun = manifest_path.read_text(encoding="utf-8").splitlines()
    assert len(records_after_final_rerun) == 2
    assert len(service.files_resource.children[folder_id]) == 2


def test_main_partial_upload_failure_does_not_record_success_and_retries_only_failed_file(
    tmp_path, monkeypatch
):
    base_path = tmp_path / "data/BIKE/raw/realtime"
    ok_file = write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_1.parquet")
    bad_file = write_snapshot(base_path / "dt=2026-09-13/hh=04/snapshot_2.parquet")
    manifest_path = tmp_path / "archive_uploads.jsonl"
    service = FakeDriveService()

    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(tmp_path / "service-account.json"))
    monkeypatch.setenv("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID", "root")
    monkeypatch.setattr(
        "DATA_ENGINE.archive.storage.drive_client.build_drive_service", lambda **_: service
    )

    real_upload_file = drive_client.upload_file

    def flaky_upload_file(service_, folder_id, local_file, **kwargs):
        if local_file.name == bad_file.name:
            raise RuntimeError("simulated upload failure")
        return real_upload_file(service_, folder_id, local_file, **kwargs)

    monkeypatch.setattr("DATA_ENGINE.archive.storage.drive_client.upload_file", flaky_upload_file)

    argv = [
        "--ai-root",
        str(tmp_path),
        "--dataset",
        "bike",
        "--older-than-hours",
        "0",
        "--manifest-path",
        str(manifest_path),
        "--yes",
    ]

    result = main(argv)

    assert result == 1
    assert not has_successful_archive(manifest_path, "bike", "2026-09-13", "04")
    folder_id = seed_folder_path(service, "root", "BIKE/raw/realtime/dt=2026-09-13/hh=04")
    uploaded_names = {item["name"] for item in service.files_resource.children[folder_id]}
    assert uploaded_names == {ok_file.name}

    # 재시도: 이미 올라간 파일은 다시 올리지 않고, 실패했던 파일만 다시 시도한다.
    monkeypatch.setattr("DATA_ENGINE.archive.storage.drive_client.upload_file", real_upload_file)
    assert main(argv) == 0
    assert has_successful_archive(manifest_path, "bike", "2026-09-13", "04")
    uploaded_names_after_retry = {
        item["name"] for item in service.files_resource.children[folder_id]
    }
    assert uploaded_names_after_retry == {ok_file.name, bad_file.name}
    assert len(service.files_resource.children[folder_id]) == 2
