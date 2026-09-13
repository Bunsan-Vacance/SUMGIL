"""Create a Google Drive OAuth token file for unattended archive uploads."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from DATA_ENGINE.archive.storage.drive_client import DRIVE_SCOPE


def authorize_drive_oauth(client_secret_file: Path, token_file: Path) -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_file), scopes=[DRIVE_SCOPE])
    credentials = flow.run_local_server(port=0)

    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(credentials.to_json(), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Authorize Google Drive OAuth and write a token JSON file.",
    )
    parser.add_argument("--client-secret-file", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    authorize_drive_oauth(args.client_secret_file, args.token_file)
    print(f"Google Drive OAuth token saved: {args.token_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
