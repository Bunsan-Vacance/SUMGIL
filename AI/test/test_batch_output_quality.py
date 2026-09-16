from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from DATA_ENGINE.monitor.check_batch_outputs import (
    BIKE_REQUIRED_COLUMNS,
    WEATHER_REQUIRED_COLUMNS,
    BatchOutputCheck,
    build_checks,
    check_batch_outputs,
    check_bike_output,
    check_weather_output,
    main,
    output_path,
)


def bike_frame() -> pd.DataFrame:
    collected_at = datetime(2026, 9, 13, 1, 42, tzinfo=ZoneInfo("Asia/Seoul"))
    return pd.DataFrame(
        {
            "station_id": ["ST-1", "ST-2"],
            "station_name": ["101. station", "102. station"],
            "rack_total_count": [10, 20],
            "current_bike_count": [5, 12],
            "shared": [50, 60],
            "stock_ratio": [0.5, 0.6],
            "station_latitude": [37.1, 37.2],
            "station_longitude": [127.1, 127.2],
            "collected_at": [collected_at, collected_at],
            "collected_date": ["2026-09-13", "2026-09-13"],
            "collected_hour": [1, 1],
            "collected_minute": [42, 42],
            "source": ["direct_poll", "direct_poll"],
        }
    )


def weather_frame() -> pd.DataFrame:
    collected_at = datetime(2026, 9, 13, 1, 42, tzinfo=ZoneInfo("Asia/Seoul"))
    return pd.DataFrame(
        {
            "collected_at": [collected_at, collected_at],
            "collected_date": ["2026-09-13", "2026-09-13"],
            "collected_hour": [1, 1],
            "collected_minute": [42, 42],
            "weather_source": ["observed", "forecast"],
            "base_datetime": [
                pd.Timestamp("2026-09-13 01:00"),
                pd.Timestamp("2026-09-13 01:30"),
            ],
            "forecast_datetime": [
                pd.Timestamp("2026-09-13 01:00"),
                pd.Timestamp("2026-09-13 02:00"),
            ],
            "nx": [60, 60],
            "ny": [127, 127],
            "t1h": [24.1, 25.0],
            "rn1": [0.0, 0.0],
            "reh": [60.0, 68.0],
            "wsd": [1.0, 2.1],
            "pty": [0.0, 0.0],
        }
    )


def crowd_frame() -> pd.DataFrame:
    """197 점검용 최소 CROWD 서빙 표 — 음수 인원이 없는 정상 판."""
    return pd.DataFrame(
        {
            "station_no": [150, 150],
            "boarding_pred": [676.4, 0.0],
            "alighting_pred": [2258.5, 12.3],
            "pred_clipped": [False, True],
        }
    )


def write_output(root, relative_path: str, df: pd.DataFrame) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def test_build_checks_uses_expected_batch_output_paths(tmp_path):
    checks = build_checks(
        tmp_path, "2026-09-13", bike_min_rows=10, weather_min_rows=5, crowd_min_rows=7
    )

    assert checks == [
        BatchOutputCheck(
            name="bike",
            path=tmp_path / "data/BIKE/interim/realtime_stock_5min/dt=2026-09-13/part.parquet",
            min_rows=10,
        ),
        BatchOutputCheck(
            name="weather",
            path=tmp_path
            / "data/EXTERNAL/weather/interim/nowcast_features/dt=2026-09-13/part.parquet",
            min_rows=5,
        ),
        BatchOutputCheck(
            name="crowd",
            path=tmp_path / "data/CROWD/serving/predictions_2026-09-13.parquet",
            min_rows=7,
        ),
    ]


def test_output_path_uses_date_partition():
    assert (
        output_path(Path("/tmp/out"), "2026-09-13").as_posix()
        == "/tmp/out/dt=2026-09-13/part.parquet"
    )


def test_bike_output_ok(tmp_path):
    path = tmp_path / "bike.parquet"
    bike_frame().to_parquet(path, index=False)

    result = check_bike_output(BatchOutputCheck("bike", path, min_rows=2))

    assert result.ok is True
    assert result.status == "ok"
    assert "OK bike batch output" in result.message


def test_bike_output_missing_file_fails(tmp_path):
    result = check_bike_output(BatchOutputCheck("bike", tmp_path / "missing.parquet", min_rows=1))

    assert result.ok is False
    assert result.status == "missing"
    assert "FAIL bike batch output missing" in result.message


def test_bike_output_missing_required_column_fails(tmp_path):
    path = tmp_path / "bike.parquet"
    bike_frame().drop(columns=["station_id"]).to_parquet(path, index=False)

    result = check_bike_output(BatchOutputCheck("bike", path, min_rows=1))

    assert result.ok is False
    assert result.status == "missing_columns"
    assert "station_id" in result.message


def test_bike_output_low_rows_fails_before_column_checks(tmp_path):
    path = tmp_path / "bike.parquet"
    bike_frame().to_parquet(path, index=False)

    result = check_bike_output(BatchOutputCheck("bike", path, min_rows=3))

    assert result.ok is False
    assert result.status == "low_rows"


def test_bike_output_negative_current_count_fails(tmp_path):
    path = tmp_path / "bike.parquet"
    df = bike_frame()
    df.loc[0, "current_bike_count"] = -1
    df.to_parquet(path, index=False)

    result = check_bike_output(BatchOutputCheck("bike", path, min_rows=1))

    assert result.ok is False
    assert result.status == "negative_current_bike_count"


def test_bike_output_negative_stock_ratio_fails(tmp_path):
    path = tmp_path / "bike.parquet"
    df = bike_frame()
    df.loc[0, "stock_ratio"] = -0.1
    df.to_parquet(path, index=False)

    result = check_bike_output(BatchOutputCheck("bike", path, min_rows=1))

    assert result.ok is False
    assert result.status == "negative_stock_ratio"


def test_bike_output_high_stock_ratio_is_reported_not_failed(tmp_path):
    path = tmp_path / "bike.parquet"
    df = bike_frame()
    df.loc[0, "stock_ratio"] = 12.14
    df.to_parquet(path, index=False)

    result = check_bike_output(BatchOutputCheck("bike", path, min_rows=1))

    assert result.ok is True
    assert "max_stock_ratio=12.14" in result.message


def test_bike_output_duplicate_station_snapshot_fails(tmp_path):
    path = tmp_path / "bike.parquet"
    df = pd.concat([bike_frame(), bike_frame().head(1)], ignore_index=True)
    df.to_parquet(path, index=False)

    result = check_bike_output(BatchOutputCheck("bike", path, min_rows=1))

    assert result.ok is False
    assert result.status == "duplicate_station_snapshot"


def test_weather_output_ok(tmp_path):
    path = tmp_path / "weather.parquet"
    weather_frame().to_parquet(path, index=False)

    result = check_weather_output(BatchOutputCheck("weather", path, min_rows=2))

    assert result.ok is True
    assert result.status == "ok"
    assert "OK weather batch output" in result.message


def test_weather_output_invalid_source_fails(tmp_path):
    path = tmp_path / "weather.parquet"
    df = weather_frame()
    df.loc[0, "weather_source"] = "bad"
    df.to_parquet(path, index=False)

    result = check_weather_output(BatchOutputCheck("weather", path, min_rows=1))

    assert result.ok is False
    assert result.status == "invalid_weather_source"


def test_weather_output_reh_out_of_range_fails(tmp_path):
    path = tmp_path / "weather.parquet"
    df = weather_frame()
    df.loc[0, "reh"] = 101
    df.to_parquet(path, index=False)

    result = check_weather_output(BatchOutputCheck("weather", path, min_rows=1))

    assert result.ok is False
    assert result.status == "invalid_reh_range"


def test_weather_output_all_feature_values_null_fails(tmp_path):
    path = tmp_path / "weather.parquet"
    df = weather_frame()
    df[["t1h", "rn1", "reh", "wsd", "pty"]] = pd.NA
    df.to_parquet(path, index=False)

    result = check_weather_output(BatchOutputCheck("weather", path, min_rows=1))

    assert result.ok is False
    assert result.status == "empty_weather_features"


def test_check_batch_outputs_rejects_unknown_check_name(tmp_path):
    with pytest.raises(ValueError, match="unknown batch output check"):
        check_batch_outputs([BatchOutputCheck("unknown", tmp_path / "out.parquet", min_rows=1)])


def test_main_returns_zero_when_all_outputs_are_ok(tmp_path, capsys):
    write_output(
        tmp_path,
        "data/BIKE/interim/realtime_stock_5min/dt=2026-09-13/part.parquet",
        bike_frame(),
    )
    write_output(
        tmp_path,
        "data/EXTERNAL/weather/interim/nowcast_features/dt=2026-09-13/part.parquet",
        weather_frame(),
    )
    write_output(tmp_path, "data/CROWD/serving/predictions_2026-09-13.parquet", crowd_frame())

    code = main(
        [
            "--ai-root",
            str(tmp_path),
            "--date",
            "2026-09-13",
            "--bike-min-rows",
            "2",
            "--weather-min-rows",
            "2",
            "--crowd-min-rows",
            "2",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "DATA_ENGINE batch output quality OK" in captured.out


def test_main_returns_one_when_any_output_fails(tmp_path, capsys):
    write_output(
        tmp_path,
        "data/BIKE/interim/realtime_stock_5min/dt=2026-09-13/part.parquet",
        bike_frame(),
    )

    code = main(
        [
            "--ai-root",
            str(tmp_path),
            "--date",
            "2026-09-13",
            "--bike-min-rows",
            "2",
            "--weather-min-rows",
            "2",
        ]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "FAIL weather batch output missing" in captured.out
    assert "DATA_ENGINE batch output quality FAILED" in captured.out


def test_required_columns_match_current_batch_contracts():
    assert "station_id" in BIKE_REQUIRED_COLUMNS
    assert "current_bike_count" in BIKE_REQUIRED_COLUMNS
    assert "weather_source" in WEATHER_REQUIRED_COLUMNS
    assert "forecast_datetime" in WEATHER_REQUIRED_COLUMNS
