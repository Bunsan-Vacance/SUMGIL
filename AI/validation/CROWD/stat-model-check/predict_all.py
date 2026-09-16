"""145 통계 모형 비교 검증 — 계열별 2025 예측을 만든다(비교·CI는 `evaluate.py`).

## 왜

배포 모델은 `lookup(요일유형×역×시간대 평균) + LightGBM(전날·같은요일유형직전·1주전 잔차 시차 +
이벤트 + 범주)`다 — "잔차에 AR 항을 건 모델"의 비선형 판이라고 볼 수 있다. 이 스크립트는 그 가설을
재는 데 필요한 계열들의 2025 예측을 **같은 평가 행**에 남긴다.

## 계열

| 이름 | 정의 |
| --- | --- |
| `lookup` | 요일유형×역×시간대 평균(2024 적합). 기준선 |
| `snaive_d7` | 같은 (역,시간대)의 **원본값** 7일 전(H1 — 노이즈를 그대로 옮기는지) |
| `ols_pooled` | 잔차 = β·[lag1d, lagsd, lag7d] 선형회귀, 타깃별 1개(전역 적합, 2024) |
| `ols_series` | 위와 같되 (역,시간대,타깃)마다 따로 적합(유효행<30이면 그 시리즈 NaN) |
| `sarima_raw` | (역,시간대,타깃) 원본 시계열 SARIMAX(1,0,1)(0,1,1,7), lookup 없이 |
| `sarimax_resid` | 같은 시계열의 lookup 잔차 SARIMAX(1,0,0)(1,0,0,7)+상수, 예측=lookup+잔차예측 |
| `lightgbm` | 배포 세트 아티팩트. 로컬에 없으면 먼저 `python -m app.CROWD.pipeline.train` |

## SARIMA 표본·전체 실행 규칙(계획 §2)

273역×20슬롯×2타깃 = 10,920시리즈를 곧바로 돌리지 않는다. 역을 청크(기본 10역)로 나눠 순서를
"92 표본(`sim-eval/compare_families.pick_sample(test, 50, 30, seed=0)`)의 50역 → 나머지 223역"으로
두고, 50역 만큼 처리한 시점에 시리즈당 시간으로 **전체 소요를 추정**한다. 변형(세트) 하나당 추정이
90분을 넘으면 표본 결과까지만 남기고 멈춘다 — `--full`은 이 결정과 무관하게 청크 재개를 계속할
뿐, 90분 규칙 자체를 건너뛰지 않는다(계획을 임의로 늘리지 않는다).

청크는 `data/CROWD/interim/validation/stat_model_check/chunks/`에 저장돼 중단 후 재실행하면
끝난 청크는 다시 돌지 않는다.

실행(폴더명에 하이픈이 있어 파일 경로로 돈다):
    cd AI
    python -m app.CROWD.pipeline.train                              # 배포 세트 로컬 학습(아티팩트 없으면 먼저)
    python validation/CROWD/stat-model-check/predict_all.py --series lookup snaive_d7 ols_pooled ols_series
    python validation/CROWD/stat-model-check/predict_all.py --series lightgbm
    python validation/CROWD/stat-model-check/predict_all.py --series sarima_raw sarimax_resid
    # 제약을 끈 변형(발산 사례 재현) — 산출은 `*_noenf*`. 역 지정도 된다.
    python validation/CROWD/stat-model-check/predict_all.py --series sarima_raw sarimax_resid \
        --no-enforce-stationarity --stations 2810

청크 캐시는 **입력 조건 메타**(패널 mtime·행 수·값 지문 + order·trend·enforce·구간·역 목록)를 옆에
남긴다. 조건이 하나라도 다르면 그 청크를 다시 계산한다 — 패널이 바뀌었는데 옛 예측을 재사용하는
사고(맥 실행에서 실제로 겪었다)를 막는다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
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

import stat_models

from app.CROWD.pipeline.dataset import (
    CROWD_INTERIM,
    CROWD_PROCESSED,
    PANEL_NAME,
    load_panel,
    time_split,
)
from app.CROWD.pipeline.dl.dataset import load_derived_slim
from app.CROWD.pipeline.features import FEATURE_SETS, RESID_COLS
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline
from app.CROWD.pipeline.predictor import build_predictor, latest_artifact


def _load_sibling(rel_path: str, name: str):
    """다른 하이픈 폴더의 검증 스크립트를 파일 경로로 재사용한다(수정 금지, import만 — 계획 §3)."""
    spec = importlib.util.spec_from_file_location(name, AI_ROOT / rel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


compare_families = _load_sibling(
    "validation/CROWD/sim-eval/compare_families.py", "crowd_stat_model_check_compare_families"
)

DEPLOY_SET = "festival_selflag_d1sd_d7_resid"
# 배포 세트 피처를 **하나도 빠뜨리지 않고** 읽는다. `build_matrix`는 프레임에 없는 컬럼을 조용히
# NaN으로 채우므로(서빙에서 실시간 열이 아직 없을 때를 위한 설계), 여기서 열을 빠뜨리면 LightGBM이
# 그 피처를 결측으로 받은 채 예측한다 — 비교 대상만 몰래 약해진다. 실제로 이벤트 5열이 빠져 있었다.
DEPLOY_FEATURE_COLS = [c for c in FEATURE_SETS[DEPLOY_SET] if c not in ("station_no", "time_slot")]
DERIVED_COLS = [
    "date",
    "station_no",
    "line",
    "time_slot",
    "day_type",
    *TARGETS,
    *RESID_COLS,
    *[c for c in DEPLOY_FEATURE_COLS if c not in RESID_COLS],
]
KEY = ["date", "station_no", "time_slot"]
SPLIT_DATE = pd.Timestamp("2025-01-01")
FULL_DATES = pd.date_range("2024-01-01", "2025-12-31", freq="D")

OUT_DIR = CROWD_INTERIM / "validation" / "stat_model_check"
CHUNK_DIR = OUT_DIR / "chunks"
MODELS_DIR = AI_ROOT / "models" / "CROWD"
PANEL_PATH = CROWD_PROCESSED / PANEL_NAME

# 정상성·가역성 제약은 **켠 쪽이 기본**이다. 끄고 돌리면 늦게 개통한 역(패널 앞부분이 통째로 결측)에서
# 근단위근 계열이 개루프로 전파돼 예측이 발산한다 — 암사역사공원(2810)에서 예측 최댓값이 1e25~1e143까지
# 튀었고, 제약을 켜자 0건이 됐다(RESULTS 1절). 끈 쪽은 `--no-enforce-stationarity`(`_noenf`)로만 돌린다.
SARIMA_SPECS: dict[str, dict] = {
    # lookup 도움 없는 "순수 ARIMA" — H2
    "sarima_raw": {
        "value_cols": list(TARGETS),
        "order": (1, 0, 1),
        "seasonal_order": (0, 1, 1, 7),
        "trend": None,
        "enforce_stationarity": True,
        "enforce_invertibility": True,
    },
    # lookup 잔차 위의 선형 시계열 모형 — H4(OLS-AR과 비교)
    "sarimax_resid": {
        "value_cols": list(RESID_COLS),
        "order": (1, 0, 0),
        "seasonal_order": (1, 0, 0, 7),
        "trend": "c",
        "enforce_stationarity": True,
        "enforce_invertibility": True,
    },
}
ALL_SERIES = [
    "lookup",
    "snaive_d7",
    "ols_pooled",
    "ols_series",
    "sarima_raw",
    "sarimax_resid",
    "lightgbm",
]


# ── 준비 ──
def prepare() -> dict:
    t0 = time.time()
    panel = load_panel(with_events=True)
    train_raw, test_raw = time_split(panel, SPLIT_DATE)
    lookup = DayTypeLookupBaseline().fit(train_raw)
    derived = load_derived_slim(columns=DERIVED_COLS)
    train, test = time_split(derived, SPLIT_DATE)
    print(
        f"[준비] 패널 {len(panel):,}행 · 파생 {len(derived):,}행 · 학습 {len(train):,} · "
        f"평가 {len(test):,} · {time.time() - t0:.0f}s",
        flush=True,
    )
    return {
        "panel": panel,
        "train_raw": train_raw,
        "test_raw": test_raw,
        "lookup": lookup,
        "derived": derived,
        "train": train,
        "test": test,
    }


def _save(name: str, frame: pd.DataFrame) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"stat_preds_{name}.parquet"
    frame.to_parquet(path, index=False)
    print(f"[저장] {name}: {len(frame):,}행 → {path.relative_to(AI_ROOT)}", flush=True)
    return path


# ── lookup ──
def predict_lookup(lookup: DayTypeLookupBaseline, frame: pd.DataFrame) -> pd.DataFrame:
    pred = lookup.predict(frame)
    out = frame[KEY].copy()
    for t in TARGETS:
        out[f"{t}_pred"] = pred[t].to_numpy()
    return out.reset_index(drop=True)


# ── 계절 나이브(H1) ──
def predict_snaive(panel: pd.DataFrame) -> pd.DataFrame:
    attached = stat_models.attach_snaive(
        panel[["date", "station_no", "time_slot", *TARGETS]], day_lag=7
    )
    test = attached[attached["date"] >= SPLIT_DATE].reset_index(drop=True)
    out = test[KEY].copy()
    for t in TARGETS:
        out[f"{t}_pred"] = test[f"{t}_snaive"].to_numpy()
    return out


# ── OLS(H3·H4) ──
def _feat_cols(target: str) -> list[str]:
    return [f"lag1d_{target}_resid", f"lagsd_{target}_resid", f"lag7d_{target}_resid"]


def predict_ols_pooled(
    lookup_pred: pd.DataFrame, train: pd.DataFrame, test: pd.DataFrame, min_valid_rows: int = 30
) -> tuple[pd.DataFrame, dict]:
    out = test[KEY].copy()
    diag = {}
    for t in TARGETS:
        cols = _feat_cols(t)
        coef = stat_models.fit_ols(
            train[cols].to_numpy(), train[f"{t}_resid"].to_numpy(), min_valid_rows
        )
        resid_pred = stat_models.predict_ols(test[cols].to_numpy(), coef)
        out[f"{t}_pred"] = lookup_pred[t].to_numpy() + resid_pred
        diag[t] = {
            "coef": None if coef is None else [round(float(c), 4) for c in coef],
            "n_train_valid": int(np.isfinite(train[cols].to_numpy()).all(axis=1).sum()),
        }
    return out, diag


def predict_ols_series(
    lookup_pred: pd.DataFrame, train: pd.DataFrame, test: pd.DataFrame, min_valid_rows: int = 30
) -> tuple[pd.DataFrame, dict]:
    """(역, 시간대, 타깃)마다 독립적인 OLS. 유효행이 `min_valid_rows` 미만인 시리즈는 NaN(원칙 8)."""
    train_groups = train.groupby(["station_no", "time_slot"], observed=True).indices
    test_groups = test.groupby(["station_no", "time_slot"], observed=True).indices
    pred = {t: np.full(len(test), np.nan) for t in TARGETS}
    n_fitted = {t: 0 for t in TARGETS}
    for key, test_idx in test_groups.items():
        te_idx = np.asarray(test_idx)
        tr_idx = train_groups.get(key)
        for t in TARGETS:
            cols = _feat_cols(t)
            coef = None
            if tr_idx is not None:
                tr = train.iloc[np.asarray(tr_idx)]
                coef = stat_models.fit_ols(
                    tr[cols].to_numpy(), tr[f"{t}_resid"].to_numpy(), min_valid_rows
                )
            if coef is not None:
                n_fitted[t] += 1
            te = test.iloc[te_idx]
            pred[t][te_idx] = stat_models.predict_ols(te[cols].to_numpy(), coef)
    out = test[KEY].copy()
    for t in TARGETS:
        out[f"{t}_pred"] = lookup_pred[t].to_numpy() + pred[t]
    diag = {"n_series": len(test_groups), "n_fitted": n_fitted}
    return out, diag


# ── SARIMA(H2·H4) ──
def _station_order(all_stations: np.ndarray, sample_stations: np.ndarray) -> list[int]:
    sample_set = {int(s) for s in sample_stations}
    rest = [int(s) for s in all_stations if int(s) not in sample_set]
    return [int(s) for s in sample_stations] + rest


def run_sarima_variant(
    name: str,
    spec: dict,
    source_frame: pd.DataFrame,
    all_stations: np.ndarray,
    sample_stations: np.ndarray,
    chunk_stations: int = 10,
    n_jobs: int = -1,
    budget_minutes: float = 90.0,
    max_stations: int | None = None,
    stations: list[int] | None = None,
    tag: str = "",
) -> tuple[pd.DataFrame, dict]:
    wide = stat_models.build_wide_series(source_frame, spec["value_cols"], FULL_DATES)
    ordered = _station_order(all_stations, sample_stations)
    if stations:
        # 지정한 역만 — 발산이 난 역을 변형 사양으로 다시 돌려 볼 때(계획 §3의 재발 방지책 비교).
        want = [int(x) for x in stations]
        ordered = [st for st in ordered if st in set(want)]
    if max_stations is not None:
        ordered = ordered[:max_stations]
    chunks = [ordered[i : i + chunk_stations] for i in range(0, len(ordered), chunk_stations)]
    n_sample_chunks = math.ceil(min(len(sample_stations), len(ordered)) / chunk_stations)
    source_sig = stat_models.source_signature(
        source_frame,
        spec["value_cols"],
        extra={
            "panel_file": PANEL_PATH.name,
            "panel_mtime": PANEL_PATH.stat().st_mtime if PANEL_PATH.exists() else None,
        },
    )

    CHUNK_DIR.mkdir(parents=True, exist_ok=True)
    results: list[pd.DataFrame] = []
    t0 = time.time()
    meta = {
        "n_stations_total": len(ordered),
        "n_sample_stations": len(sample_stations),
        "sample_elapsed_sec": None,
        "projected_full_minutes": None,
        "stopped_after_sample": False,
        "n_chunks_done": 0,
        "n_chunks_recomputed": 0,
        "enforce_stationarity": bool(spec.get("enforce_stationarity", False)),
    }
    for i, station_group in enumerate(chunks):
        chunk_path = CHUNK_DIR / f"{name}{tag}_chunk_{i:04d}.parquet"
        meta_path = chunk_path.with_suffix(".meta.json")
        want = stat_models.chunk_signature(source_sig, spec, SPLIT_DATE, SPLIT_DATE, station_group)
        have = None
        if meta_path.exists():
            try:
                have = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                have = None
        if chunk_path.exists() and stat_models.chunk_cache_valid(have, want):
            results.append(pd.read_parquet(chunk_path))
            print(f"[{name}{tag}] 청크 {i + 1}/{len(chunks)} 캐시 재사용", flush=True)
        else:
            if chunk_path.exists():
                # 패널·모형 사양이 달라졌는데 옛 예측을 재사용하면 낡은 수치로 표가 나온다.
                print(
                    f"[{name}{tag}] 청크 {i + 1}/{len(chunks)} 입력 조건이 달라졌다 — 다시 계산",
                    flush=True,
                )
                meta["n_chunks_recomputed"] += 1
            keys = [c for c in wide.columns if c[1] in set(station_group)]
            res = stat_models.run_sarima_batch(
                wide,
                keys,
                spec["order"],
                spec["seasonal_order"],
                SPLIT_DATE,
                SPLIT_DATE,
                spec.get("trend"),
                n_jobs=n_jobs,
                enforce_stationarity=bool(spec.get("enforce_stationarity", False)),
                enforce_invertibility=bool(spec.get("enforce_invertibility", False)),
            )
            chunk_path.parent.mkdir(parents=True, exist_ok=True)
            res.to_parquet(chunk_path, index=False)
            meta_path.write_text(json.dumps(want, ensure_ascii=False, indent=1), encoding="utf-8")
            results.append(res)
            print(
                f"[{name}{tag}] 청크 {i + 1}/{len(chunks)}({len(station_group)}역) "
                f"누적 {time.time() - t0:.0f}s",
                flush=True,
            )
        meta["n_chunks_done"] = i + 1
        if i + 1 == n_sample_chunks:
            elapsed = time.time() - t0
            meta["sample_elapsed_sec"] = round(elapsed, 1)
            projected_total_sec = elapsed / (i + 1) * len(chunks)
            meta["projected_full_minutes"] = round(projected_total_sec / 60.0, 1)
            print(
                f"[{name}{tag}] 표본({sum(len(g) for g in chunks[: i + 1])}역) {elapsed:.0f}s → "
                f"전체({len(ordered)}역) 추정 {projected_total_sec / 60:.1f}분",
                flush=True,
            )
            if projected_total_sec > budget_minutes * 60:
                print(
                    f"[{name}{tag}] 90분 규칙: 추정 {projected_total_sec / 60:.1f}분 > "
                    f"{budget_minutes:.0f}분 — 표본 결과까지만 내고 멈춘다.",
                    flush=True,
                )
                meta["stopped_after_sample"] = True
                break
    out = pd.concat(results, ignore_index=True) if results else pd.DataFrame()
    return out, meta


def sarima_long_to_wide(
    long_df: pd.DataFrame, target_map: dict[str, str], lookup_pred_test: pd.DataFrame | None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """SARIMA 배치 출력(롱)을 예측 스키마(넓은 표) + 진단(수렴·실패) 프레임으로 나눈다."""
    diag = long_df[
        ["target", "station_no", "time_slot", "date", "ok", "error", "n_convergence_warnings"]
    ]
    piv = long_df.pivot_table(
        index=KEY, columns="target", values="pred", aggfunc="first"
    ).reset_index()
    piv = piv.rename(columns=target_map)
    for t in TARGETS:
        if t not in piv.columns:
            piv[t] = np.nan
    if lookup_pred_test is not None:
        merged = piv.merge(lookup_pred_test, on=KEY, how="left", suffixes=("", "_lookup"))
        out = merged[KEY].copy()
        for t in TARGETS:
            out[f"{t}_pred"] = merged[t] + merged[f"{t}_lookup"]
    else:
        out = piv.rename(columns={t: f"{t}_pred" for t in TARGETS})[
            [*KEY, *[f"{t}_pred" for t in TARGETS]]
        ]
    return out, diag


# ── LightGBM ──
def predict_lightgbm(test: pd.DataFrame, artifact: Path | None) -> tuple[pd.DataFrame, str]:
    artifact = artifact or latest_artifact(MODELS_DIR, kind="lightgbm")
    if artifact is None:
        raise SystemExit(
            f"LightGBM 아티팩트가 없다({MODELS_DIR}). "
            "`python -m app.CROWD.pipeline.train`으로 배포 세트를 먼저 학습할 것."
        )
    predictor = build_predictor("lightgbm", artifact_dir=artifact)
    if predictor.feature_set != DEPLOY_SET:
        raise SystemExit(
            f"아티팩트 세트가 배포 세트와 다르다: {predictor.feature_set} != {DEPLOY_SET}."
        )
    # `build_matrix`는 없는 컬럼을 NaN으로 채우므로 여기서 막지 않으면 비교 대상만 조용히 약해진다.
    missing = stat_models.missing_feature_columns(test.columns, FEATURE_SETS[predictor.feature_set])
    if missing:
        raise SystemExit(
            f"평가 프레임에 배포 세트 피처가 없다: {missing}. "
            "DERIVED_COLS에 그 컬럼을 넣어 파생 캐시에서 읽어올 것."
        )
    pred = predictor._inner.predict_derived(test)
    out = test[KEY].merge(pred[[*KEY, *[f"{t}_pred" for t in TARGETS]]], on=KEY, how="left")
    return out, predictor.version


# ── 실행 ──
def run(args: argparse.Namespace) -> None:
    data = prepare()
    # 산출 스키마({t}_pred)와 내부 연산용(원 컬럼명 t) lookup 예측을 따로 둔다 — 잔차 계열은
    # `lookup + 잔차예측`을 계산해야 하는데 원본 `DayTypeLookupBaseline.predict`는 접미 없는
    # `TARGETS` 이름을 쓴다.
    lookup_values_test = data["lookup"].predict(data["test"])
    lookup_pred_test = predict_lookup(data["lookup"], data["test"])
    # 키 + 원 컬럼명(TARGETS) — SARIMA(잔차) 계열이 최종값(lookup + 잔차예측)을 만들 때 키로 조인한다.
    lookup_keyed_test = data["test"][KEY].copy()
    for _t in TARGETS:
        lookup_keyed_test[_t] = lookup_values_test[_t].to_numpy()

    if "lookup" in args.series:
        _save("lookup", lookup_pred_test)

    if "snaive_d7" in args.series:
        _save("snaive_d7", predict_snaive(data["panel"]))

    if "ols_pooled" in args.series:
        out, diag = predict_ols_pooled(lookup_values_test, data["train"], data["test"])
        _save("ols_pooled", out)
        print(f"[ols_pooled] 진단: {diag}", flush=True)

    if "ols_series" in args.series:
        t0 = time.time()
        out, diag = predict_ols_series(lookup_values_test, data["train"], data["test"])
        _save("ols_series", out)
        print(f"[ols_series] 진단: {diag} · {time.time() - t0:.0f}s", flush=True)

    if "lightgbm" in args.series:
        out, version = predict_lightgbm(
            data["test"], Path(args.artifact) if args.artifact else None
        )
        _save("lightgbm", out)
        print(f"[lightgbm] 아티팩트: {version}", flush=True)

    sarima_names = [s for s in args.series if s in SARIMA_SPECS]
    if sarima_names:
        sample_stations, _ = compare_families.pick_sample(data["test_raw"], 50, 30, seed=0)
        all_stations = np.sort(data["test_raw"]["station_no"].unique())
        # `--no-enforce-stationarity`는 제약을 끈 **별도 변형**이다 — 이름·청크·산출 파일에 `_noenf`를
        # 붙여 기본(제약 켬)의 캐시·결과를 덮어쓰지 않는다.
        tag = "_noenf" if args.no_enforce_stationarity else ""
        for name in sarima_names:
            spec = {**SARIMA_SPECS[name]}
            if args.no_enforce_stationarity:
                spec["enforce_stationarity"] = False
                spec["enforce_invertibility"] = False
            source = (
                data["derived"] if set(spec["value_cols"]) <= set(RESID_COLS) else data["panel"]
            )
            long_out, meta = run_sarima_variant(
                name,
                spec,
                source,
                all_stations,
                sample_stations,
                chunk_stations=args.chunk_stations,
                n_jobs=args.n_jobs,
                budget_minutes=args.budget_minutes,
                max_stations=args.max_stations,
                stations=args.stations,
                tag=tag,
            )
            if long_out.empty:
                print(f"[{name}{tag}] 결과 없음 — 건너뜀", flush=True)
                continue
            target_map = dict(zip(spec["value_cols"], TARGETS))
            lookup_arg = lookup_keyed_test if spec["value_cols"] == list(RESID_COLS) else None
            wide, diag = sarima_long_to_wide(long_out, target_map, lookup_arg)
            partial = (
                meta["stopped_after_sample"] or args.max_stations is not None or bool(args.stations)
            )
            suffix = f"{tag}_sample" if partial else tag
            _save(f"{name}{suffix}", wide)
            n_series = diag[["station_no", "time_slot", "target"]].drop_duplicates()
            series_ok = diag.groupby(["station_no", "time_slot", "target"])["ok"].first()
            n_fail = int((~series_ok.astype(bool)).sum())
            n_warn = int(diag["n_convergence_warnings"].sum())
            diag_path = OUT_DIR / f"stat_preds_{name}{suffix}_diag.parquet"
            diag.to_parquet(diag_path, index=False)
            print(
                f"[{name}{suffix}] 시리즈 {len(n_series):,}개 · 실패 {n_fail:,}개"
                f"({n_fail / max(len(n_series), 1) * 100:.2f}%) · 수렴경고 {n_warn:,}건 · 메타 {meta}",
                flush=True,
            )
            if n_fail / max(len(n_series), 1) > 0.01:
                print(
                    f"[경고] {name}{suffix} 실패율이 1%를 넘는다 — RESULTS에 명시할 것.", flush=True
                )


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--series", nargs="+", default=ALL_SERIES, choices=ALL_SERIES)
    ap.add_argument("--artifact", default=None, help="LightGBM 아티팩트 디렉터리(생략 시 최신)")
    ap.add_argument("--chunk-stations", type=int, default=10)
    ap.add_argument("--n-jobs", type=int, default=-1)
    ap.add_argument("--budget-minutes", type=float, default=90.0, help="계획 §2의 90분 규칙")
    ap.add_argument(
        "--no-enforce-stationarity",
        action="store_true",
        help="SARIMAX 정상성·가역성 제약을 끈 변형(_noenf) — 발산 사례 재현용(기본은 제약 켬)",
    )
    ap.add_argument(
        "--max-stations",
        type=int,
        default=None,
        help="처리할 역 수 상한(표본 50역만 재볼 때). 생략 시 전체 273역",
    )
    ap.add_argument(
        "--stations",
        type=int,
        nargs="+",
        default=None,
        help="지정한 역만 처리한다(발산 역 재현·변형 비교용). 산출 이름에 _sample이 붙는다",
    )
    args = ap.parse_args(argv)
    run(args)


if __name__ == "__main__":
    main(sys.argv[1:])
