"""145 후속 — 기상 × 이벤트 × 군집정의를 더한 분할 × 용량 × 세트 격자(93의 메커니즘 재현 확인).

## 왜

93(`validation/CROWD/split-check/`)은 세트 `festival_selflag_d1sd_d7_resid`(이벤트 O, **기상 X**)
하나로 전역 대 호선별·군집별 분할을 비교해 **분할 이득 없음**으로 기각했다. 그런데 군집별 모델이
전역보다 나아진다고 보고하는 논문들의 메커니즘은 "군집마다 기상 민감도가 반대라서 전역에서는
계수가 상쇄되고 군집별로 나눠야 살아난다"다 — 93은 그 조건(기상 피처) 자체를 만들지 않은 채
분할만 비교했다. 145 split-tuning(`compare_splits.py`)에서는 분할과 모델 용량이 상호작용함
(용량을 줄이면 호선별 부호가 뒤집힘)도 확인됐으므로 용량도 축에 있어야 한다.

## 답해야 하는 질문

- **Q1** 기상을 넣으면 분할의 부호가 바뀌는가?(전역에서는 무익해도 군집별에서는 유익한가)
- **Q2** 이벤트를 빼면 분할 이득이 사라지는가?(분할이 상호작용하는 상대가 이벤트인가)
- **Q3** 군집 정의를 "수준"(93 방식, 행 z-score)에서 "모양"(행 합 정규화, z-score 없음)으로
  바꾸면 결과가 달라지는가?

## 대상 호선 — 1·2·6호선만

1호선은 선형 모형이 LightGBM을 +13~17%p 이기는 노선(145 계열 비교), 6호선은 93에서 분할 시
−3.0%p로 가장 나빴던 노선, 2호선은 최대 규모 — 세 노선이 "분할이 지는 사례"와 "분할이 이길
후보"를 동시에 담는다.

## 격자 — 3 세트 × 4 분할 × 2 용량 = 24 실행

- **세트**: `fs_deploy`(93 조건 그대로) · `fs_deploy_weather`(+기상 5열) · `fs_noevent`(이벤트
  5열 제거). `app.CROWD.pipeline.features.FEATURE_SETS`에 런타임에만 등록한다 — 검증 전용
  세트라 `features.py` 파일 자체는 건드리지 않는다.
- **분할**: `global`(없음) · `line` · `cluster_level`(93 방식 그대로, 행 z-score) ·
  `cluster_shape`(행 합 정규화, z-score 없이 K-means 직접). 대상 3개 호선의 역만으로 군집화한다.
  **주의**: `cluster_level`이 쓰는 `cluster_station_profiles`는 행 단위 z-score를 쓰는데, z-score는
  행에 대한 어떤 양의 스칼라 배율에도 불변이다. 그래서 "행 합으로 정규화한 뒤 다시 z-score"를
  하면 `cluster_level`과 수학적으로 완전히 같은 군집이 나와 비교가 무의미해진다 — 그래서
  `cluster_shape`는 z-score를 건너뛰고 정규화된 비율 프로파일 자체에 직접 K-means를 적용한다.
- **용량**: `p31_300`(90 채택 = `train.DEFAULT_PARAMS`) · `p15_150`(분할용 축소).

모든 실행은 2024 학습 / 2025 평가, D−1 정보만(REALTIME_COLS 없는 세트), `lookup` 기준선은
대상 호선 2024 데이터로 한 번만 적합해 재사용한다(station_no가 lookup 키라 전역 데이터로
fit해도 대상 호선 스테이션의 표는 부분집합으로 fit한 것과 값이 같다 — 그래서 공유 파생
캐시를 깨지 않는 전역 fit을 그대로 쓴다).

## 상하선(방향) 분할을 시도하지 않는 이유

패널(`crowd_panel_2024_2025.parquet`)은 역 × 시간대 집계이고 `direction` 컬럼이 없다
(`load_panel()` 스키마 확인 완료 — boarding/alighting은 승하차 타깃이지 방향이 아니다).
방향은 배율표·재귀식 층에서 OD 비례 배분으로 갈리므로 이 패널 위에서는 상하선별 분할이
애초에 불가능하다.

## 참고(그대로 베낀 패턴)

- `split-tuning-check/compare_splits.py` — 분할×용량 격자, `stat_eval.LIGHTGBM`을 일시 교체해
  `table_b`를 재사용하는 쌍 부트스트랩 패턴.
- `split-check/compare_split.py` — `cluster_labels()`(z-score 기반 K-means), `fit_predict()`,
  `metrics_rows()`.

실행(폴더명에 하이픈이 있어 파일 경로로 돈다):
    cd AI
    python validation/CROWD/split-tuning-check/compare_features.py --n-boot 200   # 먼저 빠르게
    python validation/CROWD/split-tuning-check/compare_features.py --out RESULTS_features.md
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

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


compare_split = _load_sibling("validation/CROWD/split-check/compare_split.py", "cf_compare_split")
stat_eval = _load_sibling("validation/CROWD/stat-model-check/evaluate.py", "cf_stat_eval")

from app.CROWD.pipeline.dataset import (
    CROWD_INTERIM,
    load_or_build_derived,
    load_panel,
    time_split,
)
from app.CROWD.pipeline.features import FEATURE_SETS, SLOT_ORDER, build_matrix
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline
from app.CROWD.pipeline.train import train_models

DEPLOY_SET = "festival_selflag_d1sd_d7_resid"
# baseline-check/features.py:54 — 폴더명에 하이픈이 있어 깔끔한 import가 안 돼 값만 복제한다.
WEATHER_COLS = ["temp_c", "precip_mm", "wind_ms", "humidity_pct", "snow_cm"]
EVENT_DROP_COLS = [
    "game_count",
    "festival_count",
    "festival_short_count",
    "festival_long_count",
    "festival_min_duration_days",
]
SET_FS_DEPLOY = "fs_deploy"
SET_FS_WEATHER = "fs_deploy_weather"
SET_FS_NOEVENT = "fs_noevent"
SET_NAMES = [SET_FS_DEPLOY, SET_FS_WEATHER, SET_FS_NOEVENT]

SPLITS: dict[str, str | None] = {
    "global": None,
    "line": "line",
    "cluster_level": "cluster_level_id",
    "cluster_shape": "cluster_shape_id",
}
PARAM_GRID: dict[str, dict] = {
    "p31_300": {},  # train.DEFAULT_PARAMS 그대로
    "p15_150": {"num_leaves": 15, "n_estimators": 150},
}
OUT_DIR = CROWD_INTERIM / "validation" / "split_tuning_check"
BASELINE = "global|p31_300|fs_deploy"


def _register_feature_sets() -> None:
    """검증 전용 세트 3종을 `FEATURE_SETS`에 런타임 등록한다(`features.py` 파일은 수정하지 않는다)."""
    base = list(FEATURE_SETS[DEPLOY_SET])
    FEATURE_SETS[SET_FS_DEPLOY] = base
    FEATURE_SETS[SET_FS_WEATHER] = base + WEATHER_COLS
    FEATURE_SETS[SET_FS_NOEVENT] = [c for c in base if c not in EVENT_DROP_COLS]


# ── 군집 ──
def cluster_shape_labels(train: pd.DataFrame, k: int) -> pd.Series:
    """평일 승차 프로파일을 역별 행 합으로 나눠 정규화한 뒤, z-score 없이 K-means.

    `compare_split.cluster_labels`(→ `cluster_station_profiles`)는 행 단위 z-score를 쓰는데,
    z-score는 행에 대한 어떤 양의 스칼라 배율에도 불변이라 행 합 정규화 후 다시 z-score하면
    수학적으로 `cluster_level`과 완전히 같은 군집이 나온다. 그래서 여기서는 z-score를 건너뛰고
    정규화된 비율 프로파일 자체에 직접 K-means를 적용해 진짜 다른 축을 만든다. 결측 있는 역·
    합이 0인 역은 표준화가 왜곡되므로 제외한다(채우지 않는다 원칙의 연장).
    """
    prof = (
        train[train["day_type"] == "평일"]
        .pivot_table(index="station_no", columns="time_slot", values="boarding", aggfunc="mean")
        .reindex(columns=SLOT_ORDER)
    )
    complete = prof.dropna()
    row_sum = complete.sum(axis=1)
    normed = complete.loc[row_sum > 0].div(row_sum[row_sum > 0], axis=0)
    model = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = model.fit_predict(normed.to_numpy())
    return pd.Series(labels, index=normed.index, name="cluster_shape_id")


# ── 준비 ──
def prepare(lines: list[str], k: int) -> dict:
    t0 = time.time()
    panel = load_panel(with_events=True)
    train_raw, _ = time_split(panel)
    # 대상 호선 데이터로 적합 — station_no가 lookup 키라 전역으로 fit해도 대상 호선 역의 표는
    # 부분집합으로 fit한 것과 값이 같다(다른 호선 행은 그 역의 groupby 평균에 영향을 주지 않는다).
    # 그래서 공유 파생 캐시(`load_or_build_derived`)를 깨지 않는 전역 fit을 그대로 쓴다.
    lookup = DayTypeLookupBaseline().fit(train_raw)
    derived = load_or_build_derived(panel, lookup)
    train, test = time_split(derived)
    train, test = train.reset_index(drop=True), test.reset_index(drop=True)

    train = train[train["line"].isin(lines)].reset_index(drop=True)
    test = test[test["line"].isin(lines)].reset_index(drop=True)

    lookup_pred = lookup.predict(test)
    finite = np.isfinite(lookup_pred[TARGETS].to_numpy(dtype="float64")).all(axis=1)
    n_excluded = int((~finite).sum())
    test = test[finite].reset_index(drop=True)
    lookup_pred = lookup_pred[finite].reset_index(drop=True)

    level_labels = compare_split.cluster_labels(train, k).rename("cluster_level_id")
    shape_labels = cluster_shape_labels(train, k)
    for df in (train, test):
        df["cluster_level_id"] = df["station_no"].map(level_labels)
        df["cluster_shape_id"] = df["station_no"].map(shape_labels)

    crosstab = pd.crosstab(level_labels, shape_labels)
    print(
        f"[준비] 대상 호선 {lines} · 학습 {len(train):,} · 평가 {len(test):,}"
        f"(lookup 결측 제외 {n_excluded:,}행) · 군집 k={k} · {time.time() - t0:.0f}s",
        flush=True,
    )
    print(f"[군집 레벨] {level_labels.value_counts().sort_index().to_dict()}", flush=True)
    print(f"[군집 모양] {shape_labels.value_counts().sort_index().to_dict()}", flush=True)
    print(f"[군집 교차표: 레벨(행) × 모양(열)]\n{crosstab.to_string()}", flush=True)
    return {
        "train": train,
        "test": test,
        "lookup": lookup,
        "lookup_pred": lookup_pred,
        "n_excluded": n_excluded,
        "crosstab": crosstab,
    }


# ── LightGBM: 세트 × 분할 × 용량 ──
def lgb_predict(
    data: dict, feature_set: str, group_col: str | None, params: dict
) -> dict[str, np.ndarray]:
    """그룹별(또는 전역) fit → 평가 행 순서의 최종 예측. 93·145 `fit_predict`와 같은 구조."""
    train, test, lookup = data["train"], data["test"], data["lookup"]
    models = train_models(train, lookup, feature_set, params or None, group_col)
    X = build_matrix(test, feature_set)
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
            # 학습에 없던 그룹(군집 미배정 역 등)은 잔차 0 = lookup(93과 같은 처리)
            resid = np.nan_to_num(resid, nan=0.0)
        out[t] = lk[t].to_numpy() + resid
    return out


# ── 쌍 부트스트랩(기준 조합 대비) ──
def paired_ci(
    data: dict, preds: dict[str, dict[str, np.ndarray]], n_boot: int, seed: int
) -> pd.DataFrame:
    """`BASELINE` 조합 대비 각 조합의 개선율 차이 CI. `compare_splits.paired_ci`와 같은 패턴 —
    `stat_eval.table_b`가 기준 계열 이름을 모듈 상수로 들고 있어 그 값을 `BASELINE`으로 바꿔 쓴다.
    """
    test, lk = data["test"], data["lookup_pred"]
    frame = test[["date", "station_no", "time_slot", "line", "day_type", *TARGETS]].copy()
    for t in TARGETS:
        frame[f"lookup__{t}"] = lk[t].to_numpy(dtype="float64")
    names = ["lookup"]
    for name, pr in preds.items():
        for t in TARGETS:
            frame[f"{name}__{t}"] = pr[t]
        names.append(name)
    losses = stat_eval.daily_losses_multi(frame, names)
    candidates = [n for n in names if n not in ("lookup", BASELINE)]
    keep = stat_eval.LIGHTGBM
    stat_eval.LIGHTGBM = BASELINE
    try:
        b = stat_eval.table_b(losses, candidates, n_boot, seed)
    finally:
        stat_eval.LIGHTGBM = keep
    return b


# ── 실행 ──
def run(args: argparse.Namespace) -> dict[str, pd.DataFrame]:
    t0 = time.time()
    _register_feature_sets()
    data = prepare(args.lines, args.k)
    rows: list[dict] = []
    preds_all: dict[str, dict[str, np.ndarray]] = {}

    combos = [
        (sname, pname, setname)
        for sname in args.splits
        for pname in args.params
        for setname in args.sets
    ]
    base_split, base_param, base_set = "global", "p31_300", SET_FS_DEPLOY
    if (base_split, base_param, base_set) not in combos:
        combos.insert(0, (base_split, base_param, base_set))  # Table 2 기준 조합은 항상 필요

    for sname, pname, setname in combos:
        t1 = time.time()
        preds = lgb_predict(data, setname, SPLITS[sname], PARAM_GRID[pname])
        run_name = f"{sname}|{pname}|{setname}"
        preds_all[run_name] = preds
        chunk = compare_split.metrics_rows(data["test"], data["lookup_pred"], preds, run_name)
        for r in chunk:
            r["분할"], r["파라미터"], r["세트"] = sname, pname, setname
        rows += chunk
        tot = {r["target"]: r for r in chunk if r["axis"] == "전체"}
        print(
            f"[{run_name}] {time.time() - t1:.0f}s · RMSE 개선율 승 "
            f"{tot['boarding']['RMSE_개선율_%']} / 하 {tot['alighting']['RMSE_개선율_%']} · "
            f"MAE {tot['boarding']['MAE_개선율_%']} / {tot['alighting']['MAE_개선율_%']}",
            flush=True,
        )

    res = pd.DataFrame(rows)
    res["run"] = res["분할"] + "|" + res["파라미터"] + "|" + res["세트"]

    # ── 표 1: 격자 전체(전체 축, target별 개선율) ──
    tot = res[res["axis"] == "전체"]
    table1 = tot.pivot_table(
        index=["분할", "파라미터", "세트"],
        columns="target",
        values=["RMSE_개선율_%", "MAE_개선율_%"],
    )
    table1.columns = [f"{m}_{t}" for m, t in table1.columns]
    table1 = table1.reset_index()

    # ── 표 2: 기준 조합(global|p31_300|fs_deploy) 대비 쌍 차이 CI ──
    table2 = paired_ci(data, preds_all, args.n_boot, args.seed)

    # ── 표 3: 세트 효과만 분리 — 같은 (분할, 파라미터)에서 weather-deploy, noevent-deploy ──
    table3_rows = []
    piv = tot.pivot_table(
        index=["분할", "파라미터", "target"],
        columns="세트",
        values=["RMSE_개선율_%", "MAE_개선율_%"],
    )
    for (sname, pname, target), r in piv.iterrows():
        for other, label in (
            (SET_FS_WEATHER, "weather-deploy"),
            (SET_FS_NOEVENT, "noevent-deploy"),
        ):
            try:
                d_rmse = r[("RMSE_개선율_%", other)] - r[("RMSE_개선율_%", SET_FS_DEPLOY)]
                d_mae = r[("MAE_개선율_%", other)] - r[("MAE_개선율_%", SET_FS_DEPLOY)]
            except KeyError:
                continue
            if pd.isna(d_rmse) and pd.isna(d_mae):
                continue
            table3_rows.append(
                {
                    "분할": sname,
                    "파라미터": pname,
                    "target": target,
                    "비교": label,
                    "ΔRMSE_개선율_%p": round(float(d_rmse), 2),
                    "ΔMAE_개선율_%p": round(float(d_mae), 2),
                }
            )
    table3 = pd.DataFrame(table3_rows)

    # ── 표 4: 호선별 분해 — fs_deploy vs fs_deploy_weather, 4분할 × p31_300만 ──
    line_axis = res[
        (res["axis"] == "line")
        & (res["파라미터"] == "p31_300")
        & (res["세트"].isin([SET_FS_DEPLOY, SET_FS_WEATHER]))
        & (res["target"] == "boarding")
    ]
    table4 = line_axis.pivot_table(
        index=["group", "분할"], columns="세트", values="RMSE_개선율_%"
    ).reset_index()

    tables = {
        "표1_격자_전체": table1,
        "표2_기준대비_쌍차이": table2,
        "표3_세트효과_분리": table3,
        "표4_호선별_분해": table4,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for title, tbl in tables.items():
        tbl.to_json(
            OUT_DIR / f"feature_split_{title}_{stamp}.json", orient="records", force_ascii=False
        )
    data["crosstab"].to_json(
        OUT_DIR / f"feature_split_군집교차표_{stamp}.json", orient="split", force_ascii=False
    )
    meta = {
        "lines": args.lines,
        "n_boot": args.n_boot,
        "seed": args.seed,
        "k": args.k,
        "n_excluded_rows": data["n_excluded"],
        "elapsed_sec": round(time.time() - t0, 1),
    }
    (OUT_DIR / f"feature_split_meta_{stamp}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print(
        f"\n### 표 1 — 격자 전체(전체 축 RMSE/MAE 개선율, %)\n{table1.round(2).to_string(index=False)}"
    )
    print(
        f"\n### 표 2 — 기준 조합({BASELINE}) 대비 쌍 차이 [95% CI]\n"
        f"{table2.round(2).to_string(index=False)}"
    )
    print(
        f"\n### 표 3 — 세트 효과만 분리(같은 분할·파라미터 내 차이)\n{table3.to_string(index=False)}"
    )
    print(
        f"\n### 표 4 — 호선별 분해(fs_deploy vs fs_deploy_weather, p31_300)\n{table4.round(2).to_string(index=False)}"
    )
    print(f"\n[군집 교차표: 레벨(행) × 모양(열)]\n{data['crosstab'].to_string()}")
    print(f"[제외 행] lookup 결측 {data['n_excluded']:,}행", flush=True)

    if args.out:
        chunks = [
            (
                f"대상 호선 {args.lines} · 부트스트랩 {args.n_boot}회(seed {args.seed}) · "
                f"제외 행 {data['n_excluded']:,}\n"
            )
        ]
        for title, tbl in tables.items():
            chunks.append(f"### {title}\n\n{stat_eval.to_markdown(tbl.round(3))}\n")
        chunks.append(
            f"### 군집 교차표(레벨×모양)\n\n{stat_eval.to_markdown(data['crosstab'].reset_index())}\n"
        )
        Path(args.out).write_text("\n".join(chunks), encoding="utf-8")
        print(f"[저장] {args.out}", flush=True)
    print(f"[완료] {time.time() - t0:.0f}s", flush=True)
    return tables


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--lines", nargs="+", default=["1호선", "2호선", "6호선"])
    ap.add_argument("--sets", nargs="+", default=SET_NAMES, choices=SET_NAMES)
    ap.add_argument("--splits", nargs="+", default=list(SPLITS), choices=list(SPLITS))
    ap.add_argument("--params", nargs="+", default=list(PARAM_GRID), choices=list(PARAM_GRID))
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None, help="표를 마크다운으로 저장할 경로")
    args = ap.parse_args(argv)
    run(args)


if __name__ == "__main__":
    main(sys.argv[1:])
