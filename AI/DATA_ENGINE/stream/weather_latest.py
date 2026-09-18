"""Maintain a weather latest view without dropping grid or forecast horizons."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from DATA_ENGINE.collect.common import AI_ROOT, KST, save_latest_parquet
from DATA_ENGINE.stream.kafka_events import KafkaEvent

logger = logging.getLogger(__name__)

WEATHER_TOPIC = "weather.nowcast"
LATEST_WEATHER_RELATIVE_PATH = Path("data/EXTERNAL/weather/raw/nowcast/latest_by_grid.parquet")
LATEST_WEATHER_COLUMNS = [
    "nx", "ny", "weather_source", "category", "base_datetime", "forecast_datetime",
    "weather_value", "source_generated_at", "ingested_at", "event_id",
]
SERIES_KEY = ["nx", "ny", "weather_source", "category"]
VALUE_KEY = [*SERIES_KEY, "forecast_datetime"]


def latest_weather_path(*, ai_root: Path = AI_ROOT) -> Path:
    return Path(ai_root) / LATEST_WEATHER_RELATIVE_PATH


def _naive_kst(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(KST).replace(tzinfo=None) if value.tzinfo else value


def _weather_row(event: KafkaEvent) -> dict[str, object] | None:
    if (event.kafka_topic or event.source) != WEATHER_TOPIC or not isinstance(event.payload, dict):
        return None

    payload = event.payload
    observed = "obsrValue" in payload and "fcstValue" not in payload
    forecast = "fcstValue" in payload and "obsrValue" not in payload
    if not (observed or forecast):
        return None
    value = payload.get("obsrValue" if observed else "fcstValue")
    if value in (None, "") or not str(payload.get("category", "")).strip():
        return None
    try:
        nx = int(payload["nx"])
        ny = int(payload["ny"])
        base_datetime = datetime.strptime(
            str(payload["baseDate"]) + str(payload["baseTime"]).zfill(4), "%Y%m%d%H%M"
        ).replace(tzinfo=KST)
        forecast_datetime = (
            base_datetime
            if observed
            else datetime.strptime(
                str(payload["fcstDate"]) + str(payload["fcstTime"]).zfill(4),
                "%Y%m%d%H%M",
            ).replace(tzinfo=KST)
        )
    except (KeyError, TypeError, ValueError):
        return None

    return {
        "nx": nx,
        "ny": ny,
        "weather_source": "observed" if observed else "forecast",
        "category": str(payload["category"]),
        "base_datetime": _naive_kst(base_datetime),
        "forecast_datetime": _naive_kst(forecast_datetime),
        "weather_value": str(value),
        "source_generated_at": _naive_kst(event.source_generated_at),
        "ingested_at": _naive_kst(event.ingested_at),
        "event_id": event.event_id,
    }


def update_weather_latest(events: list[KafkaEvent], *, ai_root: Path = AI_ROOT) -> Path | None:
    """Retain the newest issue per grid/kind/category and all its forecast horizons."""
    rows = []
    invalid = 0
    for event in events:
        if (event.kafka_topic or event.source) != WEATHER_TOPIC:
            continue
        row = _weather_row(event)
        if row is None:
            invalid += 1
        else:
            rows.append(row)
    if invalid:
        logger.warning("Skipped %d invalid Kafka weather events in latest view", invalid)
    if not rows:
        return None

    path = latest_weather_path(ai_root=ai_root)
    incoming = pd.DataFrame(rows, columns=LATEST_WEATHER_COLUMNS)
    combined = pd.concat([pd.read_parquet(path), incoming], ignore_index=True) if path.exists() else incoming
    for column in ("base_datetime", "forecast_datetime", "source_generated_at", "ingested_at"):
        combined[column] = pd.to_datetime(combined[column], errors="coerce")

    newest_base = combined.groupby(SERIES_KEY, dropna=False)["base_datetime"].transform("max")
    combined = combined[combined["base_datetime"] == newest_base]
    combined = (
        combined.sort_values([*VALUE_KEY, "source_generated_at", "ingested_at", "event_id"])
        .drop_duplicates(subset=VALUE_KEY, keep="last")
        .sort_values(VALUE_KEY)
        .reset_index(drop=True)
    )
    return save_latest_parquet(combined[LATEST_WEATHER_COLUMNS], path)
