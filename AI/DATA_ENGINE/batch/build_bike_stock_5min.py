"""Build 5-minute bike stock interim table from realtime raw snapshots.

Input:
    data/BIKE/raw/realtime/dt=YYYY-MM-DD/hh=HH/snapshot_*.parquet

Output:
    data/BIKE/interim/realtime_stock_5min/dt=YYYY-MM-DD/part.parquet

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
DEFAULT_INPUT_ROOT = AI_ROOT / "data" / "BIKE" / "raw" / "realtime"
DEFAULT_OUTPUT_ROOT = AI_ROOT / "data" / "BIKE" / "interim" / "realtime_stock_5min"

RAW_TO_INTERIM_COLUMNS = {
    "stationId": "station_id",
    "stationName": "station_name",
    "rackTotCnt": "rack_total_count",
    "parkingBikeTotCnt": "current_bike_count",
    "shared": "shared",
    "stationLatitude": "station_latitude",
    "stationLongitude": "station_longitude",
}

INTERIM_COLUMNS = [
    "station_id",
    "station_name",
    "rack_total_count",
    "current_bike_count",
    "shared",
    "stock_ratio",
    "station_latitude",
    "station_longitude",
    "collected_at",
    "collected_date",
    "collected_hour",
    "collected_minute",
    "source",
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
            frame = flatten_kafka_bike(frame, path)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def flatten_kafka_bike(frame: pd.DataFrame, path: Path) -> pd.DataFrame:
    """Convert bike.stock envelope rows to the direct bikeList raw schema."""
    rows = []
    invalid = 0
    required_payload = set(RAW_TO_INTERIM_COLUMNS)

    for record in frame.to_dict("records"):
        try:
            payload = json.loads(record["payload_json"])
        except (KeyError, TypeError, ValueError):
            invalid += 1
            continue
        if not isinstance(payload, dict) or not required_payload.issubset(payload):
            invalid += 1
            continue

        entity_id = record.get("entity_id")
        payload_id = payload.get("stationId")
        if pd.isna(entity_id) or str(entity_id).strip() == "":
            entity_id = payload_id
        if str(entity_id).strip() != str(payload_id).strip():
            invalid += 1
            continue

        collected_at = pd.to_datetime(record.get("ingested_at"), errors="coerce", utc=True)
        if pd.isna(collected_at):
            invalid += 1
            continue
        collected_at = collected_at.tz_convert(KST)

        rows.append(
            {
                **payload,
                "stationId": str(entity_id).strip(),
                "collected_at": collected_at,
                "source": "bike.stock",
            }
        )

    if invalid:
        logger.warning("Skipped %d invalid Kafka bike rows in %s", invalid, path)
    return pd.DataFrame(rows, columns=[*RAW_TO_INTERIM_COLUMNS, "collected_at", "source"])


def normalize_bike_stock(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize raw bikeList snapshots to stable feature-engineering columns."""
    if raw.empty:
        return pd.DataFrame(columns=INTERIM_COLUMNS)

    missing = sorted(set(RAW_TO_INTERIM_COLUMNS) - set(raw.columns))
    if missing:
        raise ValueError(f"missing required bike raw columns: {', '.join(missing)}")
    if "collected_at" not in raw.columns:
        raise ValueError("missing required bike raw column: collected_at")

    df = raw.rename(columns=RAW_TO_INTERIM_COLUMNS).copy()
    if "source" not in df.columns:
        df["source"] = "unknown"

    numeric_cols = [
        "rack_total_count",
        "current_bike_count",
        "shared",
        "station_latitude",
        "station_longitude",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["collected_at"] = pd.to_datetime(df["collected_at"], errors="coerce")
    df = df.dropna(subset=["station_id", "collected_at"]).copy()

    rack = df["rack_total_count"].where(df["rack_total_count"] > 0)
    df["stock_ratio"] = df["current_bike_count"] / rack
    df["collected_date"] = df["collected_at"].dt.strftime("%Y-%m-%d")
    df["collected_hour"] = df["collected_at"].dt.hour.astype("int16")
    df["collected_minute"] = df["collected_at"].dt.minute.astype("int16")

    df["_slot_5m"] = df["collected_at"].dt.floor("5min")
    df = df.sort_values(["collected_at", "station_id"]).drop_duplicates(
        ["_slot_5m", "station_id"], keep="last"
    )
    return df[INTERIM_COLUMNS].reset_index(drop=True)


def build_bike_stock_5min(input_root: Path, dt: str) -> pd.DataFrame:
    return normalize_bike_stock(read_raw_snapshots(snapshot_files(input_root, dt)))


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
        help="Bike realtime raw root.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Bike 5-minute stock interim output root.",
    )
    parser.add_argument("--yes", action="store_true", help="Write output. Without this, dry-run.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    files = snapshot_files(args.input_root, args.date)
    df = build_bike_stock_5min(args.input_root, args.date)
    out_path = output_path(args.output_root, args.date)

    print(
        "DATA_ENGINE bike stock 5min batch "
        f"dry_run={str(not args.yes).lower()} "
        f"date={args.date} "
        f"snapshots={len(files)} "
        f"rows={len(df)} "
        f"output={out_path}"
    )

    if df.empty:
        print(f"WARN no bike raw snapshots found: input={args.input_root / f'dt={args.date}'}")
        return 1

    if args.yes:
        write_interim(df, out_path)
        print(f"WRITE {out_path}")
    else:
        print("DRY_RUN pass --yes to write output")
    return 0


if __name__ == "__main__":
    sys.exit(main())
