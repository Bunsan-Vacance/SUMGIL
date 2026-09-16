"""92번 — 시뮬레이션 정답 위에서 열차·5분 단위 예측기 비교와 생성기 가정 민감도.

질문: 30분 라벨을 열차·5분 단위로 내려 보여주는 것이 30분 그대로보다 사용자에게 더 맞는 정보를 주는가?
정답은 `app.CROWD.pipeline.simulate`가 만든 "그날의 실제"(모양 편차·Poisson·운행 편차 포함)이고, 예측기는
전부 **계획 시각표와 30분 라벨만** 안다.

예측기
- `slot_flat` — 슬롯 안 모든 열차에 슬롯 평균(= 30분 라벨 그대로). 열차별 표출을 하지 않는 것과 같다.
- `prop`      — 135의 직전 간격 비례 배분.
- `mix`       — 92의 배차 의존 도착 혼합 배분(예측기 h0/h1은 생성기와 별개로 고정: 5/15).
- `oracle_tt` — 실제(편차 반영) 시각표를 안다고 가정한 혼합 배분. 모양 편차·Poisson은 모른다.
                계획 시각표만 아는 `mix`와의 차이 = **실시간 배차 정보의 가치**(팀 논의 E-5).

지표(열차 단위·5분 빈 단위)
- MAE(%p), RMSE(%p): 혼잡도 오차.
- 등급 일치율(50/100): 예측 등급 = 실제 등급 비율.
- 정보량: 실제 등급이 "슬롯 평균 등급"과 다른 열차의 비율(= 열차별 표출이 새 정보를 줄 수 있는 셀의 크기)과,
  그 열차들 중 예측기가 맞춘 비율.
- skip 시나리오에서 결행 열차는 정답에 없다 → 예측기가 낸 유령 열차 비율(`phantom_ratio`)을 따로 센다.

판정 기준(계획 파일에 미리 고정): 열차 단위 등급 일치율이 `slot_flat` 대비 **+3%p 이상**이고 운행 편차
시나리오에서도 `slot_flat`보다 나쁘지 않을 때만 "열차별 표출" 채택.

실행:
    cd AI
    python validation/CROWD/sim-eval/evaluate.py                 # 기본 가정 3 시나리오 × seed 0,1 + 민감도 격자
    python validation/CROWD/sim-eval/evaluate.py --quick         # 격자 없이 기본만
    python validation/CROWD/sim-eval/evaluate.py --out validation/CROWD/sim-eval/RESULTS_raw.md
결과: 표준 출력 + `--out` 마크다운 + `data/CROWD/interim/validation/sim_eval_{base,grid}.parquet`(그림·노트북 입력).
"""

from __future__ import annotations

import argparse
import itertools
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[2]
for p in (str(AI_ROOT), str(AI_ROOT / "validation" / "CROWD" / "baseline-check")):
    if p not in sys.path:
        sys.path.insert(0, p)

from evaluate_final import to_markdown

from app.CROWD.pipeline.congestion import grade
from app.CROWD.pipeline.disaggregate import allocate_to_trains
from app.CROWD.pipeline.simulate import SimConfig, bin5_of, simulate
from DATA_ENGINE.eda.build_load_by_train import prepare_inputs

OUT_DIR = AI_ROOT / "data" / "CROWD" / "interim" / "validation"
THRESHOLDS = [50.0, 100.0]
PRED_H0, PRED_H1 = 5.0, 15.0  # 예측기가 쓰는 도착 혼합(생성기 가정과 독립)
# 2호선 순환 열차는 같은 역을 하루 두 번 지나 train_id만으로는 유일하지 않다 → 계획 도착 시각을 키에 넣는다
TRAIN_JOIN = ["date", "station_no", "direction", "day_type", "train_id", "arrival_time"]

GRID_SIGMA = (0.03, 0.05, 0.08)
GRID_MIX = ((5.0, 10.0), (5.0, 15.0), (10.0, 20.0))
GRID_SCENARIO = ("none", "delay", "skip")


# ── 예측기 ──
def predict_all(slot_loads: pd.DataFrame, timetable: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """계획 시각표만 아는 예측기 3종 → {이름: [TRAIN_JOIN..., time_slot_30min, arr_min_plan, pred_pct]}."""
    prop = allocate_to_trains(slot_loads, timetable)
    mix = allocate_to_trains(slot_loads, timetable, mix_h0=PRED_H0, mix_h1=PRED_H1)
    n_slot = prop.groupby(["date", "station_no", "direction", "day_type", "time_slot_30min"])[
        "train_id"
    ].transform("count")
    flat = prop.assign(load_est=prop["onboard_30min_est"] / n_slot)

    out = {}
    for name, df in (("slot_flat", flat), ("prop", prop), ("mix", mix)):
        d = df[[*TRAIN_JOIN, "time_slot_30min", "load_est", "train_capacity"]].copy()
        d["pred_pct"] = d["load_est"] / d["train_capacity"] * 100.0
        d["arr_min_plan"] = _minutes(d["arrival_time"])
        out[name] = d.drop(columns=["load_est"])
    return out


def _minutes(t: pd.Series) -> pd.Series:
    parts = t.astype(str).str.split(":", expand=True)
    m = parts[0].astype(int) * 60 + parts[1].astype(int)
    return m.where(m >= 4 * 60, m + 24 * 60).astype(float)


# ── 지표 ──
def _metrics(true_pct: pd.Series, pred_pct: pd.Series, slot_pct: pd.Series) -> dict:
    err = pred_pct - true_pct
    g_true, g_pred, g_slot = (grade(s, THRESHOLDS) for s in (true_pct, pred_pct, slot_pct))
    informative = g_true != g_slot  # 실제가 슬롯 평균과 다른 등급 = 열차별 표출이 새 정보를 줄 셀
    return {
        "n": len(err),
        "MAE_%p": round(float(err.abs().mean()), 2),
        "RMSE_%p": round(float(np.sqrt((err**2).mean())), 2),
        "등급일치_%": round(float((g_true == g_pred).mean() * 100), 2),
        "정보셀_%": round(float(informative.mean() * 100), 2),
        "정보셀_적중_%": (
            round(float((g_true[informative] == g_pred[informative]).mean() * 100), 2)
            if informative.any()
            else np.nan
        ),
    }


def evaluate_one(
    slot_loads: pd.DataFrame,
    timetable: pd.DataFrame,
    preds: dict[str, pd.DataFrame],
    cfg: SimConfig,
    seed: int,
) -> list[dict]:
    """한 (가정, seed)에 대해 예측기 4종의 열차·5분 지표."""
    truth = simulate(slot_loads, timetable, cfg, seed=seed)
    # oracle: 같은 seed의 편차 시각표를 알고, 모양 편차·Poisson은 모른다(기대값)
    oracle = simulate(
        slot_loads, timetable, replace(cfg, sigma_shape=0.0, poisson=False), seed=seed
    )
    oracle = oracle[[*TRAIN_JOIN, "congestion_true", "arr_min_true"]].rename(
        columns={"congestion_true": "pred_pct", "arr_min_true": "arr_min_plan"}
    )
    slot_pct = (
        truth[
            ["date", "station_no", "direction", "day_type", "time_slot_30min", "onboard_30min_est"]
        ]
        .assign(
            slot_pct=lambda d: d["onboard_30min_est"]
            / truth["train_capacity"]
            / truth.groupby(["date", "station_no", "direction", "day_type", "time_slot_30min"])[
                "train_id"
            ].transform("count")
            * 100.0
        )
        .drop(columns="onboard_30min_est")
        .drop_duplicates(["date", "station_no", "direction", "day_type", "time_slot_30min"])
    )
    t = truth[
        [
            *TRAIN_JOIN,
            "time_slot_30min",
            "congestion_true",
            "onboard_true",
            "train_capacity",
            "arr_min_true",
        ]
    ]
    t = t.merge(
        slot_pct, on=["date", "station_no", "direction", "day_type", "time_slot_30min"], how="left"
    )

    rows = []
    for name, pred in {**preds, "oracle_tt": oracle}.items():
        j = t.merge(pred[[*TRAIN_JOIN, "pred_pct", "arr_min_plan"]], on=TRAIN_JOIN, how="left")
        phantom = 1.0 - len(j.dropna(subset=["pred_pct"])) / max(len(pred), 1)
        j = j.dropna(subset=["pred_pct"])
        m_train = _metrics(j["congestion_true"], j["pred_pct"], j["slot_pct"])
        # 5분 빈: 실제는 실제 도착 시각의 빈, 예측은 계획 도착 시각의 빈. 빈 혼잡도 = Σ재차 ÷ Σ정원
        tb = (
            j.assign(bin=bin5_of(j["arr_min_true"]))
            .groupby(["date", "station_no", "direction", "bin"])
            .agg(
                onboard=("onboard_true", "sum"),
                cap=("train_capacity", "sum"),
                slot_pct=("slot_pct", "mean"),
            )
        )
        pb = (
            j.assign(
                bin=bin5_of(j["arr_min_plan"]),
                pred_load=j["pred_pct"] * j["train_capacity"] / 100.0,
            )
            .groupby(["date", "station_no", "direction", "bin"])
            .agg(pred_load=("pred_load", "sum"), cap_p=("train_capacity", "sum"))
        )
        b = tb.join(pb, how="inner")
        m_bin = _metrics(
            b["onboard"] / b["cap"] * 100.0, b["pred_load"] / b["cap_p"] * 100.0, b["slot_pct"]
        )
        base = {**{f"cfg_{k}": v for k, v in asdict(cfg).items()}, "seed": seed, "predictor": name}
        rows.append({**base, "unit": "train", "phantom_ratio": round(phantom, 4), **m_train})
        rows.append({**base, "unit": "bin5", "phantom_ratio": round(phantom, 4), **m_bin})
    return rows


# ── 실행 ──
def run(
    quick: bool, seeds: list[int], start: str, end: str
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    t0 = time.time()
    slot_loads, timetable, _, _ = prepare_inputs(pd.Timestamp(start), pd.Timestamp(end))
    preds = predict_all(slot_loads, timetable)
    print(
        f"[입력] 슬롯 {len(slot_loads):,} · 예측 열차 {len(preds['prop']):,} · {time.time() - t0:.0f}s",
        flush=True,
    )

    base_rows = []
    for scenario in GRID_SCENARIO:
        for seed in seeds:
            base_rows += evaluate_one(
                slot_loads, timetable, preds, SimConfig(scenario=scenario), seed
            )
            print(f"[기본] {scenario} seed{seed} {time.time() - t0:.0f}s", flush=True)
    base = pd.DataFrame(base_rows)

    grid = None
    if not quick:
        grid_rows = []
        for sigma, (h0, h1), scenario in itertools.product(GRID_SIGMA, GRID_MIX, GRID_SCENARIO):
            cfg = SimConfig(sigma_shape=sigma, mix_h0=h0, mix_h1=h1, scenario=scenario)
            for seed in seeds[:1]:
                grid_rows += evaluate_one(slot_loads, timetable, preds, cfg, seed)
            print(f"[격자] {cfg.tag()} {time.time() - t0:.0f}s", flush=True)
        grid = pd.DataFrame(grid_rows)
    return base, grid


def summarize(base: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    tables = []
    for unit in ("train", "bin5"):
        b = base[base["unit"] == unit]
        agg = (
            b.groupby(["cfg_scenario", "predictor"], sort=False)[
                ["MAE_%p", "RMSE_%p", "등급일치_%", "정보셀_%", "정보셀_적중_%", "phantom_ratio"]
            ]
            .mean()
            .round(2)
            .reset_index()
        )
        flat = agg[agg["predictor"] == "slot_flat"].set_index("cfg_scenario")["등급일치_%"]
        agg["Δ일치_vs_flat_%p"] = (agg["등급일치_%"] - agg["cfg_scenario"].map(flat)).round(2)
        tables.append(
            (f"{'열차' if unit == 'train' else '5분 빈'} 단위 — 시나리오 × 예측기 (seed 평균)", agg)
        )
    return tables


def summarize_grid(grid: pd.DataFrame) -> pd.DataFrame:
    g = grid[(grid["unit"] == "train") & (grid["predictor"].isin(["slot_flat", "mix"]))]
    piv = g.pivot_table(
        index=["cfg_scenario", "cfg_sigma_shape", "cfg_mix_h0", "cfg_mix_h1"],
        columns="predictor",
        values="등급일치_%",
    ).reset_index()
    piv["Δ일치_mix−flat_%p"] = (piv["mix"] - piv["slot_flat"]).round(2)
    return piv.round(2)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--quick", action="store_true", help="민감도 격자 생략")
    ap.add_argument("--seeds", default="0,1")
    ap.add_argument("--start", default="2025-06-02")
    ap.add_argument("--end", default="2025-06-08")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    base, grid = run(args.quick, [int(s) for s in args.seeds.split(",")], args.start, args.end)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base.to_parquet(OUT_DIR / "sim_eval_base.parquet", index=False)
    chunks = []
    for title, tbl in summarize(base):
        print(f"\n### {title}\n{tbl.to_string(index=False)}", flush=True)
        chunks.append(f"### {title}\n\n{to_markdown(tbl)}\n")
    if grid is not None:
        grid.to_parquet(OUT_DIR / "sim_eval_grid.parquet", index=False)
        piv = summarize_grid(grid)
        print(
            f"\n### 민감도 격자 — 열차 단위 등급 일치율(mix vs slot_flat)\n{piv.to_string(index=False)}"
        )
        chunks.append(
            f"### 민감도 격자 — 열차 단위 등급 일치율(mix vs slot_flat)\n\n{to_markdown(piv)}\n"
        )
    if args.out:
        Path(args.out).write_text("\n".join(chunks), encoding="utf-8")
        print(f"\n[저장] {args.out}")


if __name__ == "__main__":
    main(sys.argv[1:])
