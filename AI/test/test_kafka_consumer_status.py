from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from DATA_ENGINE.stream.consumer_status import ConsumerStatus, read_status
from DATA_ENGINE.stream.kafka_consumer import next_offsets, process_batch


@dataclass(frozen=True)
class Msg:
    value: dict
    topic: str = "bike.stock"
    partition: int = 0
    offset: int = 0


def good(event_id: str = "e1") -> dict:
    return {
        "event_id": event_id,
        "source": "bike.stock",
        "entity_id": "ST-1",
        "source_generated_at": None,
        "ingested_at": "2026-09-21T10:00:03+09:00",
        "poll_run_at": "2026-09-21T10:00:00+09:00",
        "payload": {},
    }


def make_status(tmp_path) -> ConsumerStatus:
    return ConsumerStatus("ai-spark", tmp_path / "status.json")


def test_process_batch_saves_commits_and_records_status(tmp_path):
    status, commits = make_status(tmp_path), []
    messages = [Msg(good("a"), offset=4), Msg(good("b"), offset=5)]

    process_batch(
        messages, commit=lambda: commits.append(1), status=status, write=lambda events: []
    )

    data = read_status(tmp_path / "status.json")
    topic = data["topics"]["bike.stock"]
    assert commits == [1]
    assert topic["saved_events"] == 2
    assert topic["committed_offsets"] == {"0": 6}
    assert topic["last_saved_at"] and topic["parse_failed"] == 0


def test_parse_failure_is_recorded_and_rest_of_batch_still_saved(tmp_path, caplog):
    status, saved = make_status(tmp_path), []
    messages = [Msg(good("a"), offset=1), Msg({"broken": True}, partition=2, offset=9)]

    process_batch(
        messages, commit=lambda: None, status=status, write=lambda events: saved.extend(events)
    )

    topic = read_status(tmp_path / "status.json")["topics"]["bike.stock"]
    assert len(saved) == 1
    assert topic["parse_failed"] == 1
    assert topic["recent_parse_failures"][0]["partition"] == 2
    assert topic["recent_parse_failures"][0]["offset"] == 9
    assert "partition=2 offset=9" in caplog.text


def test_all_messages_unparseable_still_commits_past_poison(tmp_path):
    status, commits = make_status(tmp_path), []

    process_batch(
        [Msg({"broken": True}, offset=3)],
        commit=lambda: commits.append(1),
        status=status,
        write=lambda events: pytest.fail("nothing to write"),
    )

    assert commits == [1]
    assert status.topics["bike.stock"].committed_offsets == {"0": 4}


def test_save_failure_does_not_commit_and_records_retry(tmp_path):
    status, commits = make_status(tmp_path), []

    def boom(events):
        raise OSError("disk full")

    with pytest.raises(OSError):
        process_batch([Msg(good())], commit=lambda: commits.append(1), status=status, write=boom)

    topic = read_status(tmp_path / "status.json")["topics"]["bike.stock"]
    assert commits == []
    assert topic["save_failed"] == 1
    assert topic["retry_pending"] is True
    assert "disk full" in topic["last_error"]


def test_record_received_sets_last_received_per_topic(tmp_path):
    status = make_status(tmp_path)
    status.record_received([Msg(good(), topic="subway.arrival")])
    assert status.topics["subway.arrival"].last_received_at
    assert "bike.stock" not in status.topics


def test_next_offsets_takes_max_per_partition():
    messages = [Msg({}, offset=1), Msg({}, offset=7), Msg({}, partition=1, offset=2)]
    assert next_offsets(messages) == {("bike.stock", 0): 8, ("bike.stock", 1): 3}


def test_status_write_failure_never_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    status = ConsumerStatus("ai-spark", blocker / "status.json")
    status.write()  # 부모가 파일이라 mkdir 실패 — 예외 없이 넘어가야 한다


def test_read_status_missing_or_corrupt_returns_none(tmp_path):
    assert read_status(tmp_path / "none.json") is None
    (tmp_path / "bad.json").write_text("{")
    assert read_status(tmp_path / "bad.json") is None
    (tmp_path / "ok.json").write_text(json.dumps({"topics": {}}))
    assert read_status(tmp_path / "ok.json") == {"topics": {}}
