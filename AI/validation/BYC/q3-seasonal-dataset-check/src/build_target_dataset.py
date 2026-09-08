"""Q3 시즌 master 데이터에서 OD 기반 target_net_flow train/valid/test를 생성한다.

target_net_flow(t, h) = sum(return_count_5m, t+5 ~ t+h) - sum(rent_count_5m, t+5 ~ t+h)

재고 관측치(stock_observed_hour/stock_reconstructed_raw) 기반 target_delta는 쓰지 않는다.
재고 입력은 known_stock_at_request(가장 최근 시간별 재고 anchor)로 대체하고,
minutes_since_stock_anchor로 그 값이 얼마나 오래된 정보인지 같이 남긴다.

실행 예:
    python build_target_dataset.py --data-dir ../../../data/processed/BYC/stock_q3_seasonal
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

HORIZONS = [5, 10, 15, 30]
STEP_MIN = 5

MASTER_USECOLS = [
    "station_id",
    "station_no",
    "datetime_5m",
    "stock_observed_hour",
    "capacity_proxy",
    "rent_count_5m",
    "return_count_5m",
]

# split(연도, 시작일, 끝일 exclusive)
SPLIT_DEFS = [
    ("train", 2024, "2024-07-01", "2024-09-16"),
    ("valid", 2024, "2024-09-16", "2024-10-01"),
    ("test", 2025, "2025-07-01", "2025-10-01"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="master 데이터에서 target_net_flow 기반 train/valid/test를 생성한다."
    )
    script_dir = Path(__file__).resolve()
    ai_dir = script_dir.parents[4]
    default_data_dir = ai_dir / "data" / "processed" / "BYC" / "stock_q3_seasonal"
    default_output_dir = ai_dir / "data" / "processed" / "BYC" / "stock_q3_seasonal_net_flow"
    parser.add_argument("--data-dir", default=str(default_data_dir))
    parser.add_argument("--output-dir", default=str(default_output_dir))
    return parser.parse_args()


def load_master(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=MASTER_USECOLS)
    df["datetime_5m"] = pd.to_datetime(df["datetime_5m"])
    df["station_id"] = df["station_id"].astype(str)
    return df


def rolling_forward_sum_safe(values: np.ndarray, steps: int) -> np.ndarray:
    """values[i+1 .. i+steps] 합을 반환한다.

    윈도우 안에 NaN(그리드 gap)이 하나라도 있으면 그 row는 NaN으로 남긴다 —
    표본이 불완전한 구간에 값을 채우지 않는다는 원칙을 그대로 적용한다.
    끝부분(i+steps가 시계열 범위를 벗어나는 row)도 NaN이다.
    """
    n = len(values)
    is_nan = np.isnan(values)
    filled = np.nan_to_num(values, nan=0.0)
    prefix = np.concatenate([[0.0], np.cumsum(filled)])
    nan_prefix = np.concatenate([[0], np.cumsum(is_nan.astype(int))])

    result = np.full(n, np.nan)
    valid_end = n - steps
    if valid_end > 0:
        idx = np.arange(valid_end)
        window_sum = prefix[idx + steps + 1] - prefix[idx + 1]
        window_nan_count = nan_prefix[idx + steps + 1] - nan_prefix[idx + 1]
        window_sum = np.where(window_nan_count > 0, np.nan, window_sum)
        result[idx] = window_sum
    return result


def process_station(station_id: str, group: pd.DataFrame, full_index: pd.DatetimeIndex) -> pd.DataFrame:
    """단일 station의 5분 시계열을 정규 그리드에 맞추고, horizon별 target을 계산한다."""
    g = group.drop_duplicates(subset="datetime_5m").set_index("datetime_5m").reindex(full_index)
    g.index.name = "base_time"
    g = g.reset_index()

    station_no = group["station_no"].dropna().mode()
    station_no = station_no.iloc[0] if not station_no.empty else np.nan
    capacity_proxy = group["capacity_proxy"].dropna().mode()
    capacity_proxy = capacity_proxy.iloc[0] if not capacity_proxy.empty else np.nan

    # 알려진 재고(known_stock_at_request): 가장 최근 시간별 anchor를 forward-fill
    known_stock = g["stock_observed_hour"].ffill()
    anchor_time = g["base_time"].where(g["stock_observed_hour"].notna()).ffill()
    minutes_since_anchor = (g["base_time"] - anchor_time).dt.total_seconds() / 60

    rent = g["rent_count_5m"].to_numpy(dtype=float)
    ret = g["return_count_5m"].to_numpy(dtype=float)

    frames = []
    for horizon in HORIZONS:
        steps = horizon // STEP_MIN
        target_rent = rolling_forward_sum_safe(rent, steps)
        target_return = rolling_forward_sum_safe(ret, steps)
        frames.append(
            pd.DataFrame(
                {
                    "station_id": station_id,
                    "station_no": station_no,
                    "base_time": g["base_time"],
                    "horizon_min": horizon,
                    "known_stock_at_request": known_stock,
                    "known_stock_source": "hourly_anchor",
                    "minutes_since_stock_anchor": minutes_since_anchor,
                    "capacity_proxy": capacity_proxy,
                    "target_rent_count": target_rent,
                    "target_return_count": target_return,
                    "target_net_flow": target_return - target_rent,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def build_year(master_path: Path, year: int) -> pd.DataFrame:
    print(f"[{year}] master 로드: {master_path.name}")
    df = load_master(master_path)
    full_index = pd.date_range(f"{year}-07-01", f"{year}-10-01", freq="5min", inclusive="left")

    station_frames = []
    station_ids = sorted(df["station_id"].unique())
    print(f"[{year}] station 수: {len(station_ids)}, 대상 grid rows/station: {len(full_index)}")
    for i, station_id in enumerate(station_ids, start=1):
        group = df[df["station_id"] == station_id]
        station_frames.append(process_station(station_id, group, full_index))
        if i % 50 == 0 or i == len(station_ids):
            print(f"[{year}] station 처리 {i}/{len(station_ids)}")

    result = pd.concat(station_frames, ignore_index=True)

    result["hour"] = result["base_time"].dt.hour
    result["minute"] = result["base_time"].dt.minute
    result["day_of_week"] = result["base_time"].dt.dayofweek
    result["is_weekend"] = result["day_of_week"].isin([5, 6]).astype(int)
    result["month"] = result["base_time"].dt.month
    result["known_stock_ratio"] = result["known_stock_at_request"] / result["capacity_proxy"]

    return result


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    year_frames = {}
    for year in (2024, 2025):
        master_path = data_dir / f"master_{year}_q3_top300.csv.gz"
        year_frames[year] = build_year(master_path, year)

    build_summary = {}
    for split_name, year, start, end in SPLIT_DEFS:
        full = year_frames[year]
        mask = (full["base_time"] >= start) & (full["base_time"] < end)
        split_df = full.loc[mask].copy()

        total_rows = len(split_df)
        target_missing = int(split_df["target_net_flow"].isna().sum())
        stock_missing = int(split_df["known_stock_at_request"].isna().sum())

        clean_df = split_df.dropna(subset=["target_net_flow", "known_stock_at_request"])

        out_path = output_dir / f"{split_name}_q3_target_net_flow.csv.gz"
        clean_df.to_csv(out_path, index=False, compression="gzip")

        build_summary[split_name] = {
            "rows_before_drop": total_rows,
            "rows_after_drop": len(clean_df),
            "dropped_target_missing": target_missing,
            "dropped_stock_missing": stock_missing,
            "output_file": out_path.name,
        }
        print(
            f"[{split_name}] {total_rows:,} -> {len(clean_df):,} rows "
            f"(target 결측 {target_missing:,}, stock anchor 결측 {stock_missing:,})"
        )

    (output_dir / "build_summary.json").write_text(
        json.dumps(build_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"완료. 산출물: {output_dir}")


if __name__ == "__main__":
    main()
