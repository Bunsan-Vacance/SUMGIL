from pathlib import Path

from DATA_ENGINE.archive.storage import drive_client


class FakeRequest:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class FakeFilesResource:
    def __init__(self):
        self.children = {}
        self.created = []
        self.uploads = []
        self.next_id = 1

    def list(self, *, q, spaces, fields, pageSize):
        self.last_list = {
            "q": q,
            "spaces": spaces,
            "fields": fields,
            "pageSize": pageSize,
        }
        for (parent, name, mime_type), file_id in self.children.items():
            if (
                f"'{parent}' in parents" in q
                and f"name = '{name}'" in q
                and (mime_type is None or f"mimeType = '{mime_type}'" in q)
            ):
                return FakeRequest(
                    {"files": [{"id": file_id, "name": name, "mimeType": mime_type}]}
                )
        return FakeRequest({"files": []})

    def create(self, *, body, fields, media_body=None):
        file_id = f"id-{self.next_id}"
        self.next_id += 1
        name = body["name"]
        mime_type = body.get("mimeType")
        parent = body["parents"][0]
        self.children[(parent, name, mime_type)] = file_id
        self.created.append({"body": body, "fields": fields, "media_body": media_body})
        if media_body is not None:
            self.uploads.append({"body": body, "media_body": media_body})
        return FakeRequest({"id": file_id, "name": name})


class FakeDriveService:
    def __init__(self):
        self.files_resource = FakeFilesResource()

    def files(self):
        return self.files_resource


def test_find_child_returns_existing_item():
    service = FakeDriveService()
    service.files_resource.children[("root", "BIKE", drive_client.DRIVE_FOLDER_MIME_TYPE)] = (
        "folder-1"
    )

    result = drive_client.find_child(
        service,
        "root",
        "BIKE",
        mime_type=drive_client.DRIVE_FOLDER_MIME_TYPE,
    )

    assert result == {
        "id": "folder-1",
        "name": "BIKE",
        "mimeType": drive_client.DRIVE_FOLDER_MIME_TYPE,
    }


def test_ensure_folder_path_reuses_existing_and_creates_missing_folders():
    service = FakeDriveService()
    service.files_resource.children[("root", "BIKE", drive_client.DRIVE_FOLDER_MIME_TYPE)] = (
        "bike-id"
    )

    folder_id = drive_client.ensure_folder_path(service, "root", "BIKE/raw/realtime")

    assert folder_id == "id-2"
    created_names = [item["body"]["name"] for item in service.files_resource.created]
    assert created_names == ["raw", "realtime"]


def test_upload_file_skips_existing_by_default(tmp_path):
    service = FakeDriveService()
    service.files_resource.children[("parent", "snapshot.parquet", None)] = "existing-id"
    local_file = tmp_path / "snapshot.parquet"
    local_file.write_text("data", encoding="utf-8")

    result = drive_client.upload_file(service, "parent", local_file)

    assert result.file_id == "existing-id"
    assert result.uploaded is False
    assert service.files_resource.uploads == []


def test_upload_file_creates_file_when_missing(tmp_path, monkeypatch):
    service = FakeDriveService()
    local_file = tmp_path / "snapshot.parquet"
    local_file.write_text("data", encoding="utf-8")
    monkeypatch.setattr(drive_client, "_media_file_upload", lambda path: f"media:{Path(path).name}")

    result = drive_client.upload_file(service, "parent", local_file)

    assert result.name == "snapshot.parquet"
    assert result.uploaded is True
    assert service.files_resource.uploads[0]["media_body"] == "media:snapshot.parquet"
