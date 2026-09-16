"""Persist parsed Kafka events into DATA_ENGINE raw parquet partitions."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from DATA_ENGINE.collect.common import AI_ROOT, KST, save_latest_parquet
from DATA_ENGINE.stream.kafka_events import KafkaEvent

TOPIC_BASE_DIRS = {
    "bike.stock": AI_ROOT / "data" / "BIKE" / "raw" / "realtime",
    "weather.nowcast": AI_ROOT / "data" / "EXTERNAL" / "weather" / "raw" / "nowcast",
    "subway.arrival": AI_ROOT / "data" / "SUBWAY" / "raw" / "arrival",
}
BIKE_STOCK_TOPIC = "bike.stock"
BIKE_LATEST_STOCK_RELATIVE_PATH = Path("data/BIKE/raw/realtime/latest_stock.parquet")
BIKE_LATEST_STOCK_COLUMNS = ["rental_id", "current_stock", "updated_at"]


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


def dedupe_events(events: list[KafkaEvent]) -> list[KafkaEvent]:
    """Keep the first event for each event_id within one flush batch."""
    seen: set[str] = set()
    unique: list[KafkaEvent] = []
    for event in events:
        if event.event_id in seen:
            continue
        seen.add(event.event_id)
        unique.append(event)
    return unique


def latest_stock_path(*, ai_root: Path = AI_ROOT) -> Path:
    return Path(ai_root) / BIKE_LATEST_STOCK_RELATIVE_PATH


def _payload_dict(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        decoded = json.loads(payload)
        if isinstance(decoded, dict):
            return decoded
    return {}


def _naive_kst(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(KST).replace(tzinfo=None)


def _bike_latest_stock_rows(events: list[KafkaEvent]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for event in events:
        topic = event.kafka_topic or event.source
        if topic != BIKE_STOCK_TOPIC:
            continue

        payload = _payload_dict(event.payload)
        rental_id = str(event.entity_id or payload.get("stationId", "")).strip()
        stock_value = payload.get("parkingBikeTotCnt")
        if not rental_id or stock_value in (None, ""):
            continue

        try:
            current_stock = int(stock_value)
        except (TypeError, ValueError):
            continue

        rows.append(
            {
                "rental_id": rental_id,
                "current_stock": current_stock,
                "updated_at": _naive_kst(event.freshness_time),
            }
        )

    return pd.DataFrame(rows, columns=BIKE_LATEST_STOCK_COLUMNS)


def update_bike_latest_stock(events: list[KafkaEvent], *, ai_root: Path = AI_ROOT) -> Path | None:
    """Upsert station-level latest bike stock from bike.stock events."""
    latest_rows = _bike_latest_stock_rows(dedupe_events(events))
    if latest_rows.empty:
        return None

    path = latest_stock_path(ai_root=ai_root)
    if path.exists():
        current = pd.read_parquet(path)
        combined = pd.concat([current, latest_rows], ignore_index=True)
    else:
        combined = latest_rows

    combined["updated_at"] = pd.to_datetime(combined["updated_at"])
    combined = (
        combined.sort_values(["rental_id", "updated_at"])
        .drop_duplicates(subset=["rental_id"], keep="last")
        .sort_values("rental_id")
        .reset_index(drop=True)
    )
    return save_latest_parquet(combined[BIKE_LATEST_STOCK_COLUMNS], path)


def write_events(events: list[KafkaEvent], *, ai_root: Path = AI_ROOT) -> list[Path]:
    """Write events grouped by topic and poll run time.

    ``poll_run_at`` is the intended snapshot run boundary from BE. If it is not
    present, ``ingested_at`` becomes the fallback partition time.
    """
    grouped: dict[tuple[str, datetime], list[KafkaEvent]] = defaultdict(list)
    for event in dedupe_events(events):
        topic = event.kafka_topic or event.source
        grouped[(topic, event.partition_time)].append(event)

    paths: list[Path] = []
    for (topic, partition_time), batch in sorted(grouped.items(), key=lambda x: x[0]):
        base_dir = base_dir_for_topic(topic, ai_root=ai_root)
        path = _snapshot_path(base_dir, partition_time)
        frame = pd.DataFrame([event.to_record() for event in batch])
        frame.to_parquet(path, index=False)
        paths.append(path)
    latest_path = update_bike_latest_stock(events, ai_root=ai_root)
    if latest_path is not None:
        paths.append(latest_path)
    return paths
