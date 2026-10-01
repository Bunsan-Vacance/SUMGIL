"""Kafka 오프셋 되감기 격리 재적재 + Spark 재집계 대조 (Jira S15P21A104-340, P5).

특정 시간 구간의 Kafka 메시지를 다시 읽어 **격리 경로**에만 적재한 뒤, Spark로 운영 raw와
`(kafka_topic, kafka_partition, kafka_offset)` 키 기준으로 행 단위 대조한다.

운영 컨슈머(`DATA_ENGINE/stream/kafka_consumer.py`)를 재사용할 수 없는 이유:
  - `from-ts`가 없다. `subscribe` + 그룹 커밋 오프셋 이어읽기라 임의 시각으로 되감을 수 없다.
  - 출력 경로가 `AI_ROOT/data/.../raw/` 고정이다. 격리 경로로 돌릴 수단이 없다.
  - 종료 조건이 없다(`while True`). 구간 끝에서 멈추지 않는다.
  - 운영 그룹(`ai-spark`)을 공유하면 운영 raw에 중복 행이 쌓이고, `latest_stock`을 과거 값으로
    덮어쓰며, 그룹 커밋 오프셋까지 움직여 운영 컨슈머가 건너뛰거나 재처리한다.

그래서 이 잡은 별도 그룹(`ai-spark-exp`)으로 `assign`+`seek`만 쓰고(`subscribe` 금지),
`enable_auto_commit=False`에 커밋 호출이 아예 없다. 적재는 `write_events(events, ai_root=out_root)`
를 쓴다 — `write_events`가 쓰는 raw 파티션·`latest_stock`·`latest_by_grid`·bike weather가
모두 `ai_root` 인자 아래로만 가는 것을 코드로 확인했다(kafka_sink.py `base_dir_for_topic`·
`latest_stock_path`, weather_latest.py `latest_weather_path`, weather_bike_adapter.py
`bike_weather_path`). 따라서 격리 루트 안에는 `data/<도메인>/raw/...` 구조가 그대로 재현된다.

되감기 종료 조건: ① 각 파티션이 종료 오프셋(`to_ts` 이후 첫 오프셋, 없으면 end_offsets)에
도달하면 그 파티션 종료 ② 모든 파티션이 끝나면 종료 ③ 빈 `poll`이 연속 N회면 종료
(삭제·압축으로 종료 오프셋이 영영 안 채워지는 경우의 탈출구) ④ `--max-messages` 안전 상한.

실행:
    cd AI
    python -m DATA_ENGINE.spark.jobs.replay_kafka --topic bike.stock \
        --from-ts 2026-09-30T09:00 --to-ts 2026-09-30T10:00

종료 코드: 0 일치, 1 불일치, 2 격리 위반·입력 오류.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

AI_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(AI_ROOT))

from DATA_ENGINE.collect.common import KST  # noqa: E402
from DATA_ENGINE.stream.kafka_consumer import parse_messages_with_failures  # noqa: E402
from DATA_ENGINE.stream.kafka_sink import (  # noqa: E402
    base_dir_for_topic,
    latest_stock_path,
    write_events,
)

PROD_GROUP = "ai-spark"
DEFAULT_GROUP = "ai-spark-exp"
BATCH_SIZE = 5_000
DEFAULT_MAX_MESSAGES = 2_000_000
EMPTY_POLLS_TO_STOP = 5
POLL_TIMEOUT_MS = 1000
SAMPLE_SIZE = 10
KEY_COLS = ["kafka_topic", "kafka_partition", "kafka_offset"]


class IsolationError(SystemExit):
    """격리 검사 실패 — 종료 코드 2."""

    def __init__(self, message: str) -> None:
        super().__init__(2)
        self.message = message


def domain_for_topic(topic: str) -> str:
    """토픽 -> 도메인(`data/<도메인>/...`의 첫 폴더). 컨슈머 sink의 기존 매핑을 따른다."""
    try:
        rel = base_dir_for_topic(topic, Path(""))
    except ValueError:
        raise SystemExit(2) from None
    return rel.parts[1]


def default_out_root(topic: str, run: str, ai_root: Path) -> Path:
    return ai_root / "data" / domain_for_topic(topic) / "interim" / "spark_exp" / f"replay_{run}"


def check_isolation(out_root: Path, topic: str, *, ai_root: Path) -> dict:
    """쓰기 전 격리 검사. 위반이면 `IsolationError`(exit 2). 통과 시 검사 내역을 반환한다."""
    domain = domain_for_topic(topic)
    allowed = (ai_root / "data" / domain / "interim" / "spark_exp").resolve()
    out = Path(out_root).resolve()
    if out == allowed or allowed not in out.parents:
        raise IsolationError(f"out_root가 {allowed} 아래가 아님: {out}")
    protected = [
        (ai_root / "data" / domain / "raw").resolve(),
        (ai_root / "data" / domain / "processed").resolve(),
        base_dir_for_topic(topic, ai_root).resolve(),
        latest_stock_path(ai_root=ai_root).resolve(),
    ]
    for prot in protected:
        if out == prot or prot in out.parents or out in prot.parents:
            raise IsolationError(f"out_root가 운영 경로와 겹침: {out} vs {prot}")
    return {"ok": True, "allowed_root": str(allowed), "out_root": str(out)}


def parse_kst(text: str) -> datetime:
    dt = datetime.fromisoformat(text)
    return dt.replace(tzinfo=KST) if dt.tzinfo is None else dt.astimezone(KST)


def _stat_mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return None


def resolve_offsets(consumer, tps: list, from_ms: int, to_ms: int) -> dict:
    """파티션별 (시작, 종료) 오프셋. 시작은 from_ts 이후 첫 오프셋, 종료는 to_ts 이후 첫
    오프셋(exclusive)이며 없으면 end_offsets. from_ts 이후 메시지가 없으면 시작=종료(빈 구간)."""
    ends_all = consumer.end_offsets(tps)
    starts_raw = consumer.offsets_for_times({tp: from_ms for tp in tps})
    ends_raw = consumer.offsets_for_times({tp: to_ms for tp in tps})
    result = {}
    for tp in tps:
        end_of_log = ends_all[tp]
        start = starts_raw.get(tp)
        start = start.offset if start is not None else end_of_log
        end = ends_raw.get(tp)
        end = end.offset if end is not None else end_of_log
        result[tp] = (start, max(start, end))
    return result


def rewind_read(
    consumer,
    tps: list,
    offsets: dict,
    *,
    max_messages: int,
    empty_polls_to_stop: int = EMPTY_POLLS_TO_STOP,
    on_batch=None,
) -> dict:
    """`assign`+`seek`으로 되감아 [시작, 종료) 구간만 읽는다. 커밋은 호출하지 않는다.

    `on_batch(messages)`는 BATCH_SIZE개마다(마지막 잔여 포함) 호출된다.
    반환: {"read": {tp: 건수}, "stop_reason": str}.
    """
    consumer.assign(tps)
    for tp in tps:
        consumer.seek(tp, offsets[tp][0])
    pending = {tp for tp in tps if offsets[tp][0] < offsets[tp][1]}
    read = {tp: 0 for tp in tps}
    buffer: list = []
    total = 0
    empty = 0
    stop_reason = "end_offsets_reached"

    while pending:
        polled = consumer.poll(timeout_ms=POLL_TIMEOUT_MS)
        got = 0
        for tp, messages in polled.items():
            if tp not in offsets:
                continue
            end = offsets[tp][1]
            for msg in messages:
                if msg.offset >= end:
                    continue
                buffer.append(msg)
                read[tp] += 1
                got += 1
                total += 1
        for tp in list(pending):
            if consumer.position(tp) >= offsets[tp][1]:
                pending.discard(tp)
        while len(buffer) >= BATCH_SIZE:
            batch = buffer[:BATCH_SIZE]
            del buffer[:BATCH_SIZE]
            if on_batch is not None:
                on_batch(batch)
        if total >= max_messages:
            stop_reason = "max_messages"
            break
        empty = 0 if got else empty + 1
        if pending and empty >= empty_polls_to_stop:
            stop_reason = "empty_polls"
            break
    if buffer and on_batch is not None:
        on_batch(list(buffer))
    return {"read": read, "stop_reason": stop_reason}


def _make_consumer(group: str):  # pragma: no cover - 실제 브로커 필요
    from kafka import KafkaConsumer

    from DATA_ENGINE.stream.kafka_consumer import config_from_env

    config = config_from_env()
    return KafkaConsumer(
        bootstrap_servers=config.bootstrap_servers,
        group_id=group,
        enable_auto_commit=False,
        value_deserializer=lambda value: value,
    )


def _make_tp(topic: str, partition: int):  # pragma: no cover - 실제 브로커 필요
    from kafka import TopicPartition

    return TopicPartition(topic, partition)


def replay(
    *,
    topic: str,
    from_ts: datetime,
    to_ts: datetime,
    out_root: Path,
    group: str = DEFAULT_GROUP,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    consumer=None,
    make_tp=None,
    ai_root: Path | None = None,
    empty_polls_to_stop: int = EMPTY_POLLS_TO_STOP,
) -> dict:
    """격리 검사 -> 되감기 읽기 -> 격리 적재. meta용 dict를 반환한다."""
    ai_root = Path(ai_root) if ai_root is not None else AI_ROOT
    if group == PROD_GROUP:
        raise SystemExit(f"운영 그룹({PROD_GROUP})은 사용할 수 없다 — 커밋 오프셋을 건드린다")
    if not from_ts < to_ts:
        raise SystemExit("--from-ts는 --to-ts보다 앞서야 한다")
    isolation = check_isolation(out_root, topic, ai_root=ai_root)

    latest = latest_stock_path(ai_root=ai_root)
    mtime_before = _stat_mtime(latest)
    started = time.monotonic()

    if consumer is None:
        consumer = _make_consumer(group)
    make_tp = make_tp or _make_tp
    parts = consumer.partitions_for_topic(topic)
    if not parts:
        raise SystemExit(f"토픽 {topic}의 파티션을 찾을 수 없다")
    tps = [make_tp(topic, p) for p in sorted(parts)]
    offsets = resolve_offsets(
        consumer, tps, int(from_ts.timestamp() * 1000), int(to_ts.timestamp() * 1000)
    )

    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    stats = {"events": 0, "parse_failed": 0, "files": 0}

    def on_batch(messages: list) -> None:
        events, failed = parse_messages_with_failures(messages)
        stats["parse_failed"] += len(failed)
        if events:
            stats["events"] += len(events)
            stats["files"] += len(write_events(events, ai_root=out_root))

    try:
        result = rewind_read(
            consumer,
            tps,
            offsets,
            max_messages=max_messages,
            empty_polls_to_stop=empty_polls_to_stop,
            on_batch=on_batch,
        )
    finally:
        consumer.close(autocommit=False)

    mtime_after = _stat_mtime(latest)
    return {
        "topic": topic,
        "group": group,
        "from_ts": from_ts.isoformat(),
        "to_ts": to_ts.isoformat(),
        "partitions": {
            str(tp.partition): {
                "start_offset": offsets[tp][0],
                "end_offset": offsets[tp][1],
                "read": result["read"][tp],
            }
            for tp in tps
        },
        "stop_reason": result["stop_reason"],
        "events_written": stats["events"],
        "parse_failed": stats["parse_failed"],
        "files_written": stats["files"],
        "elapsed_sec": round(time.monotonic() - started, 2),
        "isolation": isolation,
        "prod_latest_stock": {
            "path": str(latest),
            "mtime_before": mtime_before,
            "mtime_after": mtime_after,
            "unchanged": mtime_before == mtime_after,
        },
    }


def _offset_ranges(meta: dict) -> dict[int, tuple[int, int]]:
    return {int(p): (v["start_offset"], v["end_offset"]) for p, v in meta["partitions"].items()}


def compare_with_prod(
    spark,
    *,
    topic: str,
    replay_root: Path,
    compare_root: Path,
    ranges: dict[int, tuple[int, int]] | None = None,
) -> dict:
    """격리 루트와 운영 raw를 같은 `dt=/hh=` 범위에서 Kafka 키로 대조한다.

    envelope 스키마 파일만 `(topic, partition, offset)`을 갖는다. 운영 쪽 폴러 flat 파일 행은
    Kafka 키가 없어 `prod_rows_without_kafka_key`로 따로 센다. `ranges`(파티션 -> [시작, 종료))를
    주면 양쪽 모두 그 오프셋 구간 안의 행만 비교한다(구간 밖 행이 `only_in_prod`로 오탐되지 않게).
    """
    from pyspark.sql import functions as F

    from DATA_ENGINE.spark.schema_reader import split_by_schema

    rel = base_dir_for_topic(topic, Path("")).relative_to("data")
    replay_base = Path(replay_root) / "data" / rel
    prod_base = Path(compare_root) / rel

    replay_files = sorted(replay_base.glob("dt=*/hh=*/snapshot_*.parquet"))
    slots = sorted({(f.parent.parent.name, f.parent.name) for f in replay_files})
    prod_files = [
        f for dt, hh in slots for f in sorted((prod_base / dt / hh).glob("snapshot_*.parquet"))
    ]

    def keys(files: list[Path]):
        if not files:
            return None, 0
        envelope, flat = split_by_schema(files)
        flat_rows = spark.read.parquet(*flat).count() if flat else 0
        if not envelope:
            return None, flat_rows
        df = spark.read.parquet(*envelope).select(*KEY_COLS)
        df = df.where(F.col("kafka_topic") == topic)
        if ranges:
            cond = None
            for p, (lo, hi) in ranges.items():
                part = (
                    (F.col("kafka_partition") == p)
                    & (F.col("kafka_offset") >= lo)
                    & (F.col("kafka_offset") < hi)
                )
                cond = part if cond is None else (cond | part)
            df = df.where(cond)
        return df.dropDuplicates(KEY_COLS), flat_rows

    replay_df, _ = keys(replay_files)
    prod_df, prod_flat = keys(prod_files)

    counts = (0, 0, 0)
    samples: tuple[list, list] = ([], [])
    if replay_df is not None or prod_df is not None:
        empty = (replay_df if replay_df is not None else prod_df).limit(0)
        replay_df = replay_df if replay_df is not None else empty
        prod_df = prod_df if prod_df is not None else empty
        only_r = replay_df.join(prod_df, KEY_COLS, "left_anti")
        only_p = prod_df.join(replay_df, KEY_COLS, "left_anti")
        both = replay_df.join(prod_df, KEY_COLS, "inner")
        counts = (only_r.count(), only_p.count(), both.count())
        samples = (
            [r.asDict() for r in only_r.limit(SAMPLE_SIZE).collect()],
            [r.asDict() for r in only_p.limit(SAMPLE_SIZE).collect()],
        )

    return {
        "topic": topic,
        "dt_hh_slots": [f"{dt}/{hh}" for dt, hh in slots],
        "only_in_replay": counts[0],
        "only_in_prod": counts[1],
        "both": counts[2],
        "prod_rows_without_kafka_key": prod_flat,
        "sample_only_in_replay": samples[0],
        "sample_only_in_prod": samples[1],
        "match": counts[0] == 0 and counts[1] == 0,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Kafka 오프셋 되감기 격리 재적재 + 운영 raw 대조")
    ap.add_argument("--topic", required=True)
    ap.add_argument("--from-ts", required=True, help="KST ISO (예: 2026-09-30T09:00)")
    ap.add_argument("--to-ts", required=True, help="KST ISO, 종료 시각(미포함)")
    ap.add_argument("--run", default=datetime.now(KST).strftime("%Y%m%d-%H%M"))
    ap.add_argument("--out-root", type=Path, default=None)
    ap.add_argument("--group", default=DEFAULT_GROUP)
    ap.add_argument("--max-messages", type=int, default=DEFAULT_MAX_MESSAGES)
    ap.add_argument("--compare-root", type=Path, default=AI_ROOT / "data")
    ap.add_argument("--no-compare", action="store_true")
    ap.add_argument("--cores", default=None)
    ap.add_argument("--driver-memory", default=None)
    args = ap.parse_args(argv)

    try:
        from_ts, to_ts = parse_kst(args.from_ts), parse_kst(args.to_ts)
        out_root = args.out_root or default_out_root(args.topic, args.run, AI_ROOT)
        meta = replay(
            topic=args.topic,
            from_ts=from_ts,
            to_ts=to_ts,
            out_root=out_root,
            group=args.group,
            max_messages=args.max_messages,
        )
    except IsolationError as exc:
        print(f"격리 위반: {exc.message}", file=sys.stderr)
        return 2
    except (SystemExit, ValueError) as exc:
        print(f"입력 오류: {exc}", file=sys.stderr)
        return 2

    exit_code = 0
    if not args.no_compare:
        from DATA_ENGINE.spark.session import (
            DEFAULT_CORES,
            DEFAULT_DRIVER_MEMORY,
            build_spark_session,
        )

        cores = args.cores or DEFAULT_CORES
        memory = args.driver_memory or DEFAULT_DRIVER_MEMORY
        meta["spark"] = {"cores": cores, "driver_memory": memory}
        spark = build_spark_session("replay-kafka-compare", cores=cores, driver_memory=memory)
        try:
            result = compare_with_prod(
                spark,
                topic=args.topic,
                replay_root=Path(out_root),
                compare_root=args.compare_root,
                ranges=_offset_ranges(meta),
            )
        finally:
            spark.stop()
        (Path(out_root) / "compare.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(
            f"replay-compare topic={args.topic} both={result['both']} "
            f"only_in_replay={result['only_in_replay']} only_in_prod={result['only_in_prod']} "
            f"prod_rows_without_kafka_key={result['prod_rows_without_kafka_key']}"
        )
        exit_code = 0 if result["match"] else 1

    (Path(out_root) / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
