"""Persist parsed Kafka events into DATA_ENGINE raw parquet partitions."""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from DATA_ENGINE.collect.common import AI_ROOT
from DATA_ENGINE.stream.kafka_events import KafkaEvent

TOPIC_BASE_DIRS = {
    "bike.stock": AI_ROOT / "data" / "BIKE" / "raw" / "realtime",
    "weather.nowcast": AI_ROOT / "data" / "EXTERNAL" / "weather" / "raw" / "nowcast",
    "subway.arrival": AI_ROOT / "data" / "SUBWAY" / "raw" / "arrival",
}


def base_dir_for_topic(topic: str, ai_root: Path = AI_ROOT) -> Path:
    relative = {
        "bike.stock": Path("data/BIKE/raw/realtime"),
        "weather.nowcast": Path("data/EXTERNAL/weather/raw/nowcast"),
        "subway.arrival": Path("data/SUBWAY/raw/arrival"),
    }.get(topic)
    if relative is None:
        raise ValueError(f"unsupported Kafka topic: {topic}")
    return Path(ai_root) / relative


def _snapshot_path(base_dir: Path, partition_time: datetime) -> Path:
    out_dir = base_dir / f"dt={partition_time:%Y-%m-%d}" / f"hh={partition_time:%H}"
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"snapshot_{partition_time:%Y%m%dT%H%M%S}_{os.getpid()}.parquet"
    return out_dir / filename


def write_events(events: list[KafkaEvent], *, ai_root: Path = AI_ROOT) -> list[Path]:
    """Write events grouped by topic and poll run time.

    ``poll_run_at`` is the intended snapshot run boundary from BE. If it is not
    present, ``ingested_at`` becomes the fallback partition time.
    """
    grouped: dict[tuple[str, datetime], list[KafkaEvent]] = defaultdict(list)
    for event in events:
        topic = event.kafka_topic or event.source
        grouped[(topic, event.partition_time)].append(event)

    paths: list[Path] = []
    for (topic, partition_time), batch in sorted(grouped.items(), key=lambda x: x[0]):
        base_dir = base_dir_for_topic(topic, ai_root=ai_root)
        path = _snapshot_path(base_dir, partition_time)
        frame = pd.DataFrame([event.to_record() for event in batch])
        frame.to_parquet(path, index=False)
        paths.append(path)
    return paths
