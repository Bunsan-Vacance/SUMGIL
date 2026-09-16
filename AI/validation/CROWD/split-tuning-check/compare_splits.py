"""모델 분할 전략 × 하이퍼파라미터 × 계열 격자 — 93이 남긴 미해결을 닫는다.

## 용어(문서 전체에서 이대로 쓴다)

| 개념 | 이 저장소의 명칭 | 학술 표현 |
| --- | --- | --- |
| 학습 단위를 쪼갬(호선·군집·시리즈) | **모델 분할** / 그룹별 학습 | local / per-group(stratified) model |
| 쪼개지 않은 하나 | **전역 모델** | global(pooled, cross-learning) model |
| 2024/2025 경계 | **데이터 분할**(시간 분할) | temporal split |

## 왜

93(`validation/CROWD/split-check/`)은 전역 대 호선별·6호선분리·군집별을 비교해 **전역 유지**로 판정했다.
그런데 분할 모델에도 **전역에서 고른 파라미터(num_leaves 31 · 300그루)를 그대로** 썼다. 호선별로 나누면
학습 행이 1/8로 줄어드니 같은 용량은 과한 쪽이고, 그래서 6호선 −2.98%p가 "분할이 나쁘다"인지
"분할 + 과용량이 나쁘다"인지 구분되지 않는다 — 93 RESULTS 미해결의 마지막 줄이 정확히 이 문제다.

또 93은 LightGBM만 봤다. 145 통계 파트에서 **선형 계열은 분할이 실제로 이득**이었다
(`ols_pooled` +21.27 → `ols_series` +24.06, 역×시간대별 5,460모델). 그래서 "분할이 효과적인가"는
계열에 따라 답이 다를 수 있고, 그 사다리(전역 → 호선별 → 군집별 → 시리즈별)를 같은 축에서 재야 한다.

## 격자

- **분할(그룹 키)**: `global`(없음) · `line`(호선 8) · `cluster`(93과 같은 K-means k=4) · `line6`(6호선만 분리)
- **파라미터**: `p31_300`(90 채택) · `p15_150`(분할용 축소) · `p63_600`(증설) — 분할과 용량을 분리해서 본다
- **계열**: LightGBM은 위 격자 전부. 선형(잔차 OLS-AR)은 분할 사다리 4단(전역·호선별·군집별·시리즈별)
- 피처 세트는 **현 배포 세트 `festival_selflag_d1sd_d7_resid`**다(93은 그 이전 `d1d7`) — 93 표와 절대값을
  직접 비교하지 않고, 이 실행 안의 전역 대비 차이로만 읽는다.
- 군집은 93의 설계 그대로(2024 평일 승차 프로파일 z-score → K-means k=4, 평가 구간 미사용).

## 무엇을 하지 않나

GRU 호선별 재학습(8회)은 범위 밖 — GRU는 145 판정에서 결손·전무 구간 전용이라 `full`에서의 분할 이득이
채택을 바꾸지 않는다. k 탐색(3·5)도 93이 "이득 +0.5%p 이하"로 생략한 것을 유지한다.

실행(폴더명에 하이픈이 있어 파일 경로로 돈다):
    cd AI
    python validation/CROWD/split-tuning-check/compare_splits.py --smoke          # 격자 축소(3분)
    python validation/CROWD/split-tuning-check/compare_splits.py --out RESULTS_tables.md
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


def _load_sibling(rel_path: str, name: str):
    """다른 하이픈 폴더의 검증 스크립트를 파일 경로로 재사용한다(수정 금지, import만)."""
    spec = importlib.util.spec_from_file_location(name, AI_ROOT / rel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


compare_split = _load_sibling("validation/CROWD/split-check/compare_split.py", "split_compare_93")
stat_eval = _load_sibling("validation/CROWD/stat-model-check/evaluate.py", "split_stat_eval")
stat_models = _load_sibling("validation/CROWD/stat-model-check/stat_models.py", "split_stat_models")

from app.CROWD.pipeline.dataset import (
    CROWD_INTERIM,
    load_or_build_derived,
    load_panel,
    time_split,
)
from app.CROWD.pipeline.features import FEATURE_SETS, build_matrix
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline
from app.CROWD.pipeline.train import train_models

DEPLOY_SET = "festival_selflag_d1sd_d7_resid"
OUT_DIR = CROWD_INTERIM / "validation" / "split_tuning_check"
BASELINE = "global"

# 그룹 키 — None이면 전역. `grp6`는 run_all과 같은 방식으로 여기서 만든다.
SPLITS: dict[str, str | None] = {
    "global": None,
    "line": "line",
    "cluster": "cluster_id",
    "line6": "grp6",
}
# 90 그리드는 전역에서만 돌았다(6조합, 차이 0.4%p 안). 분할은 데이터가 1/8~1/4로 줄므로
# **축소(p15_150)**가 본래 후보이고, 증설(p63_600)은 반대 방향 대조군이다.
PARAM_GRID: dict[str, dict] = {
    "p31_300": {},  # 90 채택값 = train.DEFAULT_PARAMS
    "p15_150": {"num_leaves": 15, "n_estimators": 150},
    "p63_600": {"num_leaves": 63, "n_estimators": 600},
}
# 선형 계열의 분할 사다리 — 그룹 키 목록(None이면 전역)
LINEAR_LADDER: dict[str, list[str] | None] = {
    "linear_global": None,
    "linear_line": ["line"],
    "linear_cluster": ["cluster_id"],
    "linear_series": ["station_no", "time_slot"],
}


# ── 준비 ──
def prepare(k: int) -> dict:
    t0 = time.time()
    panel = load_panel(with_events=True)
    train_raw, _ = time_split(panel)
    lookup = DayTypeLookupBaseline().fit(train_raw)
    derived = load_or_build_derived(panel, lookup)
    train, test = time_split(derived)
    train, test = train.reset_index(drop=True), test.reset_index(drop=True)
    lookup_pred = lookup.predict(test)

    labels = compare_split.cluster_labels(train, k)  # 93과 같은 군집 설계
    train = train.merge(labels, left_on="station_no", right_index=True, how="left")
    test = test.merge(labels, left_on="station_no", right_index=True, how="left")
    for df in (train, test):
        df["grp6"] = np.where(df["line"] == "6호선", "6호선", "기타")
    print(
        f"[준비] 학습 {len(train):,} · 평가 {len(test):,} · 군집 k={k} "
        f"{labels.value_counts().sort_index().to_dict()} · {time.time() - t0:.0f}s",
        flush=True,
    )
    return {"lookup": lookup, "train": train, "test": test, "lookup_pred": lookup_pred}


# ── LightGBM: 분할 × 파라미터 ──
def lgb_predict(data: dict, group_col: str | None, params: dict) -> dict[str, np.ndarray]:
    """그룹별(또는 전역) fit → 평가 행 순서의 최종 예측. 93 `fit_predict`에 파라미터 축을 더한 것."""
    train, test, lookup = data["train"], data["test"], data["lookup"]
    models = train_models(train, lookup, DEPLOY_SET, params or None, group_col)
    X = build_matrix(test, DEPLOY_SET)
    lk = data["lookup_pred"]
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
            # 학습에 없던 그룹은 잔차 0 = lookup(채우지 않는다는 뜻 — 93과 같은 처리)
            resid = np.nan_to_num(resid, nan=0.0)
        out[t] = lk[t].to_numpy() + resid
    return out


# ── 선형(잔차 OLS-AR): 분할 사다리 ──
def _feat_cols(target: str) -> list[str]:
    return [f"lag1d_{target}_resid", f"lagsd_{target}_resid", f"lag7d_{target}_resid"]


def linear_predict(
    data: dict, group_keys: list[str] | None, min_valid_rows: int = 30
) -> tuple[dict[str, np.ndarray], dict]:
    """잔차 = 절편 + β·[lag1d, lagsd, lag7d]를 그룹마다 따로 적합한다.

    `group_keys=None`이면 145의 `ols_pooled`, `["station_no","time_slot"]`이면 `ols_series`와 같다 —
    그 사이(호선별·군집별)를 채우는 것이 이 함수의 목적이다. 유효행이 모자란 그룹은 NaN으로 둔다
    (원칙 8 — 값을 지어내지 않는다). 그 행은 뒤에서 공통 행 계산에 걸려 빠진다.
    """
    train, test, lk = data["train"], data["test"], data["lookup_pred"]
    out = {t: np.full(len(test), np.nan) for t in TARGETS}
    diag = {"n_groups": 0, "n_fitted": {t: 0 for t in TARGETS}}
    if group_keys is None:
        for t in TARGETS:
            cols = _feat_cols(t)
            coef = stat_models.fit_ols(
                train[cols].to_numpy(), train[f"{t}_resid"].to_numpy(), min_valid_rows
            )
            out[t] = lk[t].to_numpy() + stat_models.predict_ols(test[cols].to_numpy(), coef)
            diag["n_fitted"][t] = int(coef is not None)
        diag["n_groups"] = 1
        return out, diag

    train_groups = train.groupby(group_keys, observed=True).indices
    test_groups = test.groupby(group_keys, observed=True).indices
    diag["n_groups"] = len(test_groups)
    for key, te_idx in test_groups.items():
        te_idx = np.asarray(te_idx)
        tr_idx = train_groups.get(key)
        tr = train.iloc[np.asarray(tr_idx)] if tr_idx is not None else None
        te = test.iloc[te_idx]
        for t in TARGETS:
            cols = _feat_cols(t)
            coef = None
            if tr is not None:
                coef = stat_models.fit_ols(
                    tr[cols].to_numpy(), tr[f"{t}_resid"].to_numpy(), min_valid_rows
                )
            if coef is not None:
                diag["n_fitted"][t] += 1
            out[t][te_idx] = lk[t].to_numpy()[te_idx] + stat_models.predict_ols(
                te[cols].to_numpy(), coef
            )
    return out, diag


# ── 쌍 부트스트랩(전역 대비) ──
def paired_ci(data: dict, preds: dict[str, dict[str, np.ndarray]], n_boot: int, seed: int):
    """전역 대비 각 분할의 개선율 차이 CI. 142 블록 재표본을 145 표 조립기로 돌린다.

    `stat_eval.table_b`는 짝을 맞출 기준 계열 이름을 모듈 상수로 들고 있어, 여기서 그 값을
    `global`로 바꿔 쓴다(복붙 대신 재사용). 반환 부호는 `분할 − 전역`이고 양수면 분할이 낫다.
    """
    test, lk = data["test"], data["lookup_pred"]
    frame = test[["date", "station_no", "time_slot", "line", "day_type", *TARGETS]].copy()
    for t in TARGETS:
        frame[f"lookup__{t}"] = lk[t].to_numpy(dtype="float64")
    names = ["lookup"]
    finite = np.ones(len(test), dtype=bool)
    for name, pr in preds.items():
        for t in TARGETS:
            frame[f"{name}__{t}"] = pr[t]
            finite &= np.isfinite(pr[t])
        names.append(name)
    for t in TARGETS:
        finite &= np.isfinite(frame[f"lookup__{t}"].to_numpy(dtype="float64"))
    print(
        f"[공통 행] {int(finite.sum()):,} / {len(frame):,} ({finite.mean() * 100:.2f}%)", flush=True
    )
    frame = frame[finite].reset_index(drop=True)

    losses = stat_eval.daily_losses_multi(frame, names)
    candidates = [n for n in names if n != "lookup"]
    a = stat_eval.table_a(losses, candidates, n_boot, seed)
    keep = stat_eval.LIGHTGBM
    stat_eval.LIGHTGBM = BASELINE
    try:
        b = stat_eval.table_b(losses, [n for n in candidates if n != BASELINE], n_boot, seed)
    finally:
        stat_eval.LIGHTGBM = keep
    return a, b


# ── 실행 ──
def run(args) -> dict[str, pd.DataFrame]:
    t0 = time.time()
    data = prepare(args.k)
    rows: list[dict] = []
    ci_preds: dict[str, dict[str, np.ndarray]] = {}

    for pname in args.params:
        for sname in args.splits:
            t1 = time.time()
            preds = lgb_predict(data, SPLITS[sname], PARAM_GRID[pname])
            run_name = f"{sname}|{pname}"
            chunk = compare_split.metrics_rows(data["test"], data["lookup_pred"], preds, run_name)
            for r in chunk:
                r["계열"], r["분할"], r["파라미터"] = "lightgbm", sname, pname
            rows += chunk
            tot = [r for r in chunk if r["axis"] == "전체"]
            print(
                f"[{run_name}] {time.time() - t1:.0f}s · RMSE 개선율 승 {tot[0]['RMSE_개선율_%']}"
                f" / 하 {tot[1]['RMSE_개선율_%']} · MAE {tot[0]['MAE_개선율_%']} / {tot[1]['MAE_개선율_%']}",
                flush=True,
            )
            if pname == args.ci_params:  # CI는 한 파라미터 축에서만(전부 하면 부트스트랩이 길다)
                ci_preds[sname if sname == BASELINE else f"{sname}"] = preds

    for lname, keys in LINEAR_LADDER.items():
        if lname not in args.linear:
            continue
        t1 = time.time()
        preds, diag = linear_predict(data, keys)
        chunk = compare_split.metrics_rows(data["test"], data["lookup_pred"], preds, lname)
        for r in chunk:
            r["계열"], r["분할"], r["파라미터"] = "linear", lname.removeprefix("linear_"), "—"
        rows += chunk
        tot = [r for r in chunk if r["axis"] == "전체"]
        print(
            f"[{lname}] {time.time() - t1:.0f}s · 그룹 {diag['n_groups']:,} · "
            f"RMSE 개선율 승 {tot[0]['RMSE_개선율_%']} / 하 {tot[1]['RMSE_개선율_%']}",
            flush=True,
        )
        ci_preds[lname] = preds

    res = pd.DataFrame(rows)
    tables = {"A_격자": res}
    if not args.no_ci and len(ci_preds) > 1:
        a, b = paired_ci(data, ci_preds, args.n_boot, args.seed)
        tables["B_lookup_대비_CI"] = a
        tables["C_전역_대비_쌍차이"] = b

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for title, tbl in tables.items():
        tbl.to_parquet(OUT_DIR / f"split_tuning_{title}.parquet", index=False)
    tot = res[res["axis"] == "전체"].pivot_table(
        index=["계열", "분할"], columns="파라미터", values="RMSE_개선율_%", aggfunc="first"
    )
    print(
        f"\n### 전체 축 RMSE 개선율(승·하 평균 아님, target별 행)\n{res[res.axis == '전체'].to_string(index=False)}"
    )
    print(f"\n### 격자 요약(전체 축)\n{tot.round(2).to_string()}")
    if "C_전역_대비_쌍차이" in tables:
        c = tables["C_전역_대비_쌍차이"]
        print(
            f"\n### 전역 대비 쌍차이(전체 축)\n{c[c.axis == '전체'].round(2).to_string(index=False)}"
        )
    if args.out:
        chunks = [
            f"피처 세트 `{DEPLOY_SET}` · 군집 k={args.k} · 부트스트랩 {args.n_boot}회(seed {args.seed})\n"
        ]
        for title, tbl in tables.items():
            chunks.append(f"### {title}\n\n{stat_eval.to_markdown(tbl.round(3))}\n")
        Path(args.out).write_text("\n".join(chunks), encoding="utf-8")
        print(f"[저장] {args.out}", flush=True)
    print(f"[완료] {time.time() - t0:.0f}s", flush=True)
    return tables


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--splits", nargs="+", default=list(SPLITS), choices=list(SPLITS))
    ap.add_argument("--params", nargs="+", default=list(PARAM_GRID), choices=list(PARAM_GRID))
    ap.add_argument("--linear", nargs="+", default=list(LINEAR_LADDER), choices=list(LINEAR_LADDER))
    ap.add_argument("--k", type=int, default=4, help="군집 수(93과 같은 k=4가 기본)")
    ap.add_argument("--ci-params", default="p31_300", help="쌍 부트스트랩을 낼 파라미터 축")
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-ci", action="store_true")
    ap.add_argument(
        "--smoke", action="store_true", help="격자 축소 — 분할 2종·파라미터 1종·CI 생략"
    )
    ap.add_argument("--out", default=None, help="표를 마크다운으로 저장할 경로")
    args = ap.parse_args(argv)
    if args.smoke:
        args.splits = ["global", "line"]
        args.params = ["p31_300"]
        args.linear = ["linear_global", "linear_line"]
        args.no_ci = True
    run(args)


if __name__ == "__main__":
    main(sys.argv[1:])
