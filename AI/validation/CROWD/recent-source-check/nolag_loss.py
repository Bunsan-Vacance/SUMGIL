"""143 1단계 — 시차 피처가 없을 때(D−1 수집기가 없는 2026 운영) 배포 모델이 얼마나 퇴화하는지.

같은 모델(배포 세트 `festival_selflag_d1sd_d7_resid`, 2024 학습)을 두고 **평가 행의 시차 컬럼만 NaN**으로 바꿔
서빙 상황을 재현한다. 학습은 한 번, 평가만 세 번.
- `full`    — 현행(패널 안 날짜라 시차가 다 있다).
- `no_lag`  — `lag1d_*`·`lag7d_*`·`lagsd_*` 전부 NaN = 수집기 없이 2026 실제 날짜를 예측할 때.
- `d7_only` — `lag1d_*`·`lagsd_*`만 NaN(1주 전 값은 있는 상황, 참고).
지표는 전체·요일유형별·호선별 RMSE/MAE와 lookup 대비 개선율. `compare_split.fit_predict`·`metrics_rows` 재사용.

실행:
    cd AI
    python validation/CROWD/recent-source-check/nolag_loss.py --save-results data/CROWD/interim/validation/nolag_results.parquet
예상: 파생 캐시 읽기 + fit 1회 ≈ 1분.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[2]
for p in (
    str(AI_ROOT),
    str(AI_ROOT / "validation" / "CROWD" / "baseline-check"),
    str(AI_ROOT / "validation" / "CROWD" / "split-check"),
):
    if p not in sys.path:
        sys.path.insert(0, p)

from compare_split import metrics_rows
from evaluate_final import to_markdown

from app.CROWD.pipeline.dataset import load_or_build_derived, load_panel, time_split
from app.CROWD.pipeline.features import FEATURE_SETS, build_matrix
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline
from app.CROWD.pipeline.train import train_models

DEPLOY_SET = "festival_selflag_d1sd_d7_resid"
SCENARIOS = {
    "full": (),
    "no_lag": ("lag1d_", "lag7d_", "lagsd_"),
    "d7_only": ("lag1d_", "lagsd_"),
}


def mask_lags(test: pd.DataFrame, prefixes: tuple[str, ...]) -> pd.DataFrame:
    out = test.copy()
    cols = [c for c in FEATURE_SETS[DEPLOY_SET] if c.startswith(prefixes)] if prefixes else []
    out[cols] = np.nan
    return out


def run(save_results: str | None) -> pd.DataFrame:
    t0 = time.time()
    panel = load_panel(with_events=True)
    train_raw, _ = time_split(panel)
    lookup = DayTypeLookupBaseline().fit(train_raw)
    derived = load_or_build_derived(panel, lookup)
    train, test = time_split(derived)
    test = test.reset_index(drop=True)
    lookup_pred = lookup.predict(test)
    models = train_models(train, lookup, DEPLOY_SET, group_col=None)
    print(f"[준비+학습] {time.time() - t0:.0f}s · 평가 {len(test):,}행", flush=True)

    rows: list[dict] = []
    for name, prefixes in SCENARIOS.items():
        te = mask_lags(test, prefixes)
        X = build_matrix(te, DEPLOY_SET)
        preds = {t: lookup_pred[t].to_numpy() + models[t]["__all__"].predict(X) for t in TARGETS}
        rows += metrics_rows(test, lookup_pred, preds, name)
        tot = [r for r in rows if r["run"] == name and r["axis"] == "전체"]
        print(
            f"[{name}] RMSE 개선율 승차 {tot[0]['RMSE_개선율_%']} / 하차 {tot[1]['RMSE_개선율_%']}"
            f" · MAE {tot[0]['MAE_개선율_%']} / {tot[1]['MAE_개선율_%']}",
            flush=True,
        )
    res = pd.DataFrame(rows)
    if save_results:
        Path(save_results).parent.mkdir(parents=True, exist_ok=True)
        res.to_parquet(save_results, index=False)
    return res


def summarize(res: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    out = []
    tot = res[res["axis"] == "전체"].pivot_table(
        index="run", columns="target", values=["rmse", "mae", "RMSE_개선율_%", "MAE_개선율_%"]
    )
    tot.columns = [f"{m}_{t}" for m, t in tot.columns]
    tot = tot.reindex(list(SCENARIOS))
    out.append(
        ("전체 — 시나리오별 절대 RMSE/MAE와 lookup 대비 개선율(%)", tot.reset_index().round(2))
    )
    for axis, title in (
        ("day_type", "요일유형별 RMSE 개선율(승차)"),
        ("line", "호선별 RMSE 개선율(승차)"),
    ):
        piv = res[(res["axis"] == axis) & (res["target"] == "boarding")].pivot_table(
            index="group", columns="run", values="RMSE_개선율_%"
        )[list(SCENARIOS)]
        for c in ("no_lag", "d7_only"):
            piv[f"Δ{c}"] = (piv[c] - piv["full"]).round(2)
        out.append((title, piv.reset_index().round(2)))
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--save-results", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    res = run(args.save_results)
    chunks = []
    for title, tbl in summarize(res):
        print(f"\n### {title}\n{tbl.to_string(index=False)}")
        chunks.append(f"### {title}\n\n{to_markdown(tbl)}\n")
    if args.out:
        Path(args.out).write_text("\n".join(chunks), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
