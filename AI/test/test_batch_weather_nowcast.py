from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from DATA_ENGINE.batch.build_weather_nowcast_features import (
    INTERIM_COLUMNS,
    build_weather_nowcast_features,
    main,
    normalize_weather_nowcast,
    normalize_weather_value,
    output_path,
    snapshot_files,
)


def raw_frame() -> pd.DataFrame:
    collected_at = datetime(2026, 9, 13, 1, 12, tzinfo=ZoneInfo("Asia/Seoul"))
    return pd.DataFrame(
        [
            {
                "baseDate": "20260913",
                "baseTime": "0100",
                "category": "T1H",
                "obsrValue": "24.1",
                "fcstDate": None,
                "fcstTime": None,
                "fcstValue": None,
                "nx": "60",
                "ny": "127",
                "source": "observed",
                "collected_at": collected_at,
            },
            {
                "baseDate": "20260913",
                "baseTime": "0100",
                "category": "RN1",
                "obsrValue": "강수없음",
                "fcstDate": None,
                "fcstTime": None,
                "fcstValue": None,
                "nx": "60",
                "ny": "127",
                "source": "observed",
                "collected_at": collected_at,
            },
            {
                "baseDate": "20260913",
                "baseTime": "0130",
                "category": "T1H",
                "obsrValue": None,
                "fcstDate": "20260913",
                "fcstTime": "0200",
                "fcstValue": "25",
                "nx": "60",
                "ny": "127",
                "source": "forecast",
                "collected_at": collected_at,
            },
            {
                "baseDate": "20260913",
                "baseTime": "0130",
                "category": "REH",
                "obsrValue": None,
                "fcstDate": "20260913",
                "fcstTime": "0200",
                "fcstValue": "70",
                "nx": "60",
                "ny": "127",
                "source": "forecast",
                "collected_at": collected_at,
            },
        ]
    )


def test_snapshot_files_returns_sorted_snapshot_paths(tmp_path):
    base = tmp_path / "raw"
    second = base / "dt=2026-09-13" / "hh=02" / "snapshot_20260913T020200.parquet"
    first = base / "dt=2026-09-13" / "hh=01" / "snapshot_20260913T010200.parquet"
    ignored = base / "dt=2026-09-13" / "hh=01" / "latest.parquet"
    for path in [second, first, ignored]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    assert snapshot_files(base, "2026-09-13") == [first, second]


def test_normalize_weather_value_converts_no_rain_to_zero():
    values = normalize_weather_value(pd.Series(["강수없음", "1.5", ""]))

    assert values.tolist()[:2] == [0.0, 1.5]
    assert pd.isna(values.iloc[2])


def test_normalize_weather_nowcast_pivots_categories():
    df = normalize_weather_nowcast(raw_frame())

    assert list(df.columns) == INTERIM_COLUMNS
    assert len(df) == 2

    observed = df[df["weather_source"] == "observed"].iloc[0]
    forecast = df[df["weather_source"] == "forecast"].iloc[0]

    assert observed["t1h"] == 24.1
    assert observed["rn1"] == 0
    assert observed["collected_date"] == "2026-09-13"
    assert observed["collected_hour"] == 1
    assert observed["collected_minute"] == 12
    assert forecast["t1h"] == 25
    assert forecast["reh"] == 70
    assert forecast["forecast_datetime"].strftime("%Y-%m-%d %H:%M") == "2026-09-13 02:00"


def test_build_weather_nowcast_features_reads_date_partition(tmp_path):
    base = tmp_path / "raw"
    path = base / "dt=2026-09-13" / "hh=01" / "snapshot_20260913T011200.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw_frame().to_parquet(path, index=False)

    df = build_weather_nowcast_features(base, "2026-09-13")

    assert len(df) == 2
    assert set(df["weather_source"]) == {"observed", "forecast"}


def test_main_is_dry_run_without_yes(tmp_path, capsys):
    input_root = tmp_path / "raw"
    out_root = tmp_path / "interim"
    path = input_root / "dt=2026-09-13" / "hh=01" / "snapshot_20260913T011200.parquet"
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
    path = input_root / "dt=2026-09-13" / "hh=01" / "snapshot_20260913T011200.parquet"
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
