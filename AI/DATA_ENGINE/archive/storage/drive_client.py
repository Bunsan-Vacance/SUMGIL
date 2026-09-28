"""Google Drive client helpers for DATA_ENGINE archive uploads."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

DRIVE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
DRIVE_AUTH_MODE_SERVICE_ACCOUNT = "service_account"
DRIVE_AUTH_MODE_OAUTH = "oauth"


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


def build_service_account_drive_service(service_account_file: Path):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    credentials = service_account.Credentials.from_service_account_file(
        str(service_account_file),
        scopes=[DRIVE_SCOPE],
    )
    return build("drive", "v3", credentials=credentials)


def build_oauth_drive_service(token_file: Path):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials.from_authorized_user_file(str(token_file), scopes=[DRIVE_SCOPE])
    return build("drive", "v3", credentials=credentials)


def build_drive_service(
    service_account_file: Path | None = None,
    *,
    auth_mode: str = DRIVE_AUTH_MODE_SERVICE_ACCOUNT,
    oauth_token_file: Path | None = None,
):
    if auth_mode == DRIVE_AUTH_MODE_SERVICE_ACCOUNT:
        if service_account_file is None:
            raise RuntimeError("service_account_file is required")
        return build_service_account_drive_service(service_account_file)
    if auth_mode == DRIVE_AUTH_MODE_OAUTH:
        if oauth_token_file is None:
            raise RuntimeError("oauth_token_file is required")
        return build_oauth_drive_service(oauth_token_file)
    raise ValueError("auth_mode must be one of: service_account, oauth")


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
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
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
            supportsAllDrives=True,
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


def find_folder_path(service, root_folder_id: str, relative_path: str) -> str | None:
    parent_id = root_folder_id
    for part in [item for item in Path(relative_path).parts if item not in {"", "."}]:
        child = find_child(service, parent_id, part, mime_type=DRIVE_FOLDER_MIME_TYPE)
        if child is None:
            return None
        parent_id = str(child["id"])
    return parent_id


def list_folder_files(service, folder_id: str) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    page_token = None
    while True:
        request = service.files().list(
            q=f"'{_escape_drive_query_value(folder_id)}' in parents and trashed = false",
            spaces="drive",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            fields="nextPageToken,files(id,name,mimeType,size,md5Checksum)",
            pageSize=1000,
            **({"pageToken": page_token} if page_token else {}),
        )
        response = request.execute()
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            return files


def file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def match_local_file(local_file: Path, remote_files: Iterable[dict[str, str]]) -> str:
    """Compare a local file against a folder's remote listing by name, size, and md5.

    Returns one of: "missing", "verified", "ambiguous", "size_mismatch",
    "checksum_missing", "checksum_mismatch".
    """
    matches = [
        item
        for item in remote_files
        if item.get("name") == local_file.name and item.get("mimeType") != DRIVE_FOLDER_MIME_TYPE
    ]
    if not matches:
        return "missing"
    if len(matches) != 1:
        return "ambiguous"
    remote = matches[0]
    if "size" not in remote or int(remote["size"]) != local_file.stat().st_size:
        return "size_mismatch"
    remote_md5 = remote.get("md5Checksum")
    if not remote_md5:
        return "checksum_missing"
    if file_md5(local_file) != remote_md5:
        return "checksum_mismatch"
    return "verified"


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
            supportsAllDrives=True,
            fields="id,name",
        )
        .execute()
    )
    return DriveUploadResult(
        file_id=str(response["id"]),
        name=str(response.get("name", local_file.name)),
        uploaded=True,
    )
