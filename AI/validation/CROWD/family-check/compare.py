"""145 모델 계열 비교 — ML(lookup · LightGBM) 대 DL(GRU V3, 시드 3개), 가용성 시나리오 4종.

## 왜 새 스크립트인가

계열별 시나리오 예측·정렬·등급 변환·하루치 추론 시간은 이미 144·198의
`dl-resid-check/evaluate_dl.py`가 한다. 그 스크립트가 **하지 않는 것이 하나** 있다 —
계열 사이의 **쌍 부트스트랩 CI**다(142 §7이 145로 넘긴 과제). 2025 전행 예측을 저장하지 않고
7일 간격 표본만 남기기 때문이다.

그래서 이 스크립트는 `evaluate_dl`의 함수를 그대로 import해 예측을 만들고(복붙 금지),
**날짜별 손실 충분통계**(SSE·SAE·n)를 계열×시나리오마다 쌓아 142 `bootstrap.py`의 블록 재표본으로
계열 차이 CI를 낸다. 표 조립은 145 통계 모형 파트의 `stat-model-check/evaluate.py`의
`daily_losses_multi`·`table_a`·`table_b`를 재사용한다 — 같은 판정 축(전체·호선·요일유형)을 쓰기 위해서다.

## 왜 이 비교인가

- 198이 넘긴 것: **가용성별 2단 규칙**(`full` → LightGBM, 결손·전무 → GRU V3). 198의 근거는 시드 3회
  표준편차였고 **계열 차이의 CI는 없었다** — 시드 분산과 날짜 분산은 다른 축이다.
- 143이 넘긴 것: 시차가 전부 없으면(`no_lag`) LightGBM이 lookup보다 −37%p. 그 자리에 GRU가 대체
  후보로 설 수 있는지를 **lookup 대비 CI 하한이 0 위인가**로 본다.
- 계열 이름은 `gru`다(198 판정). LSTM·이벤트 인코딩 변형은 198에서 끝났고 여기서 다시 돌리지 않는다.

## 범위 밖

LLM(`llm_rag`)은 `CROWD_LLM_API_KEY`가 없어 호출하지 않는다 — 계획대로 비교표에 `미실행`으로 남기고
프롬프트는 92 산출물(`family_compare_llm_prompts.json`)을 그대로 둔다. 키가 생기면 이 표에 행을 더한다.

실행(폴더명에 하이픈이 있어 파일 경로로 돈다):
    cd AI
    python validation/CROWD/family-check/compare.py --eval-days 30      # 스모크(1분)
    python validation/CROWD/family-check/compare.py --grades full --out RESULTS_tables.md
"""

from __future__ import annotations

import argparse
import importlib.util
import os
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


evaluate_dl = _load_sibling("validation/CROWD/dl-resid-check/evaluate_dl.py", "family_evaluate_dl")
stat_eval = _load_sibling("validation/CROWD/stat-model-check/evaluate.py", "family_stat_eval")
stat_models = _load_sibling(
    "validation/CROWD/stat-model-check/stat_models.py", "family_stat_models"
)

from app.CROWD.pipeline.dataset import (
    CROWD_INTERIM,
    CROWD_PROCESSED,
    load_panel,
    resolved_segments,
    time_split,
)
from app.CROWD.pipeline.dl.dataset import load_derived_slim
from app.CROWD.pipeline.dl.train_dl import resolve_device
from app.CROWD.pipeline.features import FEATURE_SETS
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline
from app.CROWD.pipeline.predictor import build_predictor, latest_artifact
from app.CROWD.pipeline.topology import load_capacity

EVAL_START = pd.Timestamp("2025-01-01")
DEPLOY_SET = evaluate_dl.DEPLOY_SET
MODELS_DIR = AI_ROOT / "models" / "CROWD"
OUT_DIR = CROWD_INTERIM / "validation" / "family_check"
# 198 채택 구성(V3 = 정적 이벤트 없음) 3시드. 144 아티팩트가 아니다.
GRU_SEEDS = {
    "gru_s42": "dl_gru_s14_noev_s42_20260914-1358",
    "gru_s43": "dl_gru_s14_noev_s43_20260914-1404",
    "gru_s44": "dl_gru_s14_noev_s44_20260914-1406",
}
LLM_PROMPTS = CROWD_INTERIM / "validation" / "family_compare_llm_prompts.json"


# ── 준비 ──
def prepare(args) -> dict:
    t0 = time.time()
    panel = load_panel(with_events=True)
    train_raw, _ = time_split(panel)
    lookup = DayTypeLookupBaseline().fit(train_raw)
    derived = load_derived_slim(columns=evaluate_dl.DERIVED_COLS)
    train = derived[derived["date"] < EVAL_START]
    test = derived[derived["date"] >= EVAL_START]
    if args.eval_days:  # 스모크 — 평가 구간을 앞쪽 N일로 자른다
        test = test[test["date"] < EVAL_START + pd.Timedelta(days=args.eval_days)]
    test = test.reset_index(drop=True)
    missing = stat_models.missing_feature_columns(test.columns, FEATURE_SETS[DEPLOY_SET])
    if missing:  # 세트 피처가 비면 LightGBM만 조용히 약해진다(145 통계 파트에서 실제로 겪었다)
        raise SystemExit(f"평가 프레임에 배포 세트 피처가 없다: {missing}")
    window = panel[
        (panel["date"] >= EVAL_START - pd.Timedelta(days=args.window_days))
        & (panel["date"] <= test["date"].max())
    ].reset_index(drop=True)
    segments, _ = resolved_segments(panel)
    bounds = stat_models.divergence_bounds(train, TARGETS)
    print(
        f"[준비] 평가 {len(test):,}행 · DL 창 {len(window):,}행 · {time.time() - t0:.0f}s",
        flush=True,
    )
    return {
        "panel": panel,
        "lookup": lookup,
        "test": test,
        "window": window,
        "segments": segments,
        "bounds": bounds,
    }


# ── 계열×시나리오 예측 ──
def series_predictions(args, data: dict) -> dict[tuple[str, str], dict[str, np.ndarray]]:
    test, scenarios = data["test"], args.scenarios
    lgb = Path(args.lightgbm) if args.lightgbm else latest_artifact(MODELS_DIR, kind="lightgbm")
    if lgb is None:
        raise SystemExit("LightGBM 아티팩트가 없다 — `python -m app.CROWD.pipeline.train` 먼저.")
    print(f"[아티팩트] lightgbm={lgb.name}", flush=True)
    aligned: dict[tuple[str, str], dict[str, np.ndarray]] = {}
    for sc, frame in evaluate_dl.lgb_predictions(lgb, test, scenarios).items():
        aligned[("lightgbm", sc)] = evaluate_dl.align(test, frame)

    device = resolve_device(args.device)
    for name in args.seeds:
        artifact = MODELS_DIR / GRU_SEEDS[name]
        if not artifact.exists():
            raise SystemExit(f"DL 아티팩트가 없다: {artifact}")
        print(f"[아티팩트] {name}={artifact.name} (device={device})", flush=True)
        runs = evaluate_dl.dl_predictions(
            artifact, data["window"], scenarios, device, data["segments"]
        )
        for sc, frame in runs.items():
            aligned[(name, sc)] = evaluate_dl.align(test, frame)
    return aligned


def treat(aligned: dict, bounds: dict, mode: str) -> pd.DataFrame:
    """발산 처리(기본 `raw`)를 적용하고 걸린 행 수를 표로 남긴다.

    기본이 `raw`인 이유 — 이 표의 `lightgbm` 수치는 144·198·MODEL_REGISTRY와 나란히 읽혀야 하고
    그 문서들은 자르지 않은 값이다. `clip`으로 바꿔도 결론이 같은지는 걸린 행 수로 판단한다.
    """
    rows = []
    for (name, sc), preds in aligned.items():
        for t in TARGETS:
            low, high = bounds[t]
            values, counts = stat_models.apply_bounds(preds[t], low, high, mode)
            preds[t] = values
            rows.append(
                {
                    "series": name,
                    "scenario": sc,
                    "target": t,
                    "mode": mode,
                    "하한미만_행": counts["n_low"],
                    "상한초과_행": counts["n_high"],
                }
            )
    return pd.DataFrame(rows)


def common_mask(test: pd.DataFrame, lookup_pred: pd.DataFrame, aligned: dict) -> np.ndarray:
    """모든 계열·시나리오·타깃이 유한한 행만. 채우지 않는다(원칙 8)."""
    finite = np.ones(len(test), dtype=bool)
    for t in TARGETS:
        finite &= np.isfinite(lookup_pred[t].to_numpy(dtype="float64"))
        finite &= np.isfinite(test[t].to_numpy(dtype="float64"))
    for preds in aligned.values():
        for t in TARGETS:
            finite &= np.isfinite(preds[t])
    print(
        f"[공통 행] {int(finite.sum()):,} / {len(test):,} ({finite.mean() * 100:.2f}%)", flush=True
    )
    return finite


# ── 시나리오별 표 ──
def scenario_frame(
    common: pd.DataFrame, common_lookup: pd.DataFrame, aligned: dict, finite: np.ndarray, sc: str
) -> tuple[pd.DataFrame, list[str]]:
    """`stat_eval.daily_losses_multi`가 먹는 모양(`{계열}__{타깃}` 열)으로 한 시나리오를 펼친다."""
    frame = common.copy()
    for t in TARGETS:
        frame[f"lookup__{t}"] = common_lookup[t].to_numpy(dtype="float64")
    names = ["lookup"]
    for (name, scenario), preds in aligned.items():
        if scenario != sc:
            continue
        for t in TARGETS:
            frame[f"{name}__{t}"] = preds[t][finite]
        names.append(name)
    return frame, names


def compare_tables(
    args, common, common_lookup, aligned, finite
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """시나리오마다 표 A(lookup 대비 CI)·표 B(LightGBM과의 쌍 차이 CI)를 내고 이어 붙인다."""
    a_all, b_all = [], []
    for sc in args.scenarios:
        frame, names = scenario_frame(common, common_lookup, aligned, finite, sc)
        losses = stat_eval.daily_losses_multi(frame, names)
        candidates = [n for n in names if n != "lookup"]
        a = stat_eval.table_a(losses, candidates, args.n_boot, args.seed).assign(scenario=sc)
        b = stat_eval.table_b(
            losses, [n for n in candidates if n != "lightgbm"], args.n_boot, args.seed
        ).assign(scenario=sc)
        a_all.append(a)
        b_all.append(b)
        tot = a[(a["axis"] == "전체")].set_index(["series", "target"])
        for n in candidates:
            print(
                f"[{sc}] {n}: RMSE 개선율 승 {tot.loc[(n, 'boarding'), 'RMSE_개선율_%']:+.2f} "
                f"[{tot.loc[(n, 'boarding'), 'RMSE_CI_low']:+.2f}] / "
                f"하 {tot.loc[(n, 'alighting'), 'RMSE_개선율_%']:+.2f} "
                f"[{tot.loc[(n, 'alighting'), 'RMSE_CI_low']:+.2f}]",
                flush=True,
            )
    return pd.concat(a_all, ignore_index=True), pd.concat(b_all, ignore_index=True)


# ── 등급·시간·LLM ──
def grade_table(common, common_lookup, aligned, finite, scenario: str) -> pd.DataFrame | None:
    path = CROWD_PROCESSED / evaluate_dl.CALIBRATION_NAME
    if not path.exists():
        print(f"[안내] 배율표가 없다({path.name}) — 등급 건너뜀.", flush=True)
        return None
    segments, _ = resolved_segments(common)
    boards = {"lookup": {t: common_lookup[t].to_numpy(dtype="float64") for t in TARGETS}}
    for (name, sc), preds in aligned.items():
        if sc == scenario:
            boards[name] = {t: preds[t][finite] for t in TARGETS}
    g = evaluate_dl.grade_agreement(
        common, boards, segments, load_capacity(), pd.read_parquet(path)
    )
    return g.assign(scenario=scenario)


def timing_rows(args, data: dict) -> list[dict]:
    """하루치 추론 시간 — 판정 기준(하루 10분)은 서빙과 같은 CPU 기준으로 잰다."""
    target = pd.Timestamp(args.timing_date)
    rows = []
    gru_name = args.seeds[0]
    rows.append(
        evaluate_dl.time_one_day(
            MODELS_DIR / GRU_SEEDS[gru_name], data["panel"], target, "cpu", data["segments"]
        )
        | {"series": gru_name}
    )
    lgb = Path(args.lightgbm) if args.lightgbm else latest_artifact(MODELS_DIR, kind="lightgbm")
    predictor = build_predictor("lightgbm", artifact_dir=lgb)
    day = data["test"][data["test"]["date"] == target]
    t0 = time.time()
    predictor._inner.predict_derived(day)
    rows.append(
        {
            "series": "lightgbm",
            "artifact": lgb.name,
            "device": "cpu",
            "target_date": str(target.date()),
            "history_days": 0,
            "target_rows": len(day),
            "seconds": round(time.time() - t0, 2),
        }
    )
    for r in rows:
        print(
            f"[추론 시간] {r['series']}: {r['target_rows']:,}행 {r['seconds']}s (cpu)", flush=True
        )
    return rows


def llm_row() -> dict:
    """LLM 계열은 키가 없으면 호출하지 않는다 — 미실행 사유를 표에 남긴다(계획 §2)."""
    has_key = bool(os.environ.get("CROWD_LLM_API_KEY"))
    return {
        "series": "llm_rag",
        "상태": "키 확보 시 재실행" if not has_key else "키 있음 — 별도 실행 필요",
        "사유": "CROWD_LLM_API_KEY 없음" if not has_key else "compare.py 범위 밖(llm_family.py)",
        "프롬프트": LLM_PROMPTS.name if LLM_PROMPTS.exists() else "없음",
    }


# ── 실행 ──
def run(args) -> dict[str, pd.DataFrame]:
    t0 = time.time()
    data = prepare(args)
    test, lookup = data["test"], data["lookup"]
    lookup_pred = lookup.predict(test)
    aligned = series_predictions(args, data)
    treatment = treat(aligned, data["bounds"], args.divergence)
    finite = common_mask(test, lookup_pred, aligned)
    common = test[finite].reset_index(drop=True)
    common_lookup = lookup_pred[finite].reset_index(drop=True)

    a, b = compare_tables(args, common, common_lookup, aligned, finite)
    tables = {"A_lookup_대비_개선율_CI": a, "B_lightgbm_쌍차이": b, "C_발산처리_적용행": treatment}
    if args.grades:
        g = grade_table(common, common_lookup, aligned, finite, args.grades)
        if g is not None:
            tables["D_등급_일치율"] = g
    if not args.no_timing:
        tables["E_추론_시간"] = pd.DataFrame(timing_rows(args, data))
    tables["F_LLM_상태"] = pd.DataFrame([llm_row()])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for title, tbl in tables.items():
        tbl.to_parquet(OUT_DIR / f"family_check_{title}.parquet", index=False)
        print(f"\n### {title}\n{tbl.round(3).to_string(index=False)}")
    if args.out:
        head = (
            f"발산 처리: `{args.divergence}` · 부트스트랩 {args.n_boot}회(seed {args.seed}) · "
            f"시나리오 {args.scenarios} · 시드 {args.seeds}\n"
        )
        chunks = [head] + [
            f"### {title}\n\n{stat_eval.to_markdown(tbl.round(3))}\n"
            for title, tbl in tables.items()
        ]
        Path(args.out).write_text("\n".join(chunks), encoding="utf-8")
        print(f"[저장] {args.out}", flush=True)
    print(f"[완료] {time.time() - t0:.0f}s", flush=True)
    return tables


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--scenarios", nargs="+", default=list(evaluate_dl.SCENARIOS))
    ap.add_argument("--seeds", nargs="+", default=list(GRU_SEEDS), choices=list(GRU_SEEDS))
    ap.add_argument("--lightgbm", default=None, help="LightGBM 아티팩트(생략 시 최신)")
    ap.add_argument("--device", default="auto", help="DL 대량 추론 장치(시간 측정은 항상 cpu)")
    ap.add_argument("--window-days", type=int, default=14)
    ap.add_argument("--eval-days", type=int, default=None, help="스모크용 — 평가 앞쪽 N일만")
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument(
        "--divergence", default="raw", choices=["raw", "clip", "drop"], help="발산 처리(기본 raw)"
    )
    ap.add_argument("--grades", default=None, help="등급 일치율을 낼 시나리오 하나(예: full)")
    ap.add_argument("--no-timing", action="store_true")
    ap.add_argument("--timing-date", default="2025-06-02")
    ap.add_argument("--out", default=None, help="표를 마크다운으로 저장할 경로")
    args = ap.parse_args(argv)
    run(args)


if __name__ == "__main__":
    main(sys.argv[1:])
