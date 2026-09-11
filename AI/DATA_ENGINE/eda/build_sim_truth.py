"""시뮬레이션 정답 표 생성 — 92번. `app.CROWD.pipeline.simulate`에 실데이터를 넣어 저장한다.

입력은 135 열차별 표와 같다(`build_load_by_train.prepare_inputs`): 88 보정 라벨의 30분 방향별 재차인원과
1~8호선 시각표. 기본 가정 한 벌(σ_shape 0.05, 도착 혼합 5~15분, Poisson, 운행 편차 없음)을 시나리오
3종(none/delay/skip) × seed 3으로 저장한다. 민감도 격자는 저장하지 않고 평가기가 메모리에서 돈다
(`validation/CROWD/sim-eval/evaluate.py`).

    cd AI
    python -m DATA_ENGINE.eda.build_sim_truth                       # 2025-06-02~08, seeds 0,1,2
    python -m DATA_ENGINE.eda.build_sim_truth --seeds 0 --scenarios none

출력: data/CROWD/interim/sim/sim_truth_<start>_<end>_<scenario>_seed<k>.parquet + _meta.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from app.CROWD.pipeline.simulate import SCENARIOS, SimConfig, simulate
from DATA_ENGINE.eda.build_load_by_train import prepare_inputs

AI_ROOT = Path(__file__).resolve().parents[2]
SIM_DIR = AI_ROOT / "data" / "CROWD" / "interim" / "sim"


def build(
    start: pd.Timestamp,
    end: pd.Timestamp,
    scenarios: list[str],
    seeds: list[int],
    base: SimConfig | None = None,
    out_dir: Path = SIM_DIR,
) -> dict:
    base = base or SimConfig()
    slot_loads, tt_alloc, _labels, _lab = prepare_inputs(start, end)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta: dict = {
        "start": f"{start:%Y-%m-%d}",
        "end": f"{end:%Y-%m-%d}",
        "slot_cells": len(slot_loads),
        "slot_mass": float(slot_loads["onboard_30min_est"].sum()),
        "runs": [],
    }
    for scenario in scenarios:
        cfg = SimConfig(**{**asdict(base), "scenario": scenario})
        for seed in seeds:
            t0 = time.time()
            truth = simulate(slot_loads, tt_alloc, cfg, seed=seed)
            name = f"sim_truth_{start:%Y%m%d}_{end:%Y%m%d}_{scenario}_seed{seed}.parquet"
            truth.to_parquet(out_dir / name, index=False)
            mass = float(truth["onboard_true"].sum())
            run = {
                "scenario": scenario,
                "seed": seed,
                "rows": len(truth),
                "mass_true": mass,
                "mass_gap_pct": round((mass / meta["slot_mass"] - 1) * 100, 3),
                "delayed_ratio": round(float(truth["delayed"].mean()), 4),
                "seconds": round(time.time() - t0, 1),
                "path": name,
            }
            meta["runs"].append(run)
            print(run, flush=True)
    (out_dir / f"sim_truth_{start:%Y%m%d}_{end:%Y%m%d}_meta.json").write_text(
        json.dumps({**meta, "base_config": asdict(base)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return meta


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--start", default="2025-06-02")
    ap.add_argument("--end", default="2025-06-08")
    ap.add_argument("--scenarios", default=",".join(SCENARIOS))
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--sigma-shape", type=float, default=0.05)
    ap.add_argument("--mix-h0", type=float, default=5.0)
    ap.add_argument("--mix-h1", type=float, default=15.0)
    args = ap.parse_args(argv)
    base = SimConfig(sigma_shape=args.sigma_shape, mix_h0=args.mix_h0, mix_h1=args.mix_h1)
    build(
        pd.Timestamp(args.start),
        pd.Timestamp(args.end),
        args.scenarios.split(","),
        [int(s) for s in args.seeds.split(",")],
        base,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
