"""BE `bike_stock_pred` 스키마용 재고·확률 프로파일 — source=avg.

target_net_flow 모델 없이, 실측 `stock_anchor_hour`/`is_empty_anchor`/`is_full_anchor`를
(station, dow_type, time_slot)별로 평균·빈도내서 직접 계산한다(CROWD의 lookup baseline과
같은 "모델 없이 정직한 baseline 먼저" 철학).

    exp_bikes  = 그 그룹의 stock_anchor_hour 평균
    p_empty    = 그 그룹에서 재고==0(is_empty_anchor)인 비율
    p_full     = 그 그룹에서 재고>=rack_count(is_full_anchor)인 비율

dow_type = 0 평일 / 1 토 / 2 일요일. **공휴일은 아직 못 넣는다** —
`data/EXTERNAL/holiday/interim/holiday_calendar.parquet`가 이 로컬 환경에 없음(빈
폴더, 확인됨). CROWD의 `calendar.load_holidays()`도 파일 없으면 "전부 비공휴일"로
처리하므로 지금 이 스크립트도 같은 상태다 — 나중에 holiday calendar가 들어오면
day_of_week만으로 만든 dow_type을 공휴일까지 반영하도록 다시 계산해야 한다.

time_slot = slot_5m // 6 (5분 슬롯 6개 = 30분).

train(2024-01~11) 데이터만 사용한다(avg_baseline_full.py와 같은 관례).

실행 예 (소규모 검증):
    python stock_probability.py --max-stations 5

전체 실행:
    python stock_probability.py
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "outputs" / "full-run"
OUT_DIR = Path(__file__).resolve().parents[1] / "outputs" / "stock-probability"
NEEDED_COLS = [
    "od_station_id",
    "day_of_week",
    "slot_5m",
    "stock_anchor_hour",
    "is_empty_anchor",
    "is_full_anchor",
    "rack_count",
]
GROUP_KEYS = ["od_station_id", "dow_type", "time_slot"]


def _train_paths() -> list[Path]:
    paths = sorted(DATA_DIR.glob("train_netflow_q3_mapped_full_*.parquet"))
    if not paths:
        raise FileNotFoundError(f"{DATA_DIR}에 train_netflow_q3_mapped_full_*.parquet 없음")
    return paths


def day_of_week_to_dow_type(day_of_week: pd.Series) -> pd.Series:
    """0 평일(월~금) / 1 토 / 2 일. 공휴일 미반영(위 docstring 참고)."""
    return day_of_week.map({5: 1, 6: 2}).fillna(0).astype("int8")


def build_avg_profile(paths: list[Path], max_stations: int | None = None) -> pd.DataFrame:
    """월별 parquet을 순회하며 그룹별 부분합(sum·count)을 누적한다(avg_baseline_full.py와 동일 원리).

    stock_anchor_hour는 5분 슬롯마다 같은 값이 반복되므로(1시간 단위 재고를 그대로 anchor로
    쓰기 때문) 5분 단위 그대로 평균 내도 시간당 평균과 같다 — horizon 중복 문제(같은 base_time이
    horizon 4종만큼 반복되는 것)는 애초에 이 컬럼들이 horizon과 무관해서 안 생긴다.
    다만 원본 parquet은 horizon_min 4종만큼 행이 중복돼 있으므로, horizon_min == 5인 행만
    걸러서 중복을 없앤다(같은 base_time·station당 정확히 1행이 되게).
    """
    station_filter: set[str] | None = None
    total = None
    for p in paths:
        df = pd.read_parquet(p, columns=[*NEEDED_COLS, "horizon_min"])
        df = df[df["horizon_min"] == 5]  # base_time당 1행만(horizon 중복 제거)
        if max_stations is not None:
            if station_filter is None:
                station_filter = set(df["od_station_id"].drop_duplicates().head(max_stations))
            df = df[df["od_station_id"].isin(station_filter)]
        df = df.dropna(subset=["stock_anchor_hour"])
        df["dow_type"] = day_of_week_to_dow_type(df["day_of_week"])
        df["time_slot"] = (df["slot_5m"] // 6).astype("int16")

        g = df.groupby(GROUP_KEYS).agg(
            exp_bikes_sum=("stock_anchor_hour", "sum"),
            n=("stock_anchor_hour", "count"),
            empty_sum=("is_empty_anchor", "sum"),
            full_sum=("is_full_anchor", "sum"),
            rack_count=("rack_count", "first"),
        )
        total = g if total is None else total.add(g, fill_value=0)
        del df

    total["exp_bikes"] = total["exp_bikes_sum"] / total["n"]
    total["p_empty"] = total["empty_sum"] / total["n"]
    total["p_full"] = total["full_sum"] / total["n"]
    out = total.reset_index()[["od_station_id", "dow_type", "time_slot", "exp_bikes", "p_empty", "p_full", "n"]]
    return out.rename(columns={"od_station_id": "rental_id"})


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--max-stations", type=int, default=None, help="소규모 검증용 station 수 제한")
    p.add_argument("--out-dir", default=str(OUT_DIR))
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    paths = _train_paths()
    t0 = time.time()
    profile = build_avg_profile(paths, args.max_stations)
    print(f"완료: {len(profile):,}행, {profile['rental_id'].nunique()}station ({time.time() - t0:.1f}초)")
    print(profile.describe().to_string())

    tag = f"sample{args.max_stations}" if args.max_stations else "full"
    out_path = out_dir / f"stock_pred_avg_{tag}.parquet"
    profile.drop(columns=["n"]).to_parquet(out_path, index=False)
    print(f"저장: {out_path}")


if __name__ == "__main__":
    main()
