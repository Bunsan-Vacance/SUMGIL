"""Per-topic processing status written by the Kafka consumer.

The consumer process is the only writer. Monitors read the JSON file to show
when a topic was last received/saved without touching Kafka.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from DATA_ENGINE.collect.common import KST

AI_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATUS_PATH = AI_ROOT / "logs" / "kafka_consumer_status.json"
STATUS_PATH_ENV = "KAFKA_CONSUMER_STATUS_PATH"
MAX_RECENT_FAILURES = 20


def status_path_from_env() -> Path:
    return Path(os.environ.get(STATUS_PATH_ENV) or DEFAULT_STATUS_PATH)


def _now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


@dataclass
class TopicStatus:
    last_received_at: str | None = None
    last_saved_at: str | None = None
    committed_offsets: dict[str, int] = field(default_factory=dict)  # partition -> next offset
    saved_events: int = 0
    parse_failed: int = 0
    recent_parse_failures: list[dict[str, Any]] = field(default_factory=list)
    save_failed: int = 0
    last_error: str | None = None
    last_error_at: str | None = None
    retry_pending: bool = False


class ConsumerStatus:
    """Accumulates counters since consumer start and persists them atomically."""

    def __init__(self, group_id: str, path: Path | None = None) -> None:
        self.group_id = group_id
        self.path = path or status_path_from_env()
        self.started_at = _now()
        self.topics: dict[str, TopicStatus] = {}

    def _topic(self, topic: str) -> TopicStatus:
        return self.topics.setdefault(topic, TopicStatus())

    def record_received(self, messages: list[object]) -> None:
        now = _now()
        for topic in {getattr(msg, "topic", None) or "unknown" for msg in messages}:
            self._topic(topic).last_received_at = now

    def record_parse_failure(self, topic: str | None, partition: int | None, offset: int | None):
        status = self._topic(topic or "unknown")
        status.parse_failed += 1
        status.recent_parse_failures.append(
            {"partition": partition, "offset": offset, "at": _now()}
        )
        del status.recent_parse_failures[:-MAX_RECENT_FAILURES]

    def record_saved(self, saved_by_topic: dict[str, int], offsets: dict[tuple[str, int], int]):
        """Record a successful save + commit. ``offsets`` maps (topic, partition) -> next offset."""
        now = _now()
        for topic, count in saved_by_topic.items():
            status = self._topic(topic)
            status.saved_events += count
            status.last_saved_at = now
        for (topic, partition), offset in offsets.items():
            status = self._topic(topic)
            status.committed_offsets[str(partition)] = offset
            status.retry_pending = False

    def record_save_failure(self, topics: list[str], error: BaseException) -> None:
        now = _now()
        reason = f"{type(error).__name__}: {error}"[:300]
        for topic in topics:
            status = self._topic(topic)
            status.save_failed += 1
            status.last_error = reason
            status.last_error_at = now
            # 커밋하지 않았으므로 재기동 후 마지막 커밋 offset부터 다시 읽는다.
            status.retry_pending = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "started_at": self.started_at,
            "updated_at": _now(),
            "topics": {
                topic: {
                    "last_received_at": s.last_received_at,
                    "last_saved_at": s.last_saved_at,
                    "committed_offsets": s.committed_offsets,
                    "saved_events": s.saved_events,
                    "parse_failed": s.parse_failed,
                    "recent_parse_failures": s.recent_parse_failures,
                    "save_failed": s.save_failed,
                    "last_error": s.last_error,
                    "last_error_at": s.last_error_at,
                    "retry_pending": s.retry_pending,
                }
                for topic, s in sorted(self.topics.items())
            },
        }

    def write(self) -> None:
        """Best-effort atomic write; status must never take the consumer down."""
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), "utf-8")
            os.replace(tmp, self.path)
        except OSError:
            import logging

            logging.getLogger("kafka_consumer").warning(
                "consumer status write failed: %s", self.path, exc_info=True
            )
        finally:
            tmp.unlink(missing_ok=True)


def read_status(path: Path | None = None) -> dict[str, Any] | None:
    target = path or status_path_from_env()
    try:
        return json.loads(target.read_text("utf-8"))
    except (OSError, ValueError):
        return None
