"""Publish observed Kafka weather in the BIKE ETA service's file contract."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from DATA_ENGINE.collect.common import AI_ROOT, save_latest_parquet
from DATA_ENGINE.stream.weather_latest import latest_weather_path

BIKE_WEATHER_RELATIVE_PATH = Path("data/EXTERNAL/weather/raw/nowcast/latest_weather.parquet")
BIKE_WEATHER_NX = 60
BIKE_WEATHER_NY = 127
BIKE_WEATHER_COLUMNS = ["temp", "is_rain", "updated_at"]


def bike_weather_path(*, ai_root: Path = AI_ROOT) -> Path:
    return Path(ai_root) / BIKE_WEATHER_RELATIVE_PATH


def _weather_number(value: object) -> float | None:
    if value in ("강수없음", "없음"):
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def update_bike_weather(*, ai_root: Path = AI_ROOT) -> Path | None:
    """Use a complete observed T1H/RN1 pair from the representative grid."""
    common_path = latest_weather_path(ai_root=ai_root)
    if not common_path.exists():
        return None
    frame = pd.read_parquet(common_path)
    observed = frame[
        (frame["nx"] == BIKE_WEATHER_NX)
        & (frame["ny"] == BIKE_WEATHER_NY)
        & (frame["weather_source"] == "observed")
        & (frame["category"].isin(["T1H", "RN1"]))
    ]
    if observed.empty:
        return None

    values = observed.pivot_table(
        index="base_datetime", columns="category", values="weather_value", aggfunc="last"
    )
    if not {"T1H", "RN1"}.issubset(values.columns):
        return None
    complete = values.dropna(subset=["T1H", "RN1"])
    if complete.empty:
        return None
    observed_at = complete.index.max()
    temp = _weather_number(complete.loc[observed_at, "T1H"])
    rain = _weather_number(complete.loc[observed_at, "RN1"])
    if temp is None or rain is None or rain < 0:
        return None

    path = bike_weather_path(ai_root=ai_root)
    if path.exists():
        previous = pd.read_parquet(path)
        if not previous.empty and pd.Timestamp(previous.iloc[0]["updated_at"]) >= observed_at:
            return None
    row = pd.DataFrame(
        [{"temp": temp, "is_rain": rain > 0, "updated_at": observed_at}],
        columns=BIKE_WEATHER_COLUMNS,
    )
    return save_latest_parquet(row, path)
