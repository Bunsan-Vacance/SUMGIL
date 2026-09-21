"""Drive archive·retention Discord 알림과 subway 대상 end-to-end 동작 테스트."""

import os
import time
from pathlib import Path

import pytest
from test_archive_upload import FakeDriveService, seed_folder_path

from DATA_ENGINE.archive.manifest import ArchiveManifestRecord, append_manifest_record
from DATA_ENGINE.archive.storage import drive_client
from DATA_ENGINE.archive.upload_raw_partitions import main as upload_main
from DATA_ENGINE.monitor import notify_discord
from DATA_ENGINE.monitor.cleanup_retention import (
    DriveArchiveVerifier,
    RetentionTarget,
    build_skip_alert,
    run_cleanup,
)
from DATA_ENGINE.monitor.cleanup_retention import main as retention_main

UPLOAD_MOD = "DATA_ENGINE.archive.upload_raw_partitions"
RETENTION_MOD = "DATA_ENGINE.monitor.cleanup_retention"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in (
        "GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID",
        "GOOGLE_DRIVE_BIKE_ARCHIVE_ROOT_FOLDER_ID",
        "GOOGLE_DRIVE_WEATHER_ARCHIVE_ROOT_FOLDER_ID",
        "GOOGLE_DRIVE_SUBWAY_ARCHIVE_ROOT_FOLDER_ID",
        "GOOGLE_DRIVE_SUBWAY_ARCHIVE_ROOT_LEVEL",
        "DISCORD_WEBHOOK_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(drive_client, "_media_file_upload", lambda path: Path(path))
    real_time = time.time
    monkeypatch.setattr("DATA_ENGINE.archive.targets.time.time", lambda: real_time() + 5)


def make_partition(base: Path, name: str = "snapshot_1.parquet", dt="2026-09-13", hh="04") -> Path:
    path = base / f"dt={dt}" / f"hh={hh}" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * 10)
    return path


def upload_args(tmp_path, dataset="subway", *extra):
    return [
        "--ai-root",
        str(tmp_path),
        "--dataset",
        dataset,
        "--older-than-hours",
        "0",
        "--manifest-path",
        str(tmp_path / "archive.jsonl"),
        "--yes",
        *extra,
    ]


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(f"{UPLOAD_MOD}.notify_failure", lambda d, **kw: calls.append((d, kw)))
    monkeypatch.setattr(f"{RETENTION_MOD}.notify_failure", lambda d, **kw: calls.append((d, kw)))
    return calls


@pytest.fixture
def drive_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_FILE", str(tmp_path / "token.json"))
    monkeypatch.setenv("DATA_ENGINE_DRIVE_AUTH_MODE", "oauth")
    monkeypatch.setenv("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID", "root")


# ---- upload alerts ----


def test_upload_failure_sends_alert_with_partition_and_error(
    tmp_path, monkeypatch, sent, drive_env
):
    make_partition(tmp_path / "data/SUBWAY/raw/arrival")
    service = FakeDriveService()
    monkeypatch.setattr(drive_client, "build_drive_service", lambda **_: service)

    def boom(*_):
        raise OSError("quota exceeded")

    monkeypatch.setattr(drive_client, "upload_file", boom)

    assert upload_main(upload_args(tmp_path, "subway", "--notify-discord")) == 1

    assert len(sent) == 1
    detail, kwargs = sent[0]
    assert "subway dt=2026-09-13 hh=04" in detail
    assert "quota exceeded" in detail
    assert "SUBWAY/raw/arrival" in detail
    assert "업로드 실패" in kwargs["title"]


def test_upload_success_is_silent(tmp_path, monkeypatch, sent, drive_env):
    make_partition(tmp_path / "data/SUBWAY/raw/arrival")
    monkeypatch.setattr(drive_client, "build_drive_service", lambda **_: FakeDriveService())

    assert upload_main(upload_args(tmp_path, "subway", "--notify-discord")) == 0

    assert sent == []


def test_upload_failure_without_flag_does_not_notify(tmp_path, monkeypatch, sent, drive_env):
    make_partition(tmp_path / "data/SUBWAY/raw/arrival")
    monkeypatch.setattr(drive_client, "build_drive_service", lambda **_: FakeDriveService())
    monkeypatch.setattr(drive_client, "upload_file", lambda *_: (_ for _ in ()).throw(OSError("x")))

    assert upload_main(upload_args(tmp_path, "subway")) == 1

    assert sent == []


def test_upload_fatal_error_is_alerted_then_raised(tmp_path, monkeypatch, sent, drive_env):
    make_partition(tmp_path / "data/SUBWAY/raw/arrival")

    def bad_auth(**_):
        raise RuntimeError("token expired")

    monkeypatch.setattr(drive_client, "build_drive_service", bad_auth)

    with pytest.raises(RuntimeError, match="token expired"):
        upload_main(upload_args(tmp_path, "subway", "--notify-discord"))

    assert "token expired" in sent[0][0]


# ---- subway end-to-end ----


def test_subway_partition_uploads_to_drive_and_reruns_idempotently(
    tmp_path, monkeypatch, drive_env
):
    base = tmp_path / "data/SUBWAY/raw/arrival"
    make_partition(base, "snapshot_a.parquet")
    service = FakeDriveService()
    monkeypatch.setattr(drive_client, "build_drive_service", lambda **_: service)

    assert upload_main(upload_args(tmp_path, "subway")) == 0
    folder = seed_folder_path(service, "root", "SUBWAY/raw/arrival/dt=2026-09-13/hh=04")
    names = [item["name"] for item in service.files_resource.children[folder]]
    assert names == ["snapshot_a.parquet"]

    make_partition(base, "snapshot_b.parquet")  # 늦게 도착한 파일
    assert upload_main(upload_args(tmp_path, "subway")) == 0
    names = [item["name"] for item in service.files_resource.children[folder]]
    assert sorted(names) == ["snapshot_a.parquet", "snapshot_b.parquet"]


def test_all_datasets_option_includes_subway(tmp_path, capsys):
    make_partition(tmp_path / "data/SUBWAY/raw/arrival")
    make_partition(tmp_path / "data/BIKE/raw/realtime")
    make_partition(tmp_path / "data/EXTERNAL/weather/raw/nowcast")

    upload_main(
        [
            "--ai-root",
            str(tmp_path),
            "--older-than-hours",
            "0",
            "--manifest-path",
            str(tmp_path / "m.jsonl"),
        ]
    )

    out = capsys.readouterr().out
    for dataset in ("bike", "weather", "subway"):
        assert f"DRY_RUN {dataset}" in out


# ---- retention ----


def record_success(manifest: Path, dataset: str, dt="2026-09-11", hh="03") -> None:
    append_manifest_record(
        manifest,
        ArchiveManifestRecord(
            dataset=dataset,
            dt=dt,
            hh=hh,
            local_path="x",
            archive_backend="drive",
            archive_path="x",
            file_count=1,
            total_bytes=4,
            status="success",
            uploaded_at="2026-09-13T04:05:00+09:00",
        ),
    )


def old_subway_file(tmp_path, name="snapshot_s.parquet") -> Path:
    path = make_partition(tmp_path / "data/SUBWAY/raw/arrival", name, dt="2026-09-11", hh="03")
    stamp = time.time() - 49 * 3600
    os.utime(path, (stamp, stamp))
    return path


def test_subway_retention_deletes_only_drive_verified_files(tmp_path, monkeypatch):
    verified = old_subway_file(tmp_path, "snapshot_ok.parquet")
    unverified = old_subway_file(tmp_path, "snapshot_missing.parquet")
    manifest = tmp_path / "archive.jsonl"
    record_success(manifest, "subway")
    monkeypatch.setenv("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID", "root")
    monkeypatch.setattr(f"{RETENTION_MOD}.build_drive_service", lambda **_: object())
    looked_up = []

    def find_folder(_service, root, relative):
        looked_up.append((root, relative))
        return "folder"

    monkeypatch.setattr(f"{RETENTION_MOD}.find_folder_path", find_folder)
    monkeypatch.setattr(
        f"{RETENTION_MOD}.list_folder_files",
        lambda *_: [
            {
                "name": verified.name,
                "size": str(verified.stat().st_size),
                "md5Checksum": drive_client.file_md5(verified),
            }
        ],
    )

    result = run_cleanup(
        [RetentionTarget("subway", tmp_path / "data/SUBWAY/raw/arrival")],
        retention_hours=48,
        yes=True,
        require_archive_success=True,
        manifest_path=manifest,
        ai_root=tmp_path,
        current_slot=("2026-09-13", "04"),
    )

    assert not verified.exists() and unverified.exists()
    assert result.skips[0].reason == "archive_file_missing"
    assert looked_up == [("root", "SUBWAY/raw/arrival/dt=2026-09-11/hh=03")]


def test_retention_skips_everything_when_drive_root_is_unset(tmp_path):
    path = old_subway_file(tmp_path)
    manifest = tmp_path / "archive.jsonl"
    record_success(manifest, "subway")
    verifier = DriveArchiveVerifier(tmp_path)
    verifier.service = object()

    verification = verifier("subway", "2026-09-11", "03", path)

    assert verification.reason == "archive_root_missing"


def test_retention_alert_sent_only_when_files_are_kept(tmp_path, sent):
    old_subway_file(tmp_path)
    args = ["--ai-root", str(tmp_path), "--require-archive-success", "--notify-discord"]

    assert retention_main(args) == 0

    detail, kwargs = sent[0]
    assert "archive_not_success subway dt=2026-09-11 hh=03 files=1" in detail
    assert "삭제하지 않았다" in detail
    assert "삭제 보류" in kwargs["title"]


def test_retention_is_silent_without_skips_or_flag(tmp_path, sent):
    retention_main(["--ai-root", str(tmp_path), "--require-archive-success", "--notify-discord"])
    old_subway_file(tmp_path)
    retention_main(["--ai-root", str(tmp_path), "--require-archive-success"])

    assert sent == []


def test_retention_dry_run_remains_the_default(tmp_path, capsys):
    path = old_subway_file(tmp_path)

    retention_main(["--ai-root", str(tmp_path)])

    assert "dry_run=true" in capsys.readouterr().out
    assert path.exists()


def test_skip_alert_groups_by_partition_and_truncates(tmp_path):
    base = tmp_path / "data/SUBWAY/raw/arrival"
    for hour in range(14):
        old = make_partition(base, "snapshot_s.parquet", dt="2026-09-11", hh=f"{hour:02d}")
        stamp = time.time() - 49 * 3600
        os.utime(old, (stamp, stamp))
    result = run_cleanup(
        [RetentionTarget("subway", base)],
        retention_hours=48,
        yes=False,
        require_archive_success=True,
        manifest_path=tmp_path / "none.jsonl",
        current_slot=("2026-09-13", "04"),
    )

    alert = build_skip_alert(result)

    assert "14개를" in alert
    assert "외 4개 파티션" in alert
    assert alert.count("archive_not_success") == 10


# ---- notify_failure ----


def test_notify_failure_without_webhook_warns_and_does_not_raise(capsys):
    result = notify_discord.notify_failure("detail")

    assert result.ok and result.status == "skipped"
    assert "DISCORD_WEBHOOK_URL is empty" in capsys.readouterr().err


def test_notify_failure_posts_title_server_and_detail(monkeypatch):
    posted = {}

    class Resp:
        status_code = 204
        text = ""

    def fake_post(url, json, timeout):
        posted.update(url=url, content=json["content"])
        return Resp()

    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/hook")
    monkeypatch.setenv("DATA_ENGINE_SERVER_NAME", "J15A104A")
    monkeypatch.setattr(notify_discord.requests, "post", fake_post)

    result = notify_discord.notify_failure("subway dt=x", title="[T] title")

    assert result.status == "sent"
    for text in ("[T] title", "server=J15A104A", "subway dt=x"):
        assert text in posted["content"]


def test_notify_failure_reports_send_error_on_stderr(monkeypatch, capsys):
    def fail(*_a, **_k):
        raise notify_discord.requests.ConnectionError("down")

    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/hook")
    monkeypatch.setattr(notify_discord.requests, "post", fail)

    result = notify_discord.notify_failure("x")

    assert not result.ok
    assert "discord notification failed" in capsys.readouterr().err


# ---- 설정 누락(인증·폴더 ID)도 알림 대상 ----


def test_missing_drive_credentials_are_alerted_and_raised(tmp_path, monkeypatch, sent):
    make_partition(tmp_path / "data/SUBWAY/raw/arrival")
    monkeypatch.setenv("DATA_ENGINE_DRIVE_AUTH_MODE", "oauth")
    monkeypatch.delenv("GOOGLE_OAUTH_TOKEN_FILE", raising=False)
    monkeypatch.setenv("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID", "root")

    with pytest.raises(RuntimeError, match="GOOGLE_OAUTH_TOKEN_FILE"):
        upload_main(upload_args(tmp_path, "subway", "--notify-discord"))

    assert "GOOGLE_OAUTH_TOKEN_FILE is empty" in sent[0][0]


def test_missing_drive_root_folder_is_alerted(tmp_path, monkeypatch, sent):
    make_partition(tmp_path / "data/SUBWAY/raw/arrival")
    monkeypatch.setenv("DATA_ENGINE_DRIVE_AUTH_MODE", "oauth")
    monkeypatch.setenv("GOOGLE_OAUTH_TOKEN_FILE", str(tmp_path / "token.json"))

    with pytest.raises(RuntimeError, match="ROOT_FOLDER_ID"):
        upload_main(upload_args(tmp_path, "subway", "--notify-discord"))

    assert "ROOT_FOLDER_ID is empty" in sent[0][0]


def test_config_error_without_flag_or_yes_does_not_notify(tmp_path, monkeypatch, sent):
    make_partition(tmp_path / "data/SUBWAY/raw/arrival")
    monkeypatch.setenv("DATA_ENGINE_DRIVE_AUTH_MODE", "oauth")
    monkeypatch.delenv("GOOGLE_OAUTH_TOKEN_FILE", raising=False)
    monkeypatch.setenv("GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID", "root")

    with pytest.raises(RuntimeError):
        upload_main(upload_args(tmp_path, "subway"))  # --notify-discord 없음
    dry_run = [a for a in upload_args(tmp_path, "subway", "--notify-discord") if a != "--yes"]
    assert upload_main(dry_run) == 0  # --yes 없으면 자격 증명을 검사하지 않는다

    assert sent == []


def test_retention_crash_is_alerted_only_when_deleting(tmp_path, sent):
    (tmp_path / "archive.jsonl").write_text("{broken json\n")
    base = [
        "--ai-root",
        str(tmp_path),
        "--manifest-path",
        str(tmp_path / "archive.jsonl"),
        "--require-archive-success",
        "--notify-discord",
    ]
    old_subway_file(tmp_path)

    with pytest.raises(ValueError):
        retention_main([*base, "--yes"])

    assert "retention 정리 중단" in sent[0][0]
