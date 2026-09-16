"""Check DATA_ENGINE batch output parquet quality."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from pyarrow.lib import ArrowException

from DATA_ENGINE.collect.common import KST

AI_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BIKE_OUTPUT = Path("data/BIKE/interim/realtime_stock_5min")
DEFAULT_WEATHER_OUTPUT = Path("data/EXTERNAL/weather/interim/nowcast_features")
DEFAULT_CROWD_OUTPUT = Path("data/CROWD/serving")
DEFAULT_BIKE_MIN_ROWS = 100_000
DEFAULT_WEATHER_MIN_ROWS = 100
# CROWD 서빙 표는 1일치 21,606행(273역 × 20슬롯 × 방향 × 30분 2슬롯)이다.
DEFAULT_CROWD_MIN_ROWS = 20_000

BIKE_REQUIRED_COLUMNS = [
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

WEATHER_REQUIRED_COLUMNS = [
    "collected_at",
    "collected_date",
    "collected_hour",
    "collected_minute",
    "weather_source",
    "base_datetime",
    "forecast_datetime",
    "nx",
    "ny",
    "t1h",
    "rn1",
    "reh",
    "wsd",
    "pty",
]

WEATHER_FEATURE_COLUMNS = ["t1h", "rn1", "reh", "wsd", "pty"]
WEATHER_SOURCES = {"observed", "forecast"}

# 197: CROWD 서빙 표는 `dt=`/`part.parquet` 파티션이 아니라 날짜별 단일 parquet
# (`predictions_YYYY-MM-DD.parquet`)이다. `boarding_pred`·`alighting_pred`·`pred_clipped`는
# BIKE·weather 산출물에는 없는 컬럼이라 이 점검은 CROWD 전용이다(check_crowd_output에서만 쓴다).
CROWD_REQUIRED_COLUMNS = [
    "station_no",
    "boarding_pred",
    "alighting_pred",
    "pred_clipped",
]


@dataclass(frozen=True)
class BatchOutputCheck:
    name: str
    path: Path
    min_rows: int


@dataclass(frozen=True)
class BatchOutputResult:
    name: str
    path: Path
    ok: bool
    status: str
    message: str
    rows: int | None = None


def default_date() -> str:
    """Return the default batch output date: yesterday in KST."""
    return (datetime.now(KST).date() - timedelta(days=1)).isoformat()


def output_path(output_root: Path, dt: str) -> Path:
    return output_root / f"dt={dt}" / "part.parquet"


def crowd_output_path(output_root: Path, dt: str) -> Path:
    """CROWD 서빙 표는 파티션 폴더가 아니라 날짜별 단일 parquet(`batch_predict.py` 참고)."""
    return output_root / f"predictions_{dt}.parquet"


def missing_columns(df: pd.DataFrame, required_columns: Iterable[str]) -> list[str]:
    return sorted(set(required_columns) - set(df.columns))


def fail(
    name: str, path: Path, status: str, message: str, rows: int | None = None
) -> BatchOutputResult:
    return BatchOutputResult(
        name=name,
        path=path,
        ok=False,
        status=status,
        rows=rows,
        message=f"FAIL {name} {message}",
    )


def ok(name: str, path: Path, message: str, rows: int) -> BatchOutputResult:
    return BatchOutputResult(
        name=name,
        path=path,
        ok=True,
        status="ok",
        rows=rows,
        message=f"OK {name} {message}",
    )


def read_output(name: str, path: Path) -> tuple[pd.DataFrame | None, BatchOutputResult | None]:
    if not path.exists():
        return None, fail(name, path, "missing", f"batch output missing: path={path}")

    try:
        return pd.read_parquet(path), None
    except (OSError, ValueError, ArrowException) as exc:
        return None, fail(
            name,
            path,
            "read_error",
            f"batch output read error: path={path} error={exc}",
        )


def check_common(
    check: BatchOutputCheck,
    df: pd.DataFrame,
    required_columns: Iterable[str],
) -> BatchOutputResult | None:
    if check.min_rows <= 0:
        raise ValueError("min_rows must be positive")

    rows = len(df)
    if rows < check.min_rows:
        return fail(
            check.name,
            check.path,
            "low_rows",
            f"batch output rows low: rows={rows} min={check.min_rows} path={check.path}",
            rows=rows,
        )

    missing = missing_columns(df, required_columns)
    if missing:
        return fail(
            check.name,
            check.path,
            "missing_columns",
            f"batch output columns missing: columns={','.join(missing)} path={check.path}",
            rows=rows,
        )
    return None


def check_bike_output(check: BatchOutputCheck) -> BatchOutputResult:
    df, error = read_output(check.name, check.path)
    if error is not None:
        return error
    assert df is not None

    common_error = check_common(check, df, BIKE_REQUIRED_COLUMNS)
    if common_error is not None:
        return common_error

    rows = len(df)
    if df["station_id"].isna().any():
        return fail(check.name, check.path, "null_station_id", "station_id null found", rows)
    if df["collected_at"].isna().any():
        return fail(check.name, check.path, "null_collected_at", "collected_at null found", rows)
    if (pd.to_numeric(df["current_bike_count"], errors="coerce") < 0).any():
        return fail(
            check.name,
            check.path,
            "negative_current_bike_count",
            "current_bike_count negative found",
            rows,
        )
    if (pd.to_numeric(df["rack_total_count"], errors="coerce") < 0).any():
        return fail(
            check.name,
            check.path,
            "negative_rack_total_count",
            "rack_total_count negative found",
            rows,
        )

    stock_ratio = pd.to_numeric(df["stock_ratio"], errors="coerce").dropna()
    if (stock_ratio < 0).any():
        return fail(
            check.name,
            check.path,
            "negative_stock_ratio",
            "stock_ratio negative found",
            rows,
        )

    duplicate_count = int(df.duplicated(["collected_at", "station_id"]).sum())
    if duplicate_count:
        return fail(
            check.name,
            check.path,
            "duplicate_station_snapshot",
            f"duplicate station snapshot rows: count={duplicate_count}",
            rows,
        )

    stations = df["station_id"].nunique()
    snapshots = df["collected_at"].nunique()
    max_stock_ratio = stock_ratio.max() if not stock_ratio.empty else None
    ratio_text = f" max_stock_ratio={max_stock_ratio:.2f}" if max_stock_ratio is not None else ""
    return ok(
        check.name,
        check.path,
        f"batch output: rows={rows} stations={stations} snapshots={snapshots}{ratio_text} path={check.path}",
        rows,
    )


def check_weather_output(check: BatchOutputCheck) -> BatchOutputResult:
    df, error = read_output(check.name, check.path)
    if error is not None:
        return error
    assert df is not None

    common_error = check_common(check, df, WEATHER_REQUIRED_COLUMNS)
    if common_error is not None:
        return common_error

    rows = len(df)
    if df["collected_at"].isna().any():
        return fail(check.name, check.path, "null_collected_at", "collected_at null found", rows)

    invalid_sources = sorted(set(df["weather_source"].dropna().astype(str)) - WEATHER_SOURCES)
    if invalid_sources:
        return fail(
            check.name,
            check.path,
            "invalid_weather_source",
            f"invalid weather_source: values={invalid_sources}",
            rows,
        )

    if df[WEATHER_FEATURE_COLUMNS].notna().sum().sum() == 0:
        return fail(
            check.name,
            check.path,
            "empty_weather_features",
            "all weather feature values null",
            rows,
        )

    for col in ["rn1", "reh", "wsd", "pty"]:
        values = pd.to_numeric(df[col], errors="coerce").dropna()
        if (values < 0).any():
            return fail(check.name, check.path, f"negative_{col}", f"{col} negative found", rows)

    reh = pd.to_numeric(df["reh"], errors="coerce").dropna()
    if ((reh < 0) | (reh > 100)).any():
        return fail(check.name, check.path, "invalid_reh_range", "reh outside 0..100 found", rows)

    return ok(check.name, check.path, f"batch output: rows={rows} path={check.path}", rows)


def check_crowd_output(check: BatchOutputCheck) -> BatchOutputResult:
    """CROWD 서빙 표 전용 — 197: 음수 인원(`boarding_pred`/`alighting_pred`) 0건을 단정한다.

    등급 계산은 이미 클립된 값을 쓰므로 여기서 음수가 나오면 `to_congestion_table`의 클립이
    출력까지 전파되지 않은 것이다(`SERVING_CONTRACT.md` 5.1 참고). BIKE·weather 산출물은 이
    컬럼 자체가 없어 `check_bike_output`/`check_weather_output`과는 별도 함수로 둔다.
    """
    df, error = read_output(check.name, check.path)
    if error is not None:
        return error
    assert df is not None

    common_error = check_common(check, df, CROWD_REQUIRED_COLUMNS)
    if common_error is not None:
        return common_error

    rows = len(df)
    if (pd.to_numeric(df["boarding_pred"], errors="coerce") < 0).any():
        return fail(
            check.name, check.path, "negative_boarding_pred", "boarding_pred negative found", rows
        )
    if (pd.to_numeric(df["alighting_pred"], errors="coerce") < 0).any():
        return fail(
            check.name,
            check.path,
            "negative_alighting_pred",
            "alighting_pred negative found",
            rows,
        )

    clipped_rows = int(df["pred_clipped"].sum())
    return ok(
        check.name,
        check.path,
        f"batch output: rows={rows} clipped_rows={clipped_rows} path={check.path}",
        rows,
    )


def check_batch_outputs(checks: Iterable[BatchOutputCheck]) -> list[BatchOutputResult]:
    results = []
    for check in checks:
        if check.name == "bike":
            results.append(check_bike_output(check))
        elif check.name == "weather":
            results.append(check_weather_output(check))
        elif check.name == "crowd":
            results.append(check_crowd_output(check))
        else:
            raise ValueError(f"unknown batch output check: {check.name}")
    return results


def build_checks(
    ai_root: Path,
    dt: str,
    bike_min_rows: int,
    weather_min_rows: int,
    crowd_min_rows: int = DEFAULT_CROWD_MIN_ROWS,
) -> list[BatchOutputCheck]:
    return [
        BatchOutputCheck(
            name="bike",
            path=output_path(ai_root / DEFAULT_BIKE_OUTPUT, dt),
            min_rows=bike_min_rows,
        ),
        BatchOutputCheck(
            name="weather",
            path=output_path(ai_root / DEFAULT_WEATHER_OUTPUT, dt),
            min_rows=weather_min_rows,
        ),
        # 197: 음수 인원이 다시 새면 여기서 잡는다. 경로 규칙이 dt= 파티션이 아니라
        # 날짜별 단일 parquet이라 crowd_output_path를 따로 쓴다.
        BatchOutputCheck(
            name="crowd",
            path=crowd_output_path(ai_root / DEFAULT_CROWD_OUTPUT, dt),
            min_rows=crowd_min_rows,
        ),
    ]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check DATA_ENGINE batch output quality.")
    parser.add_argument("--date", default=default_date(), help="Target output date YYYY-MM-DD.")
    parser.add_argument(
        "--ai-root",
        type=Path,
        default=AI_ROOT,
        help="AI project root. Defaults to the root inferred from this file.",
    )
    parser.add_argument(
        "--bike-min-rows",
        type=int,
        default=DEFAULT_BIKE_MIN_ROWS,
        help="Minimum rows for bike batch output.",
    )
    parser.add_argument(
        "--weather-min-rows",
        type=int,
        default=DEFAULT_WEATHER_MIN_ROWS,
        help="Minimum rows for weather batch output.",
    )
    parser.add_argument(
        "--crowd-min-rows",
        type=int,
        default=DEFAULT_CROWD_MIN_ROWS,
        help="Minimum rows for CROWD serving table.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    checks = build_checks(
        args.ai_root,
        dt=args.date,
        bike_min_rows=args.bike_min_rows,
        weather_min_rows=args.weather_min_rows,
        crowd_min_rows=args.crowd_min_rows,
    )
    results = check_batch_outputs(checks)
    for result in results:
        print(result.message)

    if all(result.ok for result in results):
        print("DATA_ENGINE batch output quality OK")
        return 0

    print("DATA_ENGINE batch output quality FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
