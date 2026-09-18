"""Build weather nowcast feature table from raw KMA snapshots.

Input:
    data/EXTERNAL/weather/raw/nowcast/dt=YYYY-MM-DD/hh=HH/snapshot_*.parquet

Output:
    data/EXTERNAL/weather/interim/nowcast_features/dt=YYYY-MM-DD/part.parquet

The script is dry-run by default. Pass --yes to write the output file.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from DATA_ENGINE.collect.common import AI_ROOT

KST = ZoneInfo("Asia/Seoul")
logger = logging.getLogger(__name__)
DEFAULT_INPUT_ROOT = AI_ROOT / "data" / "EXTERNAL" / "weather" / "raw" / "nowcast"
DEFAULT_OUTPUT_ROOT = AI_ROOT / "data" / "EXTERNAL" / "weather" / "interim" / "nowcast_features"

WEATHER_CATEGORIES = ["T1H", "RN1", "REH", "WSD", "PTY"]
WEATHER_FEATURE_COLUMNS = [category.lower() for category in WEATHER_CATEGORIES]
INTERIM_COLUMNS = [
    "collected_at",
    "collected_date",
    "collected_hour",
    "collected_minute",
    "weather_source",
    "base_datetime",
    "forecast_datetime",
    "nx",
    "ny",
    *WEATHER_FEATURE_COLUMNS,
]


def today_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def snapshot_files(input_root: Path, dt: str) -> list[Path]:
    return sorted(input_root.glob(f"dt={dt}/hh=*/snapshot_*.parquet"))


def read_raw_snapshots(paths: list[Path]) -> pd.DataFrame:
    if not paths:
        return pd.DataFrame()
    frames = []
    for path in paths:
        frame = pd.read_parquet(path)
        if "payload_json" in frame.columns:
            frame = flatten_kafka_weather(frame, path)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def flatten_kafka_weather(frame: pd.DataFrame, path: Path) -> pd.DataFrame:
    rows = []
    invalid = 0
    for record in frame.to_dict("records"):
        try:
            payload = json.loads(record["payload_json"])
        except (TypeError, ValueError):
            invalid += 1
            continue
        if not isinstance(payload, dict):
            invalid += 1
            continue
        if "obsrValue" in payload and "fcstValue" not in payload:
            source = "observed"
        elif "fcstValue" in payload and "obsrValue" not in payload:
            source = "forecast"
        else:
            invalid += 1
            continue
        if not {"baseDate", "baseTime", "category", "nx", "ny"}.issubset(payload):
            invalid += 1
            continue
        if source == "forecast" and not {"fcstDate", "fcstTime"}.issubset(payload):
            invalid += 1
            continue
        collected_at = record.get("poll_run_at")
        if pd.isna(collected_at):
            collected_at = record.get("ingested_at")
        rows.append(
            {
                **payload,
                "source": source,
                "collected_at": collected_at,
            }
        )
    if invalid:
        logger.warning("Skipped %d invalid Kafka weather rows in %s", invalid, path)
    return pd.DataFrame(rows, columns=[
        "baseDate", "baseTime", "fcstDate", "fcstTime", "category", "nx", "ny",
        "obsrValue", "fcstValue", "source", "collected_at",
    ])


def parse_kma_datetime(date_series: pd.Series, time_series: pd.Series) -> pd.Series:
    date_text = date_series.astype("string").str.replace("-", "", regex=False).str.zfill(8)
    time_text = time_series.astype("string").str.replace(":", "", regex=False).str.zfill(4)
    return pd.to_datetime(date_text + time_text, format="%Y%m%d%H%M", errors="coerce")


def normalize_weather_value(values: pd.Series) -> pd.Series:
    cleaned = values.astype("string").str.strip()
    cleaned = cleaned.replace(
        {
            "강수없음": "0",
            "없음": "0",
            "null": None,
            "None": None,
            "": None,
        }
    )
    return pd.to_numeric(cleaned, errors="coerce")


def normalize_weather_nowcast(raw: pd.DataFrame) -> pd.DataFrame:
    """Pivot raw KMA nowcast/forecast rows into one row per valid weather time."""
    if raw.empty:
        return pd.DataFrame(columns=INTERIM_COLUMNS)

    required = {"baseDate", "baseTime", "category", "source", "collected_at", "nx", "ny"}
    missing = sorted(required - set(raw.columns))
    if missing:
        raise ValueError(f"missing required weather raw columns: {', '.join(missing)}")

    df = raw[raw["category"].isin(WEATHER_CATEGORIES)].copy()
    if df.empty:
        return pd.DataFrame(columns=INTERIM_COLUMNS)

    df["weather_source"] = df["source"].astype("string")
    df["collected_at"] = pd.to_datetime(
        df["collected_at"], errors="coerce", utc=True
    ).dt.tz_convert(KST)
    df["base_datetime"] = parse_kma_datetime(df["baseDate"], df["baseTime"])
    if {"fcstDate", "fcstTime"}.issubset(df.columns):
        df["forecast_datetime"] = parse_kma_datetime(
            df["fcstDate"].fillna(df["baseDate"]),
            df["fcstTime"].fillna(df["baseTime"]),
        )
    else:
        df["forecast_datetime"] = df["base_datetime"]
    df["forecast_datetime"] = df["forecast_datetime"].fillna(df["base_datetime"])

    value_col = "fcstValue" if "fcstValue" in df.columns else "obsrValue"
    if "fcstValue" in df.columns and "obsrValue" in df.columns:
        df["weather_value"] = normalize_weather_value(df["fcstValue"].fillna(df["obsrValue"]))
    elif value_col in df.columns:
        df["weather_value"] = normalize_weather_value(df[value_col])
    else:
        raise ValueError("missing required weather raw value column: obsrValue or fcstValue")

    df["nx"] = pd.to_numeric(df["nx"], errors="coerce")
    df["ny"] = pd.to_numeric(df["ny"], errors="coerce")
    df = df.dropna(
        subset=[
            "collected_at", "base_datetime", "forecast_datetime", "weather_source", "nx", "ny"
        ]
    ).copy()

    # Poller and Kafka may report the same observation more than once.
    df = df.sort_values("collected_at").drop_duplicates(
        subset=[
            "weather_source", "base_datetime", "forecast_datetime", "nx", "ny", "category"
        ],
        keep="last",
    )

    index_cols = [
        "weather_source",
        "base_datetime",
        "forecast_datetime",
        "nx",
        "ny",
    ]
    collected_at = df.groupby(index_cols, dropna=False)["collected_at"].max()
    pivot = (
        df.pivot_table(
            index=index_cols,
            columns="category",
            values="weather_value",
            aggfunc="last",
        )
        .rename(columns=str.lower)
        .reset_index()
    )
    pivot = pivot.merge(collected_at.rename("collected_at").reset_index(), on=index_cols)

    for col in WEATHER_FEATURE_COLUMNS:
        if col not in pivot.columns:
            pivot[col] = pd.NA

    pivot["collected_date"] = pivot["collected_at"].dt.strftime("%Y-%m-%d")
    pivot["collected_hour"] = pivot["collected_at"].dt.hour.astype("int16")
    pivot["collected_minute"] = pivot["collected_at"].dt.minute.astype("int16")
    pivot = pivot[INTERIM_COLUMNS]
    pivot = pivot.sort_values(["forecast_datetime", "weather_source", "collected_at"])
    return pivot.reset_index(drop=True)


def build_weather_nowcast_features(input_root: Path, dt: str) -> pd.DataFrame:
    return normalize_weather_nowcast(read_raw_snapshots(snapshot_files(input_root, dt)))


def output_path(output_root: Path, dt: str) -> Path:
    return output_root / f"dt={dt}" / "part.parquet"


def write_interim(df: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        df.to_parquet(tmp_path, index=False)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=today_kst(), help="Target raw partition date YYYY-MM-DD.")
    parser.add_argument(
        "--input-root",
        type=Path,
        default=DEFAULT_INPUT_ROOT,
        help="Weather nowcast raw root.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Weather nowcast feature interim output root.",
    )
    parser.add_argument("--yes", action="store_true", help="Write output. Without this, dry-run.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    files = snapshot_files(args.input_root, args.date)
    df = build_weather_nowcast_features(args.input_root, args.date)
    out_path = output_path(args.output_root, args.date)

    print(
        "DATA_ENGINE weather nowcast batch "
        f"dry_run={str(not args.yes).lower()} "
        f"date={args.date} "
        f"snapshots={len(files)} "
        f"rows={len(df)} "
        f"output={out_path}"
    )

    if df.empty:
        print(f"WARN no weather raw snapshots found: input={args.input_root / f'dt={args.date}'}")
        return 1

    if args.yes:
        write_interim(df, out_path)
        print(f"WRITE {out_path}")
    else:
        print("DRY_RUN pass --yes to write output")
    return 0


if __name__ == "__main__":
    sys.exit(main())
