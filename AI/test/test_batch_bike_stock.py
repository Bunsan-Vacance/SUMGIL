from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from DATA_ENGINE.batch.build_bike_stock_5min import (
    INTERIM_COLUMNS,
    build_bike_stock_5min,
    main,
    normalize_bike_stock,
    output_path,
    snapshot_files,
)


def raw_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "stationId": ["ST-1", "ST-2"],
            "stationName": ["101. station", "102. station"],
            "rackTotCnt": ["10", "0"],
            "parkingBikeTotCnt": ["5", "2"],
            "shared": ["50", "0"],
            "stationLatitude": ["37.1", "37.2"],
            "stationLongitude": ["127.1", "127.2"],
            "collected_at": [
                datetime(2026, 9, 13, 1, 5, tzinfo=ZoneInfo("Asia/Seoul")),
                datetime(2026, 9, 13, 1, 5, tzinfo=ZoneInfo("Asia/Seoul")),
            ],
            "source": ["direct_poll", "direct_poll"],
        }
    )


def test_snapshot_files_returns_sorted_snapshot_paths(tmp_path):
    base = tmp_path / "raw"
    second = base / "dt=2026-09-13" / "hh=02" / "snapshot_20260913T020500.parquet"
    first = base / "dt=2026-09-13" / "hh=01" / "snapshot_20260913T010500.parquet"
    ignored = base / "dt=2026-09-13" / "hh=01" / "latest.parquet"
    for path in [second, first, ignored]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    assert snapshot_files(base, "2026-09-13") == [first, second]


def test_normalize_bike_stock_renames_and_derives_columns():
    df = normalize_bike_stock(raw_frame())

    assert list(df.columns) == INTERIM_COLUMNS
    assert df.loc[0, "station_id"] == "ST-1"
    assert df.loc[0, "rack_total_count"] == 10
    assert df.loc[0, "current_bike_count"] == 5
    assert df.loc[0, "stock_ratio"] == 0.5
    assert pd.isna(df.loc[1, "stock_ratio"])
    assert df.loc[0, "collected_date"] == "2026-09-13"
    assert df.loc[0, "collected_hour"] == 1
    assert df.loc[0, "collected_minute"] == 5


def test_normalize_bike_stock_deduplicates_station_snapshot():
    raw = pd.concat([raw_frame().head(1), raw_frame().head(1)], ignore_index=True)
    raw.loc[1, "parkingBikeTotCnt"] = "7"

    df = normalize_bike_stock(raw)

    assert len(df) == 1
    assert df.loc[0, "current_bike_count"] == 7


def test_build_bike_stock_5min_reads_date_partition(tmp_path):
    base = tmp_path / "raw"
    path = base / "dt=2026-09-13" / "hh=01" / "snapshot_20260913T010500.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw_frame().to_parquet(path, index=False)

    df = build_bike_stock_5min(base, "2026-09-13")

    assert len(df) == 2
    assert set(df["station_id"]) == {"ST-1", "ST-2"}


def test_main_is_dry_run_without_yes(tmp_path, capsys):
    input_root = tmp_path / "raw"
    out_root = tmp_path / "interim"
    path = input_root / "dt=2026-09-13" / "hh=01" / "snapshot_20260913T010500.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw_frame().to_parquet(path, index=False)

    code = main(
        [
            "--date",
            "2026-09-13",
            "--input-root",
            str(input_root),
            "--output-root",
            str(out_root),
        ]
    )

    assert code == 0
    assert "dry_run=true" in capsys.readouterr().out
    assert not output_path(out_root, "2026-09-13").exists()


def test_main_writes_output_with_yes(tmp_path):
    input_root = tmp_path / "raw"
    out_root = tmp_path / "interim"
    path = input_root / "dt=2026-09-13" / "hh=01" / "snapshot_20260913T010500.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw_frame().to_parquet(path, index=False)

    code = main(
        [
            "--date",
            "2026-09-13",
            "--input-root",
            str(input_root),
            "--output-root",
            str(out_root),
            "--yes",
        ]
    )

    written = output_path(out_root, "2026-09-13")
    assert code == 0
    assert written.exists()
    assert len(pd.read_parquet(written)) == 2
