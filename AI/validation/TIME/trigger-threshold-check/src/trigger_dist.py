"""실스냅샷 표본으로 TIME 재안내 트리거(`p_empty ≥ P` / `predicted_stock < 1`) 발동 비율을 본다.

실행(리포 `AI/`에서, 실스냅샷 `data/BIKE/raw/realtime/latest_stock.parquet`·`bike_stock_pred` 표 필요):

    PYTHONPATH=. python validation/TIME/trigger-threshold-check/src/trigger_dist.py [--n 200] [--seed 7]

운영 서버(J15A104A)에서는 `/tmp`에 복사해 같은 명령으로 돌린다 — 로컬은 배치 표가 없으면 `AvgDataMissing`이 난다.
"""

from __future__ import annotations

import argparse
import random
import time

import pandas as pd

from app.BIKE import service

SNAPSHOT = "data/BIKE/raw/realtime/latest_stock.parquet"
ETAS = (5, 15, 30)
P_THRESHOLDS = (0.5, 0.6, 0.7)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    snap = pd.read_parquet(SNAPSHOT)
    random.seed(args.seed)
    sample = random.sample(snap.rental_id.tolist(), args.n)
    rows = []
    t0 = time.time()
    for rid in sample:
        for eta in ETAS:
            try:
                r = service.predict_eta_stock(rid, eta)
            except Exception as e:  # 표본 하나의 실패는 집계에서만 뺀다
                rows.append((rid, eta, None, None, type(e).__name__))
                continue
            rows.append((rid, eta, r["predicted_stock"], r["p_empty"], r["source"]))
    df = pd.DataFrame(rows, columns=["rid", "eta", "pred", "p_empty", "src"])
    print(f"elapsed {time.time() - t0:.1f}s n {len(df)} errors {df.pred.isna().sum()}")
    cur_by_id = snap.set_index("rental_id")["current_stock"]
    for eta, g in df.dropna(subset=["pred"]).groupby("eta"):
        cur = cur_by_id.loc[g.rid].values
        parts = [f"eta={eta:2d}"]
        for p in P_THRESHOLDS:
            parts.append(f"p>={p}: {(g.p_empty >= p).mean():.1%}")
        parts.append(f"pred<1: {(g.pred < 1).mean():.1%}")
        parts.append(f"pred<1&cur>0: {((g.pred < 1) & (cur > 0)).mean():.1%}")
        parts.append(f"cur0: {(cur == 0).mean():.1%}")
        parts.append(
            f"p_empty q50/q90/q95={g.p_empty.quantile(0.5):.2f}/{g.p_empty.quantile(0.9):.2f}/{g.p_empty.quantile(0.95):.2f}"
        )
        print("  ".join(parts))


if __name__ == "__main__":
    main()
