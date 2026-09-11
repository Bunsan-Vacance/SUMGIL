"""열차별 재차인원 추정 표 — 135번 2층 산출물.

    crowd_congestion_label_calibrated_2024_2026.parquet   (날짜·역·방향·30분, 열차 평균 혼잡도 %)
    × timetable_long.parquet                              (역·방향·요일유형·열차 통과 시각)
      → app.CROWD.pipeline.disaggregate.allocate_to_trains (직전 열차 간격 비례, 12분 초과 플래그)
      → data/CROWD/processed/crowd_load_by_train_<기간>.parquet

## 30분 라벨을 열차로 나누는 방식

88의 보정 혼잡도는 정의상 **"그 30분에 지나간 열차들의 평균 혼잡도"** 다. 그러므로 그 슬롯의 총
재차인원 = 평균 혼잡도 × 정원 × 그 슬롯 열차 수이고, 이것을 열차별 간격 비례로 배분하면 균등 배차에서는
열차마다 평균값이 그대로, 간격이 벌어진 열차에는 그만큼 더 실린다. 1층(승하차 30분 분해)은 거치지
않는다 — 라벨이 이미 방향별 30분이고, 방향 평균이 4%p를 뭉갠다는 것이 홀드아웃에서 확인됐다.

## 기간을 잘라 만든다

보정 라벨 전체(1,580만 행)에 열차를 붙이면 8천만 행이 넘는다. 검증·표출 실험용으로 기본 1주
(2025-06-02~06-08, 월~일)를 만들고 `--start/--end`로 바꾼다. 서빙에서는 배치가 대상 날짜만 만든다.

## 결측·플래그

- 배율표가 없어 보정 혼잡도가 NaN인 셀은 배분하지 않는다(NaN 유지).
- 그 30분에 열차가 없는 셀은 결과에 나오지 않는다(운행 없음).
- `headway_long`(직전 열차 간격 > 12분)은 균등 도착 가정이 약한 열차 표시. 값은 그대로.
- 공휴일(패널 day_type "휴일")은 일요일 시각표를 쓴다.

실행:
    cd AI
    python -m DATA_ENGINE.eda.build_load_by_train [--start 2025-06-02 --end 2025-06-08]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from app.CROWD.pipeline.disaggregate import LONG_HEADWAY_MIN, allocate_to_trains
from DATA_ENGINE.eda.parsers_timetable import TIMETABLE_INTERIM, day_type_to_timetable

AI_ROOT = Path(__file__).resolve().parents[2]
CROWD_PROCESSED = AI_ROOT / "data" / "CROWD" / "processed"
LABEL_NAME = "crowd_congestion_label_calibrated_2024_2026.parquet"
PANEL_NAME = "crowd_panel_2024_2025.parquet"

LABEL_COLS = [
    "date",
    "station_no",
    "line",
    "direction",
    "time_slot",
    "train_capacity",
    "congestion_pct_calibrated",
]


def load_labels(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    lab = pd.read_parquet(CROWD_PROCESSED / LABEL_NAME, columns=LABEL_COLS)
    lab = lab[(lab["date"] >= start) & (lab["date"] <= end)].rename(
        columns={"time_slot": "time_slot_30min"}
    )
    lab = lab[lab["line"] != "9호선"]  # 9호선은 승하차 패널 기간이 달라 별도
    # 분기점(강동 2549)은 본선·하남선·마천지선 세 세그먼트에 다 들어 있어 같은 (날짜·역·방향·30분)이
    # 3행이다. 지선 세그먼트에서는 강동이 종점이라 재차 0으로 계산되므로, 실제 승강장 상황을 담은
    # 값은 본선 쪽 최댓값이다 → 키당 max로 접는다(sum은 3배 과대, mean은 과소).
    key = ["date", "station_no", "direction", "time_slot_30min"]
    lab = (
        lab.sort_values("congestion_pct_calibrated", ascending=False)
        .drop_duplicates(key)
        .reset_index(drop=True)
    )
    day_type = pd.read_parquet(
        CROWD_PROCESSED / PANEL_NAME, columns=["date", "day_type"]
    ).drop_duplicates("date")
    lab = lab.merge(day_type, on="date", how="left")
    lab["day_type_tt"] = lab["day_type"].map(day_type_to_timetable)
    return lab


def build(
    start: pd.Timestamp, end: pd.Timestamp, mix_h0: float | None = None, mix_h1: float = 15.0
) -> tuple[pd.DataFrame, dict]:
    labels = load_labels(start, end)
    # pass_time(도착, 없으면 출발)을 그 역을 지나는 시각으로 쓴다. 원본 arrival/departure 컬럼은 버린다.
    tt = (
        pd.read_parquet(TIMETABLE_INTERIM)
        .drop(columns=["arrival_time", "departure_time"], errors="ignore")
        .rename(columns={"day_type": "day_type_tt", "pass_time": "arrival_time"})
    )

    # 슬롯별 열차 수 → 슬롯 총 재차인원 = 평균 혼잡도 × 정원 × 열차 수
    tt["arr_min"] = tt["arrival_time"].str.slice(0, 2).astype(int) * 60 + tt[
        "arrival_time"
    ].str.slice(3, 5).astype(int)
    tt["arr_min"] = tt["arr_min"].where(tt["arr_min"] >= 4 * 60, tt["arr_min"] + 24 * 60)
    tt["time_slot_30min"] = ((tt["arr_min"] // 30) * 30 % (24 * 60)).map(
        lambda m: f"{m // 60:02d}:{m % 60:02d}"
    )
    key = ["station_no", "direction", "day_type_tt", "time_slot_30min"]
    n_trains = tt.groupby(key, observed=True)["train_id"].nunique().rename("n_trains").reset_index()

    lab = labels.merge(n_trains, on=key, how="left")
    lab["onboard_30min_est"] = (
        lab["congestion_pct_calibrated"] / 100.0 * lab["train_capacity"] * lab["n_trains"]
    )

    slot_loads = (
        lab.dropna(subset=["onboard_30min_est"])
        .drop(columns=["day_type"])  # 패널 day_type(휴일 포함) 대신 시각표 요일유형을 키로 쓴다
        .rename(columns={"day_type_tt": "day_type"})
    )[
        [
            "date",
            "station_no",
            "line",
            "direction",
            "day_type",
            "time_slot_30min",
            "train_capacity",
            "onboard_30min_est",
        ]
    ]
    tt_alloc = tt.rename(columns={"day_type_tt": "day_type"})[
        ["station_no", "direction", "day_type", "train_id", "arrival_time", "express"]
    ]
    out = allocate_to_trains(
        slot_loads,
        tt_alloc,
        load_col="onboard_30min_est",
        long_headway_min=LONG_HEADWAY_MIN,
        mix_h0=mix_h0,
        mix_h1=mix_h1,
    )
    # allocate_to_trains는 배분에 필요한 컬럼만 돌려준다 — 급행 여부는 열차 키로 다시 붙인다.
    out = out.merge(
        tt_alloc[["station_no", "direction", "day_type", "train_id", "express"]].drop_duplicates(),
        on=["station_no", "direction", "day_type", "train_id"],
        how="left",
    )
    out["congestion_pct_est"] = out["load_est"] / out["train_capacity"] * 100
    out = out.rename(columns={"load_est": "onboard_est"})
    out = out[
        [
            "date",
            "station_no",
            "line",
            "direction",
            "day_type",
            "time_slot_30min",
            "train_id",
            "arrival_time",
            "express",
            "headway_min",
            "headway_long",
            "share",
            "onboard_est",
            "congestion_pct_est",
            "train_capacity",
        ]
    ].sort_values(["date", "line", "station_no", "direction", "arrival_time"])

    stats = {
        "label_cells": len(labels),
        "label_cells_with_value": int(labels["congestion_pct_calibrated"].notna().sum()),
        "cells_without_trains": int(
            (lab["n_trains"].isna() & lab["congestion_pct_calibrated"].notna()).sum()
        ),
        "train_rows": len(out),
        "long_headway_ratio": round(float(out["headway_long"].mean()), 4) if len(out) else None,
        "rush_long_headway_ratio": (
            round(
                float(
                    out[
                        out["time_slot_30min"].isin(
                            ["07:30", "08:00", "08:30", "18:00", "18:30", "19:00"]
                        )
                    ]["headway_long"].mean()
                ),
                4,
            )
            if len(out)
            else None
        ),
        "mass_gap": (
            float(
                (
                    out.groupby(
                        ["date", "station_no", "direction", "time_slot_30min"], observed=True
                    )["onboard_est"].sum()
                    - slot_loads.set_index(["date", "station_no", "direction", "time_slot_30min"])[
                        "onboard_30min_est"
                    ]
                )
                .abs()
                .max()
            )
            if len(out)
            else None
        ),
    }
    return out.reset_index(drop=True), stats


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--start", default="2025-06-02")
    ap.add_argument("--end", default="2025-06-08")
    ap.add_argument(
        "--mix-h0",
        type=float,
        default=None,
        help="배차 의존 도착 혼합(92): 이 분까지 무작위 도착 가중 1. 생략하면 간격 비례(135 기본)",
    )
    ap.add_argument("--mix-h1", type=float, default=15.0, help="이 분부터 무작위 도착 가중 0")
    args = ap.parse_args(argv)
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    out, stats = build(start, end, mix_h0=args.mix_h0, mix_h1=args.mix_h1)
    suffix = f"_mix{args.mix_h0:g}-{args.mix_h1:g}" if args.mix_h0 is not None else ""
    path = CROWD_PROCESSED / f"crowd_load_by_train_{start:%Y%m%d}_{end:%Y%m%d}{suffix}.parquet"
    out.to_parquet(path, index=False)
    for k, v in stats.items():
        print(f"{k}: {v}")
    print(f"저장: {path} ({len(out):,}행)")


if __name__ == "__main__":
    main(sys.argv[1:])
