"""145 통계 모형 비교 검증 — 표 A~D(날짜 블록 부트스트랩 CI · DM · 재현율 · 92 표본 점추정).

## 왜

`predict_all.py`가 계열별 2025 예측을 만들어 두면, 이 스크립트는 그것들을 **같은 공통 행**에
모아 lookup 대비 개선율에 구간을 붙이고(142 `significance-check/bootstrap.py`와 같은 방법),
LightGBM과의 **쌍 비교**로 "통계 모형이 LightGBM 개선분의 몇 %를 재현하는가"를 답한다.

## 방법(142 재사용)

날짜 블록 부트스트랩·Diebold-Mariano의 순수 함수(`resample_dates`, `weighted_rmse`,
`improvement_pct`, `diebold_mariano` 등)는 `significance-check/bootstrap.py`에서 그대로
가져온다(복붙 금지, import만 — 계획 §3). 날짜별 손실 충분통계(SSE·SAE·n)만 있으면 재표본마다
RMSE·MAE를 정확히 다시 계산할 수 있다는 그 스크립트의 항등식을 여기서도 그대로 쓴다.

## 표

- **A** — 계열별 lookup 대비 RMSE·MAE 개선율 + 95% CI + DM(vs lookup).
- **B** — LightGBM과의 **쌍 차이**(`개선율_lightgbm − 개선율_계열`) CI + DM(계열 vs LightGBM
  날짜별 MSE 차이). 142 §7이 남긴 "쌍 부트스트랩" 과제를 여기서 처리한다.
- **C** — "LightGBM 개선분 재현율" = 개선율_계열 / 개선율_lightgbm(전체, 승·하).
- **D** — 92 표본(`sim-eval/compare_families.pick_sample(test, 50, 30, seed=0)`과 같은 행) 위
  점추정 RMSE·MAE(구간 없음).

등급 일치율(표본이 아니라 셀 단위 배율표 필요)은 로컬에 배율표가 없어 건너뛴다 — RESULTS 미해결에
남긴다.

실행(폴더명에 하이픈이 있어 파일 경로로 돈다. `predict_all.py`로 예측을 먼저 만들어야 한다):
    cd AI
    python validation/CROWD/stat-model-check/evaluate.py --out RESULTS_tables.md
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[2]
for _p in (str(AI_ROOT), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.CROWD.pipeline.dataset import CROWD_INTERIM, load_panel, time_split  # noqa: E402
from app.CROWD.pipeline.dl.dataset import load_derived_slim  # noqa: E402
from app.CROWD.pipeline.lookup import TARGETS  # noqa: E402


def _load_sibling(rel_path: str, name: str):
    """다른 하이픈 폴더의 검증 스크립트를 파일 경로로 재사용한다(수정 금지, import만 — 계획 §3)."""
    spec = importlib.util.spec_from_file_location(name, AI_ROOT / rel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


boot = _load_sibling(
    "validation/CROWD/significance-check/bootstrap.py", "crowd_stat_model_check_bootstrap"
)
compare_families = _load_sibling(
    "validation/CROWD/sim-eval/compare_families.py", "crowd_stat_model_check_compare_families2"
)

KEY = ["date", "station_no", "time_slot"]
AXES = {"전체": None, "호선": "line", "요일유형": "day_type"}
OUT_DIR = CROWD_INTERIM / "validation" / "stat_model_check"
SPLIT_DATE = pd.Timestamp("2025-01-01")
LIGHTGBM = "lightgbm"
CANDIDATE_SERIES = [
    "snaive_d7",
    "ols_pooled",
    "ols_series",
    "sarima_raw",
    "sarimax_resid",
    LIGHTGBM,
]
DERIVED_COLS = ["date", "station_no", "line", "time_slot", "day_type", *TARGETS]


# 실측 최댓값(승 26,951 / 하 20,476, 2024~2025 패널)의 약 3.7배. SARIMA(특히 `enforce_stationarity=False`로
# 둔 근단위근 계열)가 결측 구간에서 개루프로 전파되며 드물게(<0.15%행) 발산한다(계획에 없는 사후 점검 —
# RESULTS에 명시). 적합 자체는 성공(`ok=True`)했지만 물리적으로 불가능한 값이라 그 행만 NaN으로 되돌린다
# (원칙 8 — 채우지 않고 결측으로 남긴다. 여기서는 "있던 값을 결측 처리"하는 예외적 조치라 개수를 센다).
DIVERGENCE_BOUND = 1.0e5


# ── 로딩 ──
def load_predictions(names: list[str]) -> dict[str, pd.DataFrame]:
    preds = {}
    for name in names:
        path = OUT_DIR / f"stat_preds_{name}.parquet"
        if not path.exists():
            print(f"[안내] {name} 예측 파일이 없다({path.name}) — 건너뜀.", flush=True)
            continue
        frame = pd.read_parquet(path)
        for t in TARGETS:
            col = f"{t}_pred"
            bad = frame[col].abs() > DIVERGENCE_BOUND
            if bad.any():
                print(
                    f"[발산] {name}.{col}: {int(bad.sum()):,}행이 {DIVERGENCE_BOUND:.0e}을 넘어 "
                    "NaN으로 되돌림",
                    flush=True,
                )
                frame.loc[bad, col] = np.nan
        preds[name] = frame
    return preds


def build_common_frame(
    test: pd.DataFrame, frames: dict[str, pd.DataFrame]
) -> tuple[pd.DataFrame, dict[str, float], float]:
    """모든 계열이 유한한 공통 행만 남긴다. 계열별 자기 유효행 비율과 공통 행 비율을 함께 낸다."""
    merged = test[["date", "station_no", "time_slot", "line", "day_type", *TARGETS]].copy()
    own_coverage: dict[str, float] = {}
    for name, frame in frames.items():
        sub = frame[[*KEY, *[f"{t}_pred" for t in TARGETS]]].rename(
            columns={f"{t}_pred": f"{name}__{t}" for t in TARGETS}
        )
        cols = [f"{name}__{t}" for t in TARGETS]
        own_finite = np.isfinite(sub[cols].to_numpy(dtype="float64")).all(axis=1)
        own_coverage[name] = float(own_finite.mean())
        merged = merged.merge(sub, on=KEY, how="left")
    value_cols = [f"{name}__{t}" for name in frames for t in TARGETS]
    finite = np.isfinite(merged[value_cols].to_numpy(dtype="float64")).all(axis=1)
    common_ratio = float(finite.mean())
    print(
        f"[공통 행] {int(finite.sum()):,} / {len(merged):,} ({common_ratio * 100:.2f}%)", flush=True
    )
    for name, cov in own_coverage.items():
        print(f"  · {name} 자기 유효행 {cov * 100:.2f}%", flush=True)
    common = merged[finite].reset_index(drop=True)
    return common, own_coverage, common_ratio


# ── 날짜별 손실 충분통계(다계열) ──
def daily_losses_multi(common: pd.DataFrame, series_names: list[str]) -> pd.DataFrame:
    rows = []
    for axis, col in AXES.items():
        group = pd.Series("전체", index=common.index) if col is None else common[col].astype(str)
        for target in TARGETS:
            truth = common[target].to_numpy(dtype="float64")
            base_df = pd.DataFrame({"date": common["date"], "group": group, "n": 1})
            for name in series_names:
                err = common[f"{name}__{target}"].to_numpy(dtype="float64") - truth
                base_df[f"sse__{name}"] = err**2
                base_df[f"sae__{name}"] = np.abs(err)
            agg = (
                base_df.groupby(["date", "group"], observed=True)
                .sum()
                .reset_index()
                .assign(axis=axis, target=target)
            )
            rows.append(agg)
    return pd.concat(rows, ignore_index=True)


# ── 표 A: lookup 대비 개선율 + CI + DM ──
def table_a(losses: pd.DataFrame, series_names: list[str], n_boot: int, seed: int) -> pd.DataFrame:
    dates = np.sort(losses["date"].unique())
    n_dates = len(dates)
    counts = boot.resample_counts(boot.resample_dates(n_dates, n_boot, seed), n_dates)
    date_index = {d: i for i, d in enumerate(dates)}
    rows = []
    for (axis, group, target), sub in losses.groupby(["axis", "group", "target"], observed=True):
        pos = sub["date"].map(date_index).to_numpy()
        n_vec = np.zeros(n_dates)
        n_vec[pos] = sub["n"].to_numpy(dtype="float64")
        sse_lookup = np.zeros(n_dates)
        sae_lookup = np.zeros(n_dates)
        sse_lookup[pos] = sub["sse__lookup"].to_numpy(dtype="float64")
        sae_lookup[pos] = sub["sae__lookup"].to_numpy(dtype="float64")
        full = np.ones((1, n_dates))
        base_rmse_point = boot.weighted_rmse(full, sse_lookup, n_vec)[0]
        base_mae_point = boot.weighted_mae(full, sae_lookup, n_vec)[0]
        boot_rmse_base = boot.weighted_rmse(counts, sse_lookup, n_vec)
        boot_mae_base = boot.weighted_mae(counts, sae_lookup, n_vec)
        for name in series_names:
            sse = np.zeros(n_dates)
            sae = np.zeros(n_dates)
            sse[pos] = sub[f"sse__{name}"].to_numpy(dtype="float64")
            sae[pos] = sub[f"sae__{name}"].to_numpy(dtype="float64")
            point_rmse = boot.improvement_pct(
                np.array([base_rmse_point]), boot.weighted_rmse(full, sse, n_vec)
            )[0]
            point_mae = boot.improvement_pct(
                np.array([base_mae_point]), boot.weighted_mae(full, sae, n_vec)
            )[0]
            boot_rmse = boot.improvement_pct(boot_rmse_base, boot.weighted_rmse(counts, sse, n_vec))
            boot_mae = boot.improvement_pct(boot_mae_base, boot.weighted_mae(counts, sae, n_vec))
            rmse_lo, rmse_hi = boot.percentile_ci(boot_rmse)
            mae_lo, mae_hi = boot.percentile_ci(boot_mae)
            ok = n_vec > 0
            dm = boot.diebold_mariano((sse[ok] - sse_lookup[ok]) / n_vec[ok])
            rows.append(
                {
                    "series": name,
                    "axis": axis,
                    "group": group,
                    "target": target,
                    "n_rows": int(n_vec.sum()),
                    "n_dates": int(ok.sum()),
                    "RMSE_개선율_%": point_rmse,
                    "RMSE_CI_low": rmse_lo,
                    "RMSE_CI_high": rmse_hi,
                    "MAE_개선율_%": point_mae,
                    "MAE_CI_low": mae_lo,
                    "MAE_CI_high": mae_hi,
                    "DM_stat": dm["stat"],
                    "DM_p": dm["p"],
                }
            )
    return pd.DataFrame(rows)


# ── 표 B: LightGBM 대비 쌍 차이 ──
def table_b(losses: pd.DataFrame, series_names: list[str], n_boot: int, seed: int) -> pd.DataFrame:
    candidates = [s for s in series_names if s != LIGHTGBM]
    dates = np.sort(losses["date"].unique())
    n_dates = len(dates)
    counts = boot.resample_counts(boot.resample_dates(n_dates, n_boot, seed), n_dates)
    date_index = {d: i for i, d in enumerate(dates)}
    rows = []
    for (axis, group, target), sub in losses.groupby(["axis", "group", "target"], observed=True):
        pos = sub["date"].map(date_index).to_numpy()
        n_vec = np.zeros(n_dates)
        n_vec[pos] = sub["n"].to_numpy(dtype="float64")
        sse_lookup = np.zeros(n_dates)
        sae_lookup = np.zeros(n_dates)
        sse_lookup[pos] = sub["sse__lookup"].to_numpy(dtype="float64")
        sae_lookup[pos] = sub["sae__lookup"].to_numpy(dtype="float64")
        sse_lgb = np.zeros(n_dates)
        sae_lgb = np.zeros(n_dates)
        sse_lgb[pos] = sub[f"sse__{LIGHTGBM}"].to_numpy(dtype="float64")
        sae_lgb[pos] = sub[f"sae__{LIGHTGBM}"].to_numpy(dtype="float64")
        boot_rmse_base = boot.weighted_rmse(counts, sse_lookup, n_vec)
        boot_mae_base = boot.weighted_mae(counts, sae_lookup, n_vec)
        boot_rmse_lgb = boot.improvement_pct(
            boot_rmse_base, boot.weighted_rmse(counts, sse_lgb, n_vec)
        )
        boot_mae_lgb = boot.improvement_pct(
            boot_mae_base, boot.weighted_mae(counts, sae_lgb, n_vec)
        )
        full = np.ones((1, n_dates))
        point_rmse_lgb = boot.improvement_pct(
            boot.weighted_rmse(full, sse_lookup, n_vec), boot.weighted_rmse(full, sse_lgb, n_vec)
        )[0]
        point_mae_lgb = boot.improvement_pct(
            boot.weighted_mae(full, sae_lookup, n_vec), boot.weighted_mae(full, sae_lgb, n_vec)
        )[0]
        ok = n_vec > 0
        for name in candidates:
            sse = np.zeros(n_dates)
            sae = np.zeros(n_dates)
            sse[pos] = sub[f"sse__{name}"].to_numpy(dtype="float64")
            sae[pos] = sub[f"sae__{name}"].to_numpy(dtype="float64")
            boot_rmse = boot.improvement_pct(boot_rmse_base, boot.weighted_rmse(counts, sse, n_vec))
            boot_mae = boot.improvement_pct(boot_mae_base, boot.weighted_mae(counts, sae, n_vec))
            # diff = 개선율_계열 − 개선율_lightgbm. 양수 = 계열이 더 낫다. 판정 기준(계획 §0)의
            # "하한 > −2%p"는 이 부호 기준이다 — 최악의 재표본에서도 계열이 LightGBM보다 2%p 넘게
            # 나쁘지 않아야 대체를 검토한다.
            diff_rmse = boot_rmse - boot_rmse_lgb
            diff_mae = boot_mae - boot_mae_lgb
            point_rmse = boot.improvement_pct(
                boot.weighted_rmse(full, sse_lookup, n_vec), boot.weighted_rmse(full, sse, n_vec)
            )[0]
            point_mae = boot.improvement_pct(
                boot.weighted_mae(full, sae_lookup, n_vec), boot.weighted_mae(full, sae, n_vec)
            )[0]
            rmse_lo, rmse_hi = boot.percentile_ci(diff_rmse)
            mae_lo, mae_hi = boot.percentile_ci(diff_mae)
            # DM: 계열 SSE − LightGBM SSE(날짜별). 음수 = 계열의 오차가 더 작다(계열이 낫다).
            dm = boot.diebold_mariano((sse[ok] - sse_lgb[ok]) / n_vec[ok])
            rows.append(
                {
                    "series": name,
                    "axis": axis,
                    "group": group,
                    "target": target,
                    "point_diff_RMSE_%p(계열-LightGBM)": point_rmse - point_rmse_lgb,
                    "diff_RMSE_CI_low": rmse_lo,
                    "diff_RMSE_CI_high": rmse_hi,
                    "point_diff_MAE_%p(계열-LightGBM)": point_mae - point_mae_lgb,
                    "diff_MAE_CI_low": mae_lo,
                    "diff_MAE_CI_high": mae_hi,
                    "대체_가능(RMSE·MAE 하한>-2%p)": bool(rmse_lo > -2.0 and mae_lo > -2.0),
                    "DM_stat(계열-LightGBM)": dm["stat"],
                    "DM_p": dm["p"],
                }
            )
    return pd.DataFrame(rows)


# ── 표 C: 재현율 ──
def table_c(table_a_df: pd.DataFrame) -> pd.DataFrame:
    tot = table_a_df[table_a_df["axis"] == "전체"].copy()
    lgb = tot[tot["series"] == LIGHTGBM].set_index("target")
    rows = []
    for name in tot["series"].unique():
        if name == LIGHTGBM:
            continue
        sub = tot[tot["series"] == name].set_index("target")
        for target in TARGETS:
            if target not in sub.index or target not in lgb.index:
                continue
            rmse_ratio = sub.loc[target, "RMSE_개선율_%"] / lgb.loc[target, "RMSE_개선율_%"] * 100
            mae_ratio = sub.loc[target, "MAE_개선율_%"] / lgb.loc[target, "MAE_개선율_%"] * 100
            rows.append(
                {
                    "series": name,
                    "target": target,
                    "개선율_계열_RMSE_%": sub.loc[target, "RMSE_개선율_%"],
                    "개선율_lightgbm_RMSE_%": lgb.loc[target, "RMSE_개선율_%"],
                    "재현율_RMSE_%": round(float(rmse_ratio), 1),
                    "개선율_계열_MAE_%": sub.loc[target, "MAE_개선율_%"],
                    "개선율_lightgbm_MAE_%": lgb.loc[target, "MAE_개선율_%"],
                    "재현율_MAE_%": round(float(mae_ratio), 1),
                }
            )
    return pd.DataFrame(rows)


# ── 표 D: 92 표본 점추정 ──
def table_d(
    common: pd.DataFrame, series_names: list[str], sample_stations, sample_dates
) -> pd.DataFrame:
    sample = common[
        common["station_no"].isin(sample_stations) & common["date"].isin(sample_dates)
    ].reset_index(drop=True)
    rows = []
    for target in TARGETS:
        truth = sample[target].to_numpy(dtype="float64")
        base_err = sample[f"lookup__{target}"].to_numpy(dtype="float64") - truth
        base_rmse = float(np.sqrt(np.mean(base_err**2)))
        base_mae = float(np.mean(np.abs(base_err)))
        rows.append(
            {
                "series": "lookup",
                "target": target,
                "n": len(sample),
                "RMSE": round(base_rmse, 2),
                "MAE": round(base_mae, 2),
                "RMSE_개선율_%": 0.0,
                "MAE_개선율_%": 0.0,
            }
        )
        for name in series_names:
            err = sample[f"{name}__{target}"].to_numpy(dtype="float64") - truth
            rmse = float(np.sqrt(np.mean(err**2)))
            mae = float(np.mean(np.abs(err)))
            rows.append(
                {
                    "series": name,
                    "target": target,
                    "n": len(sample),
                    "RMSE": round(rmse, 2),
                    "MAE": round(mae, 2),
                    "RMSE_개선율_%": (
                        round((1 - rmse / base_rmse) * 100, 2) if base_rmse else np.nan
                    ),
                    "MAE_개선율_%": round((1 - mae / base_mae) * 100, 2) if base_mae else np.nan,
                }
            )
    return pd.DataFrame(rows)


def to_markdown(frame: pd.DataFrame) -> str:
    cols = [str(c) for c in frame.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for _, r in frame.iterrows():
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in r.tolist()) + " |")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, pd.DataFrame]:
    t0 = time.time()
    derived = load_derived_slim(columns=DERIVED_COLS)
    test = derived[derived["date"] >= SPLIT_DATE].reset_index(drop=True)
    names = ["lookup", *[s for s in CANDIDATE_SERIES]]
    frames = load_predictions(names)
    available = [s for s in CANDIDATE_SERIES if s in frames]
    if "lookup" not in frames:
        raise SystemExit("lookup 예측이 없다 — predict_all.py --series lookup을 먼저 실행할 것.")
    common, own_coverage, common_ratio = build_common_frame(test, frames)
    print(f"[준비] 공통 프레임 {len(common):,}행 · {time.time() - t0:.0f}s", flush=True)

    losses = daily_losses_multi(common, ["lookup", *available])
    a = table_a(losses, available, args.n_boot, args.seed)
    b = table_b(losses, [s for s in available if s != LIGHTGBM], args.n_boot, args.seed)
    c = table_c(a)

    _, test_raw = time_split(load_panel(with_events=True))
    sample_stations, sample_dates = compare_families.pick_sample(test_raw, 50, 30, seed=0)
    d = table_d(common, available, sample_stations, sample_dates)

    tables = {
        "A_lookup_대비_개선율_CI": a,
        "B_lightgbm_쌍차이": b,
        "C_재현율": c,
        "D_92표본_점추정": d,
    }
    for title, tbl in tables.items():
        print(f"\n### {title}\n{tbl.round(3).to_string(index=False)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for title, tbl in tables.items():
        tbl.to_parquet(OUT_DIR / f"eval_table_{title}.parquet", index=False)
    if args.out:
        chunks = [
            f"공통 행 비율: {common_ratio * 100:.2f}%\n\n계열별 자기 유효행: {own_coverage}\n"
        ]
        for title, tbl in tables.items():
            chunks.append(f"### {title}\n\n{to_markdown(tbl.round(3))}\n")
        Path(args.out).write_text("\n".join(chunks), encoding="utf-8")
        print(f"[저장] {args.out}", flush=True)
    print(f"[완료] {time.time() - t0:.0f}s", flush=True)
    return tables


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    run(args)


if __name__ == "__main__":
    main(sys.argv[1:])
