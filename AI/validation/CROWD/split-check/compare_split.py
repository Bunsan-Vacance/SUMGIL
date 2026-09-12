"""93번 — 전역 모델 vs 그룹별(호선·6호선 분리·군집) 모델, 그리고 요일유형 시차 세트 B′ 비교.

같은 분할(2024 학습 / 2025 평가)·같은 피처·같은 하이퍼파라미터(90 기본)에서 **fit만** 나눈다. 파생 컬럼은
전역으로 한 번 만들어 캐시에서 읽으므로(`load_or_build_derived`) 그룹 모델도 환승 노드 등 다른 호선 정보를
피처로 갖는다 — "호선 독립 모델"이 아니라 "호선별로 fit한 모델"이다.

실행 단위(`--runs`, 쉼표 구분; 기본 전부)
- `global`        — 전역 단일 모델(90 배포 세트). 기준.
- `line`          — 호선별 8모델.
- `line6`         — 6호선만 분리(6호선 / 나머지 전역).
- `cluster`       — 학습 구간 승차 프로파일 K-means(`--k`) 군집별 모델.
- `cluster_feat`  — 전역 모델 + `cluster_id` 피처.
- `sameday`       — 전역 모델, 세트 `festival_selflag_sameday_d7_resid`(B′: 전날 → 같은 요일유형 직전 날).
- `d1sd`          — 전역 모델, 세트 `festival_selflag_d1sd_d7_resid`(전날·같은 유형 직전 날·1주 전 셋 다).
- `global_no150`, `line1_no150` — 1호선 서울역(150) 제외 참고 실험(141: 2025 집계 정의 변화 의심).

지표: 전체·호선별·요일유형별 RMSE/MAE(lookup 대비 개선율). 결과는 long parquet(`--save-results`)로 남겨
그림·노트북이 읽는다. 판정 기준은 계획 파일에 고정: 분할은 전체 RMSE·MAE 둘 다 개선 + 어느 호선도 2%p 이상
악화 없음(1%p 미만 개선이면 나누지 않음); B′는 일요일·휴일 슬라이스 +3%p 이상 + 평일 비악화.

실행:
    cd AI
    python validation/CROWD/split-check/compare_split.py --save-results data/CROWD/interim/validation/split_results.parquet
    python validation/CROWD/split-check/compare_split.py --runs global,line6,sameday
예상: 파생 캐시 재생성(DERIVED_VERSION 2) 1회 ~1분, fit 하나 3~10초, 전체 8실행 ≈ 3~4분.
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
for p in (str(AI_ROOT), str(AI_ROOT / "validation" / "CROWD" / "baseline-check")):
    if p not in sys.path:
        sys.path.insert(0, p)

from baseline import regression_metrics
from evaluate_final import to_markdown

from app.CROWD.pipeline.dataset import load_or_build_derived, load_panel, time_split
from app.CROWD.pipeline.features import FEATURE_SETS, SLOT_ORDER, build_matrix
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline
from app.CROWD.pipeline.train import train_models
from DATA_ENGINE.eda.analysis_crowd import cluster_station_profiles

DEPLOY_SET = "festival_selflag_d1d7_resid"
SAMEDAY_SET = "festival_selflag_sameday_d7_resid"
D1SD_SET = "festival_selflag_d1sd_d7_resid"
ALL_RUNS = [
    "global",
    "line",
    "line6",
    "cluster",
    "cluster_feat",
    "sameday",
    "d1sd",
    "global_no150",
    "line1_no150",
]
SEOUL_LINE1 = 150


def _pct(base: float, val: float) -> float:
    return round((1 - val / base) * 100, 2) if base else np.nan


# ── 군집 ──
def cluster_labels(train: pd.DataFrame, k: int) -> pd.Series:
    """2024 학습 구간 평일 승차 프로파일(역 × 20슬롯 평균) → K-means 군집 라벨. 평가 구간은 쓰지 않는다."""
    prof = (
        train[train["day_type"] == "평일"]
        .pivot_table(index="station_no", columns="time_slot", values="boarding", aggfunc="mean")
        .reindex(columns=SLOT_ORDER)
    )
    labels = cluster_station_profiles(prof, n_clusters=k)
    return labels.rename("cluster_id")


# ── 한 실행 ──
def fit_predict(
    train: pd.DataFrame,
    test: pd.DataFrame,
    lookup: DayTypeLookupBaseline,
    feature_set: str,
    group_col: str | None,
) -> dict[str, np.ndarray]:
    """그룹별(또는 전역) fit → 평가 행 순서대로 이어 붙인 최종 예측(lookup + 잔차)."""
    models = train_models(train, lookup, feature_set, group_col=group_col)
    X = build_matrix(test, feature_set)
    lk = lookup.predict(test)
    out = {}
    for t in TARGETS:
        resid = np.full(len(test), np.nan)
        if group_col is None:
            resid[:] = models[t]["__all__"].predict(X)
        else:
            keys = test[group_col].astype(str).to_numpy()
            for gkey, booster in models[t].items():
                mask = keys == gkey
                if mask.any():
                    resid[mask] = booster.predict(X[mask])
            # 학습에 없던 그룹(평가에만 있는 군집 등)은 전역 대체가 없으므로 잔차 0 = lookup
            resid = np.nan_to_num(resid, nan=0.0)
        out[t] = lk[t].to_numpy() + resid
    return out


def metrics_rows(
    test: pd.DataFrame, lookup_pred: pd.DataFrame, preds: dict, run: str
) -> list[dict]:
    rows = []
    axes = {
        "전체": pd.Series("전체", index=test.index),
        "line": test["line"],
        "day_type": test["day_type"],
    }
    for axis, series in axes.items():
        for g, idx in series.groupby(series, observed=True).groups.items():
            for t in TARGETS:
                b = regression_metrics(test.loc[idx, t], lookup_pred.loc[idx, t])
                m = regression_metrics(
                    test.loc[idx, t], pd.Series(preds[t][test.index.get_indexer(idx)], index=idx)
                )
                rows.append(
                    {
                        "run": run,
                        "axis": axis,
                        "group": str(g),
                        "target": t,
                        "n": len(idx),
                        "base_rmse": round(b["rmse"], 2),
                        "rmse": round(m["rmse"], 2),
                        "mae": round(m["mae"], 2),
                        "base_mae": round(b["mae"], 2),
                        "RMSE_개선율_%": _pct(b["rmse"], m["rmse"]),
                        "MAE_개선율_%": _pct(b["mae"], m["mae"]),
                    }
                )
    return rows


def run_all(runs: list[str], k: int) -> pd.DataFrame:
    t0 = time.time()
    panel = load_panel(with_events=True)
    train_raw, _ = time_split(panel)
    lookup = DayTypeLookupBaseline().fit(train_raw)
    derived = load_or_build_derived(panel, lookup)
    train, test = time_split(derived)
    test = test.reset_index(drop=True)
    lookup_pred = lookup.predict(test)
    print(f"[준비] 학습 {len(train):,} · 평가 {len(test):,} · {time.time() - t0:.0f}s", flush=True)

    if any(r.startswith("cluster") for r in runs):
        labels = cluster_labels(train, k)
        train = train.merge(labels, left_on="station_no", right_index=True, how="left")
        test = test.merge(labels, left_on="station_no", right_index=True, how="left")
        print(f"[군집] k={k}: {labels.value_counts().sort_index().to_dict()}", flush=True)
        FEATURE_SETS["__deploy_plus_cluster__"] = FEATURE_SETS[DEPLOY_SET] + ["cluster_id"]
    for df in (train, test):
        df["grp6"] = np.where(df["line"] == "6호선", "6호선", "기타")
        df["grp1"] = np.where(df["line"] == "1호선", "1호선", "기타")

    spec = {
        "global": (DEPLOY_SET, None, None),
        "line": (DEPLOY_SET, "line", None),
        "line6": (DEPLOY_SET, "grp6", None),
        "cluster": (DEPLOY_SET, "cluster_id", None),
        "cluster_feat": ("__deploy_plus_cluster__", None, None),
        "sameday": (SAMEDAY_SET, None, None),
        "d1sd": (D1SD_SET, None, None),
        "global_no150": (DEPLOY_SET, None, SEOUL_LINE1),
        "line1_no150": (DEPLOY_SET, "grp1", SEOUL_LINE1),
    }
    rows: list[dict] = []
    for run in runs:
        fs, gcol, drop = spec[run]
        tr, te, lp = train, test, lookup_pred
        if drop is not None:
            tr = train[train["station_no"] != drop]
            keep = test["station_no"] != drop
            te, lp = test[keep], lookup_pred[keep]
        t1 = time.time()
        preds = fit_predict(tr, te, lookup, fs, gcol)
        rows += metrics_rows(te, lp, preds, run)
        tot = [r for r in rows if r["run"] == run and r["axis"] == "전체"]
        print(
            f"[{run}] {time.time() - t1:.0f}s · RMSE 개선율 승차 {tot[0]['RMSE_개선율_%']} / 하차 {tot[1]['RMSE_개선율_%']}"
            f" · MAE {tot[0]['MAE_개선율_%']} / {tot[1]['MAE_개선율_%']}",
            flush=True,
        )
    print(f"[총 {time.time() - t0:.0f}s]")
    return pd.DataFrame(rows)


# ── 요약 ──
def summarize(res: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    out = []
    tot = res[res["axis"] == "전체"].pivot_table(
        index="run", columns="target", values=["RMSE_개선율_%", "MAE_개선율_%"]
    )
    tot.columns = [f"{m}_{t}" for m, t in tot.columns]
    out.append(("전체 — 실행별 lookup 대비 개선율(%)", tot.reset_index().round(2)))
    for axis, title in (
        ("line", "호선별 RMSE 개선율(승차)"),
        ("day_type", "요일유형별 RMSE 개선율(승차)"),
    ):
        piv = res[(res["axis"] == axis) & (res["target"] == "boarding")].pivot_table(
            index="group", columns="run", values="RMSE_개선율_%"
        )
        if "global" in piv.columns:
            for c in piv.columns:
                if c != "global":
                    piv[f"Δ{c}"] = (piv[c] - piv["global"]).round(2)
        out.append((title, piv.reset_index().round(2)))
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--runs", default=",".join(ALL_RUNS))
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--save-results", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    runs = [r for r in args.runs.split(",") if r]
    unknown = set(runs) - set(ALL_RUNS)
    if unknown:
        raise SystemExit(f"알 수 없는 실행: {unknown} (가능: {ALL_RUNS})")
    res = run_all(runs, args.k)
    if args.save_results:
        Path(args.save_results).parent.mkdir(parents=True, exist_ok=True)
        res.assign(k=args.k).to_parquet(args.save_results, index=False)
    chunks = []
    for title, tbl in summarize(res):
        print(f"\n### {title}\n{tbl.to_string(index=False)}")
        chunks.append(f"### {title}\n\n{to_markdown(tbl)}\n")
    if args.out:
        Path(args.out).write_text("\n".join(chunks), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
