"""Send DATA_ENGINE monitor alerts to Discord."""

from __future__ import annotations

import argparse
import os
import socket
import sys
from dataclasses import dataclass

import requests
from dotenv import load_dotenv

DISCORD_CONTENT_LIMIT = 2000
DEFAULT_TITLE = "[DATA_ENGINE] 수집 상태 이상 감지"


@dataclass(frozen=True)
class DiscordNotifyResult:
    ok: bool
    status: str
    message: str


def truncate_message(message: str, limit: int = DISCORD_CONTENT_LIMIT) -> str:
    if limit <= 0:
        raise ValueError("limit must be positive")
    if len(message) <= limit:
        return message
    suffix = "\n... (truncated)"
    if limit <= len(suffix):
        return message[:limit]
    return message[: limit - len(suffix)] + suffix


def build_discord_message(
    detail: str,
    *,
    server_name: str,
    title: str = DEFAULT_TITLE,
    status: str = "FAIL",
) -> str:
    content = f"{title}\nserver={server_name}\nstatus={status}\n\n{detail}".strip()
    return truncate_message(content)


def resolve_server_name(server_name: str | None = None) -> str:
    return server_name or os.environ.get("DATA_ENGINE_SERVER_NAME") or socket.gethostname()


def send_discord_notification(
    message: str,
    *,
    webhook_url: str | None = None,
    timeout_sec: float = 10.0,
    dry_run: bool = False,
) -> DiscordNotifyResult:
    webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL", "")
    content = truncate_message(message)

    if dry_run:
        return DiscordNotifyResult(
            ok=True,
            status="dry_run",
            message=f"DRY_RUN discord notification skipped: content={content}",
        )

    if not webhook_url:
        return DiscordNotifyResult(
            ok=True,
            status="skipped",
            message="WARN discord notification skipped: DISCORD_WEBHOOK_URL is empty",
        )

    try:
        response = requests.post(webhook_url, json={"content": content}, timeout=timeout_sec)
    except requests.RequestException as exc:
        return DiscordNotifyResult(
            ok=False,
            status="failed",
            message=f"FAIL discord notification failed: {exc}",
        )

    if 200 <= response.status_code < 300:
        return DiscordNotifyResult(
            ok=True,
            status="sent",
            message="OK discord notification sent",
        )

    return DiscordNotifyResult(
        ok=False,
        status="failed",
        message=(
            "FAIL discord notification failed: "
            f"status_code={response.status_code} body={response.text[:300]}"
        ),
    )


def notify_failure(detail: str, *, title: str = DEFAULT_TITLE) -> DiscordNotifyResult:
    """Send a failure alert; a failed send is reported on stderr and never raises."""
    content = build_discord_message(detail, server_name=resolve_server_name(), title=title)
    result = send_discord_notification(content)
    if result.status != "sent":
        print(result.message, file=sys.stderr)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send DATA_ENGINE monitor alert to Discord.")
    parser.add_argument("--message", required=True, help="Alert detail message.")
    parser.add_argument(
        "--webhook-url",
        default=None,
        help="Discord webhook URL. Defaults to DISCORD_WEBHOOK_URL.",
    )
    parser.add_argument(
        "--server-name",
        default=None,
        help="Server name for the alert. Defaults to DATA_ENGINE_SERVER_NAME or hostname.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print payload without sending.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    content = build_discord_message(
        args.message,
        server_name=resolve_server_name(args.server_name),
    )
    result = send_discord_notification(
        content,
        webhook_url=args.webhook_url,
        dry_run=args.dry_run,
    )
    print(result.message)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
