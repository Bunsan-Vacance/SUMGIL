"""line9-model-check 3단계 — 게이트: 9호선 13역이 lookup보다 나은가.

## 왜 새 분할을 쓰는가

9호선 패널은 2024-12-31~2026-01(학습 창 안은 2024-12-31~2025-12-31)만 있어 기존 분할
(2024 학습 / 2025 평가)로는 9호선을 평가할 수 없다(9호선 학습 표본이 하루도 없다). 그래서
`--split-date 2025-10-01`(학습 ~2025-09-30 / 평가 2025-10-01~2025-12-31)을 쓴다 — 9호선도
9개월치 학습 표본(2024-12-31~2025-09-30)이 생긴다.

## 무엇을 재사용하는가

`masking-check/compare.py`·`dl-resid-check/evaluate_dl.py`가 쓰는 시나리오 정의(`masking.SCENARIOS`,
LightGBM 마스킹 컬럼 접두 `masking.LAG_COLUMN_PREFIXES` = `evaluate_dl.LGB_MASK`)와 부트스트랩
순수 함수(`significance-check/bootstrap.py`)를 그대로 가져다 쓴다(복붙 금지, import만). 다만 그
스크립트들은 평가 시작일을 `2025-01-01`로 하드코딩해 두어(모듈 상수) 이 게이트의 분할
(`2025-10-01`)에 맞게 그대로 쓸 수 없다 — CLI 인자를 하드코딩된 상수 위에 새로 얹는 대신, 이
파일이 자체 `prepare()`로 병합 패널을 그 분할로 나누고, `CrowdPredictor.predict_derived`
(아티팩트 자체 lookup 사용) + `boot.*`(날짜 블록 부트스트랩)만 가져다 쓴다.

## 게이트 정의

- 아티팩트: `build_merged_panel.py`가 만든 병합 패널로 `train.py --mask-mode stack
  --split-date 2025-10-01`을 1회 학습한 것(`models/CROWD/_experiments/line9/gate_stack_split20251001`).
- 평가 시나리오: `no_lag`(시차 전부 NaN) — 9호선은 D−1 수집기가 커버하지 않아 서빙 시
  영구 결측이므로, 9호선의 실질 성능은 `no_lag` 시나리오로만 봐야 한다(`masking-check/RESULTS.md`
  1절과 같은 논리).
- 기준선: 같은 분할로 fit한 lookup(요일유형×역×시간대 평균) — 아티팩트 자체의
  `lookup.parquet`을 그대로 쓴다(`CrowdPredictor.predict_derived`가 같은 호출에서
  `{target}_lookup`·`{target}_pred`를 함께 낸다 — 별도로 lookup을 다시 fit할 필요가 없다).
- 표본: 평가 구간(2025-10-01~2025-12-31)의 9호선 13역 행(`station_no` 4126~4138)과, 비교용으로
  같은 구간의 1~8호선 행(공통 행 계산은 두 그룹에 같은 마스크를 적용한 뒤 station_no로만 나눈다
  — 그룹마다 다른 공통 행 규칙을 쓰면 안 된다는 `AI/CLAUDE.md` 하드 룰 2).
- CI: 날짜 블록 쌍(paired) 부트스트랩 1,000회(seed 0).

## 판정

9호선 행의 `no_lag` RMSE 개선율 CI 하한이 0보다 크면 통과. 0 이하면 기각.

실행:
    cd AI
    python validation/CROWD/line9-model-check/gate_check.py
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[2]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))


def _load_sibling(rel_path: str, name: str):
    """다른 하이픈 폴더의 검증 스크립트를 파일 경로로 재사용한다(수정 금지, import만 —
    masking-check/compare.py·window_diff.py와 같은 관례)."""
    spec = importlib.util.spec_from_file_location(name, AI_ROOT / rel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


boot = _load_sibling("validation/CROWD/significance-check/bootstrap.py", "line9_check_bootstrap")

from app.CROWD.pipeline.dataset import (
    CROWD_INTERIM,
    CROWD_PROCESSED,
    load_or_build_derived,
    load_panel,
    time_split,
)
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline
from app.CROWD.pipeline.masking import LAG_COLUMN_PREFIXES, SCENARIOS
from app.CROWD.pipeline.predict import CrowdPredictor

MERGED_PANEL_NAME = "crowd_panel_2024_2025_line9.parquet"
MERGED_DERIVED_CACHE = CROWD_INTERIM / "crowd_panel_derived_2024_2025_line9.parquet"
SPLIT_DATE = pd.Timestamp("2025-10-01")
LINE9_STATIONS = list(range(4126, 4139))  # 4126 언주 ~ 4138 중앙보훈병원
DEFAULT_ARTIFACT = (
    AI_ROOT / "models" / "CROWD" / "_experiments" / "line9" / "gate_stack_split20251001"
)
OUT_DIR = CROWD_INTERIM / "validation" / "line9_model_check"


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=AI_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


# ── 준비 ──
def prepare(
    panel_path: Path,
    derived_cache: Path,
    split_date: pd.Timestamp,
    events_path: Path | None = None,
) -> dict:
    t0 = time.time()
    # `load_panel`의 `events_path` 기본값은 패널명과 무관한 고정값(`EVENTS_NAME`)이라,
    # 병합 패널을 줘도 9호선 이벤트가 붙지 않는다 — 명시적으로 받아야 한다.
    kw = {} if events_path is None else {"events_path": events_path}
    panel = load_panel(panel_path=panel_path, with_events=True, **kw)
    train_raw, _test_raw = time_split(panel, split_date)
    lookup_for_derived = DayTypeLookupBaseline().fit(train_raw)
    derived = load_or_build_derived(
        panel,
        lookup_for_derived,
        cache_path=derived_cache,
        panel_path=panel_path,
    )
    train, test = time_split(derived, split_date)
    print(
        f"[준비] 전체 {len(derived):,}행 · 학습 {len(train):,}행 · 평가 {len(test):,}행 · "
        f"{time.time() - t0:.0f}s",
        flush=True,
    )
    return {"panel": panel, "derived": derived, "train": train, "test": test}


def mask_scenario(frame: pd.DataFrame, scenario: str) -> pd.DataFrame:
    """`scenario`가 가리는 시차 컬럼을 NaN으로 덮은 복사본(`masking.LAG_COLUMN_PREFIXES` 규칙)."""
    out = frame.copy()
    prefixes = LAG_COLUMN_PREFIXES[scenario]
    cols = [c for c in out.columns if c.startswith(prefixes)] if prefixes else []
    if cols:
        out[cols] = np.nan
    return out


# ── 예측·정렬 ──
def predict_scenario(artifact_dir: Path, test: pd.DataFrame, scenario: str) -> pd.DataFrame:
    predictor = CrowdPredictor(artifact_dir)
    masked = mask_scenario(test, scenario)
    pred = predictor.predict_derived(masked)
    return test[["date", "station_no", "time_slot", *TARGETS]].merge(
        pred, on=["date", "station_no", "time_slot"], how="left"
    )


# ── 날짜별 손실 충분통계(그룹 = line9 vs 1~8호선) ──
def daily_losses(common: pd.DataFrame) -> pd.DataFrame:
    rows = []
    group = np.where(common["station_no"].isin(LINE9_STATIONS), "line9", "line1_8")
    for target in TARGETS:
        truth = common[target].to_numpy(dtype="float64")
        err_lookup = common[f"{target}_lookup"].to_numpy(dtype="float64") - truth
        err_model = common[f"{target}_pred"].to_numpy(dtype="float64") - truth
        agg = (
            pd.DataFrame(
                {
                    "date": common["date"],
                    "group": group,
                    "n": 1,
                    "sse_lookup": err_lookup**2,
                    "sae_lookup": np.abs(err_lookup),
                    "sse_model": err_model**2,
                    "sae_model": np.abs(err_model),
                }
            )
            .groupby(["date", "group"], observed=True)
            .sum()
            .reset_index()
            .assign(target=target)
        )
        rows.append(agg)
    return pd.concat(rows, ignore_index=True)


def bootstrap_improvement(losses: pd.DataFrame, n_boot: int, seed: int) -> pd.DataFrame:
    """그룹×타깃마다 lookup 대비 RMSE·MAE 개선율 점추정 + 95% CI(날짜 블록 쌍 부트스트랩)."""
    dates = np.sort(losses["date"].unique())
    n_dates = len(dates)
    counts = boot.resample_counts(boot.resample_dates(n_dates, n_boot, seed), n_dates)
    date_index = {d: i for i, d in enumerate(dates)}
    rows = []
    for (group, target), sub in losses.groupby(["group", "target"], observed=True):
        pos = sub["date"].map(date_index).to_numpy()
        n_vec = np.zeros(n_dates)
        n_vec[pos] = sub["n"].to_numpy(dtype="float64")
        sse_lookup = np.zeros(n_dates)
        sae_lookup = np.zeros(n_dates)
        sse_model = np.zeros(n_dates)
        sae_model = np.zeros(n_dates)
        sse_lookup[pos] = sub["sse_lookup"].to_numpy(dtype="float64")
        sae_lookup[pos] = sub["sae_lookup"].to_numpy(dtype="float64")
        sse_model[pos] = sub["sse_model"].to_numpy(dtype="float64")
        sae_model[pos] = sub["sae_model"].to_numpy(dtype="float64")

        full = np.ones((1, n_dates))
        point_rmse = boot.improvement_pct(
            boot.weighted_rmse(full, sse_lookup, n_vec), boot.weighted_rmse(full, sse_model, n_vec)
        )[0]
        point_mae = boot.improvement_pct(
            boot.weighted_mae(full, sae_lookup, n_vec), boot.weighted_mae(full, sae_model, n_vec)
        )[0]
        boot_rmse = boot.improvement_pct(
            boot.weighted_rmse(counts, sse_lookup, n_vec),
            boot.weighted_rmse(counts, sse_model, n_vec),
        )
        boot_mae = boot.improvement_pct(
            boot.weighted_mae(counts, sae_lookup, n_vec),
            boot.weighted_mae(counts, sae_model, n_vec),
        )
        rmse_lo, rmse_hi = boot.percentile_ci(boot_rmse)
        mae_lo, mae_hi = boot.percentile_ci(boot_mae)
        rows.append(
            {
                "group": group,
                "target": target,
                "n_rows": int(n_vec.sum()),
                "n_dates": int((n_vec > 0).sum()),
                "RMSE_개선율_%": point_rmse,
                "RMSE_CI_low": rmse_lo,
                "RMSE_CI_high": rmse_hi,
                "MAE_개선율_%": point_mae,
                "MAE_CI_low": mae_lo,
                "MAE_CI_high": mae_hi,
            }
        )
    return pd.DataFrame(rows)


def run(args: argparse.Namespace) -> pd.DataFrame:
    t0 = time.time()
    panel_path = CROWD_PROCESSED / args.panel
    artifact_dir = Path(args.artifact)
    events_path = CROWD_PROCESSED / args.events if args.events else None
    data = prepare(panel_path, Path(args.derived_cache), SPLIT_DATE, events_path)
    test = data["test"]

    pred = predict_scenario(artifact_dir, test, args.scenario)
    finite = (
        np.isfinite(pred[f"{TARGETS[0]}_lookup"])
        & np.isfinite(pred[f"{TARGETS[1]}_lookup"])
        & np.isfinite(pred[f"{TARGETS[0]}_pred"])
        & np.isfinite(pred[f"{TARGETS[1]}_pred"])
    )
    common = pred[finite].reset_index(drop=True)
    print(
        f"[공통 행] {len(common):,} / {len(pred):,} ({finite.mean() * 100:.2f}%) · 시나리오 {args.scenario}",
        flush=True,
    )
    n_line9 = int(common["station_no"].isin(LINE9_STATIONS).sum())
    n_other = len(common) - n_line9
    print(f"[표본] 9호선 {n_line9:,}행 · 1~8호선 {n_other:,}행", flush=True)

    losses = daily_losses(common)
    result = bootstrap_improvement(losses, args.n_boot, args.seed)
    result = result.assign(
        scenario=args.scenario,
        artifact=artifact_dir.name,
        panel=panel_path.name,
        split_date=str(SPLIT_DATE.date()),
        n_boot=args.n_boot,
        seed=args.seed,
        git_commit=_git_commit(),
    )

    print(f"\n### 게이트 결과 — 시나리오 {args.scenario}")
    print(result.round(3).to_string(index=False))

    gate_rows = result[(result["group"] == "line9")]
    passed = bool((gate_rows["RMSE_CI_low"] > 0).all())
    print(f"\n### 판정 — 9호선 no_lag RMSE 개선율 CI 하한 > 0: {'통과' if passed else '기각'}")
    for _, r in gate_rows.iterrows():
        print(
            f"  {r['target']}: {r['RMSE_개선율_%']:+.2f}% [{r['RMSE_CI_low']:+.2f}, "
            f"{r['RMSE_CI_high']:+.2f}] (n_dates={r['n_dates']}, n_rows={r['n_rows']})"
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"gate_check_{args.scenario}.parquet"
    result.to_parquet(out_path, index=False)
    print(f"\n[저장] {out_path} · {time.time() - t0:.0f}s", flush=True)
    return result


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--panel", default=MERGED_PANEL_NAME)
    ap.add_argument("--derived-cache", default=str(MERGED_DERIVED_CACHE))
    ap.add_argument("--events", default=None, help="이벤트 표 파일명(기본: dataset.EVENTS_NAME)")
    ap.add_argument("--artifact", default=str(DEFAULT_ARTIFACT))
    ap.add_argument("--scenario", default="no_lag", choices=list(SCENARIOS))
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    run(args)


if __name__ == "__main__":
    main(sys.argv[1:])
