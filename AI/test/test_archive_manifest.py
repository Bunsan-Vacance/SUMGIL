import json

import pytest

from DATA_ENGINE.archive.manifest import (
    ArchiveManifestRecord,
    append_manifest_record,
    has_successful_archive,
    latest_partition_status,
    load_manifest_records,
    record_from_dict,
)


def make_record(
    *,
    dataset: str = "bike",
    status: str = "success",
    uploaded_at: str = "2026-09-13T04:05:00+09:00",
    backend: str = "drive",
    error: str | None = None,
) -> ArchiveManifestRecord:
    return ArchiveManifestRecord(
        dataset=dataset,
        dt="2026-09-13",
        hh="03",
        local_path=f"data/{dataset}/raw/realtime/dt=2026-09-13/hh=03",
        archive_backend=backend,
        archive_path=f"{dataset}/raw/realtime/dt=2026-09-13/hh=03",
        file_count=12,
        total_bytes=1234,
        status=status,
        uploaded_at=uploaded_at,
        error=error,
    )


def test_append_manifest_record_creates_parent_and_loads_roundtrip(tmp_path):
    manifest_path = tmp_path / "data/manifest/archive_uploads.jsonl"
    record = make_record()

    append_manifest_record(manifest_path, record)

    assert load_manifest_records(manifest_path) == [record]


def test_append_manifest_record_writes_jsonl(tmp_path):
    manifest_path = tmp_path / "archive_uploads.jsonl"

    append_manifest_record(manifest_path, make_record())

    lines = manifest_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["dataset"] == "bike"
    assert payload["status"] == "success"


def test_load_manifest_records_returns_empty_when_missing(tmp_path):
    assert load_manifest_records(tmp_path / "missing.jsonl") == []


def test_failed_record_roundtrips_with_error(tmp_path):
    manifest_path = tmp_path / "archive_uploads.jsonl"
    record = make_record(status="failed", error="upload timeout")

    append_manifest_record(manifest_path, record)

    loaded = load_manifest_records(manifest_path)
    assert loaded == [record]
    assert loaded[0].error == "upload timeout"


def test_has_successful_archive_returns_true_for_latest_success(tmp_path):
    manifest_path = tmp_path / "archive_uploads.jsonl"
    append_manifest_record(manifest_path, make_record(status="failed"))
    append_manifest_record(
        manifest_path,
        make_record(status="success", uploaded_at="2026-09-13T04:10:00+09:00"),
    )

    assert has_successful_archive(manifest_path, "bike", "2026-09-13", "03") is True


def test_has_successful_archive_returns_false_when_latest_is_failed(tmp_path):
    manifest_path = tmp_path / "archive_uploads.jsonl"
    append_manifest_record(manifest_path, make_record(status="success"))
    append_manifest_record(
        manifest_path,
        make_record(
            status="failed",
            uploaded_at="2026-09-13T04:10:00+09:00",
            error="retry failed",
        ),
    )

    assert has_successful_archive(manifest_path, "bike", "2026-09-13", "03") is False


def test_has_successful_archive_returns_false_for_different_backend(tmp_path):
    manifest_path = tmp_path / "archive_uploads.jsonl"
    append_manifest_record(manifest_path, make_record(status="success", backend="drive"))

    assert (
        has_successful_archive(
            manifest_path,
            "bike",
            "2026-09-13",
            "03",
            backend="s3",
        )
        is False
    )


def test_latest_partition_status_ignores_other_partitions(tmp_path):
    manifest_path = tmp_path / "archive_uploads.jsonl"
    append_manifest_record(manifest_path, make_record(dataset="weather", status="success"))
    append_manifest_record(manifest_path, make_record(dataset="bike", status="failed"))

    latest = latest_partition_status(manifest_path, "bike", "2026-09-13", "03")

    assert latest is not None
    assert latest.dataset == "bike"
    assert latest.status == "failed"


def test_record_from_dict_rejects_invalid_status():
    payload = make_record().__dict__ | {"status": "pending"}

    with pytest.raises(ValueError, match="status must be one of"):
        record_from_dict(payload)


def test_record_from_dict_rejects_negative_file_count():
    payload = make_record().__dict__ | {"file_count": -1}

    with pytest.raises(ValueError, match="file_count must be non-negative"):
        record_from_dict(payload)


def test_record_from_dict_rejects_negative_total_bytes():
    payload = make_record().__dict__ | {"total_bytes": -1}

    with pytest.raises(ValueError, match="total_bytes must be non-negative"):
        record_from_dict(payload)


def test_record_from_dict_rejects_missing_required_field():
    payload = make_record().__dict__.copy()
    del payload["archive_path"]

    with pytest.raises(ValueError, match="manifest record missing fields"):
        record_from_dict(payload)


def test_load_manifest_records_rejects_broken_json_line(tmp_path):
    manifest_path = tmp_path / "archive_uploads.jsonl"
    manifest_path.write_text("{not json}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid manifest JSON"):
        load_manifest_records(manifest_path)


def test_load_manifest_records_rejects_non_object_line(tmp_path):
    manifest_path = tmp_path / "archive_uploads.jsonl"
    manifest_path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(TypeError, match="manifest line must be an object"):
        load_manifest_records(manifest_path)
