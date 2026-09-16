"""146 3단계 — 1호선 절단 구간을 어떻게 다룰 것인가. 세 안을 2025 실측으로 비교한다.

## 문제

`line_topology.yaml`의 1호선은 서울교통공사 구간(서울역 150 ~ 청량리 158)뿐이고 양 끝이 코레일로
이어지는 **절단면**이다. 재귀식은 "구간 안에서 타고 구간 안에서 내린다"는 닫힌 OD를 가정하므로,
오름차순 마지막 역(청량리)의 하선과 내림차순 첫 역(서울역)의 상선은 정의상 재차 0이 된다. 실제로는
그 열차가 코레일 구간으로 계속 달리고 실측 스냅샷도 평일 평균 24.4%·32.5%를 보고한다. 재차 0이면
배율(실측 ÷ raw 평균)도 산출이 안 돼(ratio NaN) 그 셀은 값이 아예 없다 — 1호선 20개 방향·역 중 2개,
하루 78셀.

## 비교하는 세 안 (계획에 사전 고정)

- **(0) 현행** — 재귀식 raw × 배율표. 경계 2셀은 NaN.
- **(a) 경계 유입 상수** — 경계역 유입 재차 = 실측 혼잡도 × 정원 − 그 역까지의 재귀식 재차. 요일유형×
  방향×30분별 상수를 재귀식 재차에 더한 뒤 **기존 배율표**를 곱한다.
- **(b) 1호선 lookup 혼잡도** — 1호선은 예측을 쓰지 않고 실측 스냅샷 평균을 그대로 낸다.

## 정답과 조인

정답은 `data/CROWD/interim/crowd_congestion_long.parquet`(88 실측 스냅샷, `source=seoul_1_8`).
조인 키는 `station_no · direction · day_type · time_slot(30분)`이다. 계획은 여기에 `year=2025`
필터를 적었지만 **1~8호선 스냅샷에는 연도 축이 없다**(대표 1주 단일 조사라 `year`가 전부 결측) —
연도 필터는 9호선에만 해당해 여기서는 적용하지 않았다. 2025는 **입력 승하차 쪽**의 범위다.

## 이 비교는 한쪽이 순환 참조라는 점을 밝혀 둔다

배율표(88)는 바로 이 스냅샷을 분자로 맞춘 값이다. 그래서 배율이 있는 셀에서는 (0)의 날짜 평균이
정답과 거의 같아지는 것이 **정상**이고(항등식 확인용 수치다), (b)는 정답을 그대로 서빙하는 자기
비교라 MAE가 0이 된다. MAE 기준만으로는 셋을 가를 수 없어, 순환이 없는 두 번째 축을 따로 낸다:
방향×요일유형×30분마다 **스케일 1개만** 쓰는 적합에서 상수항(경계 유입)을 넣으면 공간 프로파일이
얼마나 좋아지는가 — 여기서 절단이 실제로 문제인지가 드러난다.

실행(약 1분):
    cd AI
    python validation/CROWD/congestion-criteria-check/line1_boundary.py --out line1_draft.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[2]
for p in (str(AI_ROOT), str(AI_ROOT / "validation" / "CROWD" / "baseline-check")):
    if p not in sys.path:
        sys.path.insert(0, p)

from evaluate_final import to_markdown

from app.CROWD.pipeline.batch_predict import CALIBRATION_NAME
from app.CROWD.pipeline.congestion import (
    apply_calibration,
    hour_bucket_to_30min_slots,
    recursive_congestion,
    truncated_boundary_cells,
)
from app.CROWD.pipeline.dataset import (
    CROWD_INTERIM,
    CROWD_PROCESSED,
    load_panel,
    resolved_segments,
)
from app.CROWD.pipeline.topology import load_capacity

LINE = "1호선"
YEAR = 2025
SNAPSHOT_NAME = "crowd_congestion_long.parquet"
# 스냅샷에 있는 요일유형(공휴일은 없다 — 146 2단계의 일요일 대체가 따로 담당한다).
SNAPSHOT_DAY_TYPES = ("평일", "토요일", "일요일")
KEY = ["station_no", "direction", "day_type", "time_slot_30min"]


def measured(path: Path = CROWD_INTERIM / SNAPSHOT_NAME) -> pd.DataFrame:
    snap = pd.read_parquet(path)
    snap = snap[(snap["source"] == "seoul_1_8") & (snap["line"] == LINE)].copy()
    snap["station_no"] = snap["station_no"].astype("int64")
    return snap.rename(columns={"time_slot": "time_slot_30min", "congestion_pct": "meas"})[
        [*KEY, "meas"]
    ]


def recursive_2025(panel: pd.DataFrame, segments: list[dict], capacity: dict) -> pd.DataFrame:
    """2025 실측 승하차 → 1호선 재귀식(1시간). 예측을 섞지 않는다 — 모델 오차를 비교에 넣지 않으려는 것."""
    sub = panel[(panel["line"] == LINE) & (panel["date"].dt.year == YEAR)]
    segs = [s for s in segments if s["line"] == LINE]
    raw = recursive_congestion(sub, segs, capacity)
    day_type = sub[["date", "station_no", "day_type"]].drop_duplicates(["date", "station_no"])
    return raw.merge(day_type, on=["date", "station_no"], how="left")


def boundary_inflow_table(raw: pd.DataFrame, meas: pd.DataFrame, capacity: dict) -> pd.DataFrame:
    """(보정 5) 경계역 유입 재차 = 실측 혼잡도 × 정원 − 그 역까지의 재귀식 재차.

    요일유형 × 방향 × 30분 상수 표. 경계 셀의 재귀식 재차는 정의상 0이라 사실상 "실측 혼잡도 ×
    정원"이 그대로 상수가 된다 — 절단으로 놓친 통과 승객의 크기다.
    """
    train_capacity = capacity["cars_per_train"][LINE] * capacity["car_capacity"]
    cells = truncated_boundary_cells([{"line": LINE, "truncated": True, "stations": STATIONS}])
    onboard = (
        raw.groupby(["station_no", "direction", "day_type", "time_slot"])["onboard"]
        .mean()
        .reset_index()
    )
    onboard["time_slot_30min"] = onboard["time_slot"].map(hour_bucket_to_30min_slots)
    onboard = onboard.explode("time_slot_30min")
    edge = onboard[
        pd.MultiIndex.from_arrays([onboard["station_no"], onboard["direction"]]).isin(list(cells))
    ]
    out = edge.merge(meas, on=KEY, how="inner")
    out["boundary_onboard"] = np.clip(out["meas"] / 100 * train_capacity - out["onboard"], 0, None)
    return out[["direction", "day_type", "time_slot_30min", "boundary_onboard", "meas"]]


STATIONS: list[int] = []  # main()에서 토폴로지로 채운다


def option_frames(
    raw: pd.DataFrame, calibration: pd.DataFrame, inflow: pd.DataFrame, capacity: dict
) -> dict[str, pd.DataFrame]:
    """세 안의 (역·방향·요일유형·30분) 평균 혼잡도."""
    train_capacity = capacity["cars_per_train"][LINE] * capacity["car_capacity"]
    base = apply_calibration(raw, calibration, holiday_fallback=None)
    cur = base.groupby(KEY)["congestion_pct_calibrated"].mean().rename("pred").reset_index()

    # (a) 재귀식 재차에 경계 상수를 더한 뒤 **기존 배율표**를 곱한다.
    adj = base.merge(
        inflow[["direction", "day_type", "time_slot_30min", "boundary_onboard"]],
        on=["direction", "day_type", "time_slot_30min"],
        how="left",
    )
    adj["boundary_onboard"] = adj["boundary_onboard"].fillna(0.0)
    adj["pred"] = ((adj["onboard"] + adj["boundary_onboard"]) / train_capacity * 100) * adj["ratio"]
    opt_a = adj.groupby(KEY)["pred"].mean().reset_index()
    return {"(0) 현행": cur, "(a) 경계 유입 상수": opt_a}


def score(frame: pd.DataFrame, meas: pd.DataFrame, name: str) -> list[dict]:
    m = meas.merge(frame, on=KEY, how="left")
    rows = []
    for (direction, day_type), d in m.groupby(["direction", "day_type"]):
        ok = d.dropna(subset=["pred"])
        rows.append(
            {
                "안": name,
                "방향": direction,
                "요일유형": day_type,
                "셀": len(d),
                "값이_나온_셀_%": round(len(ok) / len(d) * 100, 1),
                "MAE_%p": (
                    round(float((ok["pred"] - ok["meas"]).abs().mean()), 3) if len(ok) else None
                ),
                "상관": round(float(ok["pred"].corr(ok["meas"])), 4) if len(ok) > 2 else None,
            }
        )
    return rows


def structural_fit(raw: pd.DataFrame, meas: pd.DataFrame) -> pd.DataFrame:
    """순환 없는 축 — 방향×요일유형×30분마다 스케일 1개만 두고, 상수항(경계 유입)의 효과를 본다.

    셀별 배율(역·방향·요일유형·30분)은 정답을 셀마다 맞춘 값이라 절단 오차를 통째로 흡수한다. 여기서는
    **역 축을 자유도로 남겨** 공간 프로파일이 실측과 맞는지만 본다: 10개 역에 대해
    `meas ≈ s·raw`(스케일만)와 `meas ≈ s·raw + c`(경계 상수 추가)를 각각 최소자승으로 적합한다.
    """
    g = (
        raw.groupby(["station_no", "direction", "day_type", "time_slot"])["congestion_raw_pct"]
        .mean()
        .reset_index()
    )
    g["time_slot_30min"] = g["time_slot"].map(hour_bucket_to_30min_slots)
    g = g.explode("time_slot_30min")
    m = g.merge(meas, on=KEY, how="inner")
    rows = []
    for (direction, day_type, _slot), d in m.groupby(["direction", "day_type", "time_slot_30min"]):
        x = d["congestion_raw_pct"].to_numpy(dtype=float)
        y = d["meas"].to_numpy(dtype=float)
        if (x * x).sum() <= 0 or len(x) < 3:
            continue
        s0 = (x * y).sum() / (x * x).sum()
        design = np.c_[x, np.ones_like(x)]
        coef, *_ = np.linalg.lstsq(design, y, rcond=None)
        rows.append(
            {
                "방향": direction,
                "요일유형": day_type,
                "MAE_스케일만_%p": float(np.abs(s0 * x - y).mean()),
                "MAE_스케일＋상수_%p": float(np.abs(design @ coef - y).mean()),
                "상수_%p": float(coef[1]),
            }
        )
    out = pd.DataFrame(rows).groupby(["방향", "요일유형"]).mean(numeric_only=True).reset_index()
    out["개선율_%"] = (1 - out["MAE_스케일＋상수_%p"] / out["MAE_스케일만_%p"]) * 100
    return out.round(2)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", default=str(_HERE / "line1_draft.md"))
    args = ap.parse_args(argv)
    chunks: list[str] = []

    def emit(title: str, frame: pd.DataFrame) -> None:
        print(f"\n### {title}", flush=True)
        print(frame.to_string(index=False), flush=True)
        chunks.append(f"### {title}\n\n{to_markdown(frame)}\n")

    panel = load_panel(with_events=True)
    segments, _ = resolved_segments(panel)
    capacity = load_capacity()
    calibration = pd.read_parquet(CROWD_PROCESSED / CALIBRATION_NAME)
    STATIONS[:] = next(s["stations"] for s in segments if s["line"] == LINE)
    meas = measured()
    meas = meas[meas["day_type"].isin(SNAPSHOT_DAY_TYPES)]
    raw = recursive_2025(panel, segments, capacity)
    raw = raw[raw["day_type"].isin(SNAPSHOT_DAY_TYPES)]
    print(
        f"[입력] 1호선 {len(STATIONS)}역 · 재귀식 {len(raw):,}행 · 실측 {len(meas):,}셀", flush=True
    )

    inflow = boundary_inflow_table(raw, meas, capacity)
    emit(
        "3-A. 경계 유입 상수(요일유형×방향 평균) — 절단으로 놓친 통과 재차",
        inflow.groupby(["direction", "day_type"])[["boundary_onboard", "meas"]]
        .mean()
        .round(1)
        .reset_index()
        .rename(columns={"boundary_onboard": "평균_유입_재차_명", "meas": "경계셀_실측_혼잡도_%"}),
    )

    frames = option_frames(raw, calibration, inflow, capacity)
    # (b)는 정답 자체를 서빙한다 — 별도 계산 없이 정답을 그대로 예측으로 둔다.
    frames["(b) 1호선 lookup(실측 평균)"] = meas.rename(columns={"meas": "pred"})
    rows = [r for name, f in frames.items() for r in score(f, meas, name)]
    emit("3-B. 세 안의 방향·요일유형별 MAE·상관 (정답 = 88 실측 스냅샷)", pd.DataFrame(rows))

    overall = (
        pd.DataFrame(rows)
        .groupby("안")
        .agg(
            셀=("셀", "sum"),
            값이_나온_셀_평균_=("값이_나온_셀_%", "mean"),
            MAE_평균_p=("MAE_%p", "mean"),
            상관_평균=("상관", "mean"),
        )
        .round(3)
        .reset_index()
    )
    emit("3-C. 세 안 요약", overall)
    emit("3-D. 순환 없는 축 — 스케일만 vs 스케일＋경계 상수", structural_fit(raw, meas))

    out = Path(args.out)
    out.write_text("\n".join(chunks), encoding="utf-8")
    store = CROWD_INTERIM / "validation"
    store.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(store / "congestion_criteria_line1.parquet", index=False)
    print(f"\n[저장] {out}")


if __name__ == "__main__":
    main(sys.argv[1:])
