"""Google Drive client helpers for DATA_ENGINE archive uploads."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DRIVE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"


@dataclass(frozen=True)
class DriveUploadResult:
    file_id: str
    name: str
    uploaded: bool


def _escape_drive_query_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _media_file_upload(local_file: Path):
    from googleapiclient.http import MediaFileUpload

    return MediaFileUpload(str(local_file), resumable=True)


def build_drive_service(service_account_file: Path):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    credentials = service_account.Credentials.from_service_account_file(
        str(service_account_file),
        scopes=[DRIVE_SCOPE],
    )
    return build("drive", "v3", credentials=credentials)


def find_child(
    service,
    parent_folder_id: str,
    name: str,
    *,
    mime_type: str | None = None,
) -> dict[str, str] | None:
    escaped_parent = _escape_drive_query_value(parent_folder_id)
    escaped_name = _escape_drive_query_value(name)
    clauses = [
        f"'{escaped_parent}' in parents",
        f"name = '{escaped_name}'",
        "trashed = false",
    ]
    if mime_type is not None:
        escaped_mime = _escape_drive_query_value(mime_type)
        clauses.append(f"mimeType = '{escaped_mime}'")

    response = (
        service.files()
        .list(
            q=" and ".join(clauses),
            spaces="drive",
            fields="files(id,name,mimeType)",
            pageSize=1,
        )
        .execute()
    )
    files = response.get("files", [])
    return files[0] if files else None


def create_folder(service, parent_folder_id: str, name: str) -> str:
    response = (
        service.files()
        .create(
            body={
                "name": name,
                "mimeType": DRIVE_FOLDER_MIME_TYPE,
                "parents": [parent_folder_id],
            },
            fields="id",
        )
        .execute()
    )
    return str(response["id"])


def ensure_folder_path(service, root_folder_id: str, relative_path: str) -> str:
    parent_id = root_folder_id
    for part in [item for item in Path(relative_path).parts if item not in {"", "."}]:
        existing = find_child(service, parent_id, part, mime_type=DRIVE_FOLDER_MIME_TYPE)
        if existing is None:
            parent_id = create_folder(service, parent_id, part)
        else:
            parent_id = str(existing["id"])
    return parent_id


def upload_file(
    service,
    parent_folder_id: str,
    local_file: Path,
    *,
    skip_existing: bool = True,
) -> DriveUploadResult:
    if skip_existing:
        existing = find_child(service, parent_folder_id, local_file.name)
        if existing is not None:
            return DriveUploadResult(
                file_id=str(existing["id"]),
                name=str(existing.get("name", local_file.name)),
                uploaded=False,
            )

    response = (
        service.files()
        .create(
            body={"name": local_file.name, "parents": [parent_folder_id]},
            media_body=_media_file_upload(local_file),
            fields="id,name",
        )
        .execute()
    )
    return DriveUploadResult(
        file_id=str(response["id"]),
        name=str(response.get("name", local_file.name)),
        uploaded=True,
    )
