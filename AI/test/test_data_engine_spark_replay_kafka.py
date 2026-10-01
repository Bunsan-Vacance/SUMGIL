"""replay_kafka 잡 테스트 — kafka 라이브러리 없이 가짜 컨슈머로 돈다."""

from __future__ import annotations

import json
from collections import namedtuple
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from DATA_ENGINE.collect.common import KST
from DATA_ENGINE.spark.jobs import replay_kafka as rk

TP = namedtuple("TP", ["topic", "partition"])
OT = namedtuple("OT", ["offset", "timestamp"])
Msg = namedtuple("Msg", ["topic", "partition", "offset", "timestamp", "value"])

TOPIC = "bike.stock"
BASE_MS = int(datetime(2026, 9, 30, 9, 0, tzinfo=KST).timestamp() * 1000)
MINUTE = 60_000


def _value(i: int) -> bytes:
    return json.dumps(
        {
            "event_id": f"bike.stock+ST-{i}+h{i}",
            "source": TOPIC,
            "entity_id": f"ST-{i}",
            "source_generated_at": None,
            "ingested_at": "2026-09-30T09:00:03+09:00",
            "poll_run_at": "2026-09-30T09:00:00+09:00",
            "payload": {"stationId": f"ST-{i}", "parkingBikeTotCnt": "3"},
        }
    ).encode()


class FakeConsumer:
    """offset i 의 메시지 타임스탬프 = BASE_MS + i * 1분. 파티션 0 하나."""

    def __init__(self, n: int = 20, per_poll: int = 4) -> None:
        self.msgs = [Msg(TOPIC, 0, i, BASE_MS + i * MINUTE, _value(i)) for i in range(n)]
        self.per_poll = per_poll
        self.calls: list[str] = []
        self.pos: dict[TP, int] = {}
        self.assigned: list[TP] = []

    def partitions_for_topic(self, topic):
        return {0}

    def end_offsets(self, tps):
        return {tp: len(self.msgs) for tp in tps}

    def offsets_for_times(self, query):
        out = {}
        for tp, ts in query.items():
            hit = next((m for m in self.msgs if m.timestamp >= ts), None)
            out[tp] = OT(hit.offset, hit.timestamp) if hit else None
        return out

    def assign(self, tps):
        self.calls.append("assign")
        self.assigned = list(tps)

    def subscribe(self, *a, **k):
        self.calls.append("subscribe")

    def seek(self, tp, offset):
        self.calls.append("seek")
        self.pos[tp] = offset

    def poll(self, timeout_ms=0):
        out = {}
        for tp in self.assigned:
            start = self.pos[tp]
            chunk = [m for m in self.msgs if m.offset >= start][: self.per_poll]
            if chunk:
                out[tp] = chunk
                self.pos[tp] = chunk[-1].offset + 1
        return out

    def position(self, tp):
        return self.pos[tp]

    def commit(self, *a, **k):
        self.calls.append("commit")

    def close(self, autocommit=True):
        self.calls.append(f"close(autocommit={autocommit})")


def _ts(minute: int) -> datetime:
    return datetime.fromtimestamp((BASE_MS + minute * MINUTE) / 1000, tz=KST)


@pytest.fixture
def ai_root(tmp_path, monkeypatch):
    root = tmp_path / "AI"
    root.mkdir()
    monkeypatch.setattr(rk, "AI_ROOT", root)
    return root


def _out(root: Path) -> Path:
    return root / "data" / "BIKE" / "interim" / "spark_exp" / "replay_t"


def _run(root: Path, consumer: FakeConsumer, **kw) -> dict:
    return rk.replay(
        topic=TOPIC,
        from_ts=kw.pop("from_ts", _ts(5)),
        to_ts=kw.pop("to_ts", _ts(12)),
        out_root=kw.pop("out_root", _out(root)),
        consumer=consumer,
        make_tp=TP,
        ai_root=root,
        **kw,
    )


def test_offset_bounds_and_stop_at_end(ai_root):
    consumer = FakeConsumer()
    meta = _run(ai_root, consumer)
    part = meta["partitions"]["0"]
    # from 5분 -> offset 5, to 12분 -> offset 12(미포함)
    assert (part["start_offset"], part["end_offset"], part["read"]) == (5, 12, 7)
    assert meta["stop_reason"] == "end_offsets_reached"
    assert meta["events_written"] == 7
    assert "subscribe" not in consumer.calls
    assert consumer.calls[:2] == ["assign", "seek"]


def test_end_offsets_used_when_to_ts_past_log(ai_root):
    meta = _run(ai_root, FakeConsumer(), to_ts=_ts(999))
    assert meta["partitions"]["0"]["end_offset"] == 20
    assert meta["partitions"]["0"]["read"] == 15


def test_no_commit_called(ai_root):
    consumer = FakeConsumer()
    _run(ai_root, consumer)
    assert "commit" not in consumer.calls
    assert "close(autocommit=False)" in consumer.calls


def test_prod_group_rejected(ai_root):
    with pytest.raises(SystemExit):
        _run(ai_root, FakeConsumer(), group="ai-spark")
    assert not (ai_root / "data").exists()


@pytest.mark.parametrize(
    "bad",
    [
        lambda r: r / "data" / "BIKE" / "raw" / "realtime" / "x",
        lambda r: r / "data" / "BIKE" / "interim" / "other",
        lambda r: r / "data" / "BIKE" / "interim" / "spark_exp",
        lambda r: r / "elsewhere",
    ],
)
def test_out_root_outside_isolation_exits_2(ai_root, bad):
    with pytest.raises(SystemExit) as exc:
        _run(ai_root, FakeConsumer(), out_root=bad(ai_root))
    assert exc.value.code == 2
    assert not (ai_root / "data" / "BIKE" / "raw").exists()


def test_main_returns_2_on_isolation_violation(ai_root, tmp_path):
    code = rk.main(
        [
            "--topic",
            TOPIC,
            "--from-ts",
            "2026-09-30T09:00",
            "--to-ts",
            "2026-09-30T10:00",
            "--out-root",
            str(tmp_path / "outside"),
            "--no-compare",
        ]
    )
    assert code == 2


def test_writes_only_under_out_root(ai_root):
    out = _out(ai_root)
    meta = _run(ai_root, FakeConsumer())
    assert list(out.glob("data/BIKE/raw/realtime/dt=*/hh=*/snapshot_*.parquet"))
    # 운영 raw·latest_stock은 생기지 않는다.
    assert not (ai_root / "data" / "BIKE" / "raw").exists()
    assert meta["prod_latest_stock"]["unchanged"] is True
    outside = [p for p in (ai_root / "data").rglob("*") if p.is_file() and out not in p.parents]
    assert outside == []


def test_spark_compare_both_and_only_in_prod(tmp_path):
    pytest.importorskip("pyspark")
    from DATA_ENGINE.spark.session import build_spark_session

    spark = build_spark_session("test-replay-compare", cores="1", driver_memory="1g")
    try:
        rel = Path("BIKE/raw/realtime/dt=2026-09-30/hh=09")
        replay_root = tmp_path / "replay"
        prod_root = tmp_path / "prod"

        def frame(offsets):
            return pd.DataFrame(
                {
                    "event_id": [f"e{o}" for o in offsets],
                    "payload_json": ["{}"] * len(offsets),
                    "kafka_topic": [TOPIC] * len(offsets),
                    "kafka_partition": [0] * len(offsets),
                    "kafka_offset": offsets,
                }
            )

        for root, offsets in ((replay_root / "data", [0, 1, 2]), (prod_root, [0, 1, 2, 3])):
            d = root / rel
            d.mkdir(parents=True)
            frame(offsets).to_parquet(d / "snapshot_a.parquet", index=False)

        full = rk.compare_with_prod(
            spark, topic=TOPIC, replay_root=replay_root, compare_root=prod_root
        )
        assert (full["both"], full["only_in_replay"], full["only_in_prod"]) == (3, 0, 1)
        assert full["match"] is False
        assert full["sample_only_in_prod"][0]["kafka_offset"] == 3

        # 오프셋 구간 [0, 3)로 제한하면 일치한다.
        ranged = rk.compare_with_prod(
            spark,
            topic=TOPIC,
            replay_root=replay_root,
            compare_root=prod_root,
            ranges={0: (0, 3)},
        )
        assert (ranged["both"], ranged["only_in_prod"], ranged["match"]) == (3, 0, True)

        # 운영에서 한 행이 빠지면 only_in_replay로 드러난다.
        frame([0, 1]).to_parquet(prod_root / rel / "snapshot_a.parquet", index=False)
        missing = rk.compare_with_prod(
            spark, topic=TOPIC, replay_root=replay_root, compare_root=prod_root
        )
        assert (missing["both"], missing["only_in_replay"]) == (2, 1)
    finally:
        spark.stop()
