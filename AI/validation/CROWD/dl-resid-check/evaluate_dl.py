"""144 — GRU 잔차 모델 2025 평가: 이력 가용성 4시나리오 × 모델 3계열.

143에서 확인된 것: 배포 LightGBM은 시차가 전부 NaN이면 lookup보다 **−37%**다. 144의 질문은
"`full` 정확도"가 아니라 **"이력이 짧을 때 lookup 이하로 떨어지지 않는가"**이고, 그 답을 내려면
같은 행 집합에서 같은 시나리오를 모든 계열에 똑같이 적용해야 한다.

## 비교 축

| 계열 | 무엇 | 이력 결손을 어떻게 받는가 |
| --- | --- | --- |
| `lookup` | 요일유형×역×시간대 평균 | 이력을 안 본다(기준선, 모든 시나리오에서 같은 값) |
| `lightgbm` | 현 배포 아티팩트(`festival_selflag_d1sd_d7_resid`) | 시차 컬럼 NaN(143 `mask_lags`) |
| `gru` | 144 아티팩트(이력 절단 증강) | 시퀀스 마스크 0 |
| `gru_no_trunc` | 144 대조군(증강 없음) | 시퀀스 마스크 0 |
| `lstm` | 셀만 LSTM으로 바꾼 1회 실험(`--model lstm`, 나머지 설정 동일) | 시퀀스 마스크 0 |

시나리오는 `masking.SCENARIOS`(`full / d7_only / d1_only / no_lag`)로 한 곳에서 정의한다. 시퀀스 쪽은
"남길 이력 일자"가 그대로 마스크가 되고, LightGBM 쪽은 그 일자에 대응하는 시차 컬럼만 남긴다:

| 시나리오 | 시퀀스 마스크 | LightGBM에서 NaN으로 만드는 열 |
| --- | --- | --- |
| `full` | 전부 | (없음) |
| `d7_only` | D−7만 | `lag1d_*`, `lagsd_*` |
| `d1_only` | D−1만 | `lag7d_*`, `lagsd_*` |
| `no_lag` | 전부 0 | `lag1d_*`, `lag7d_*`, `lagsd_*` |

`lagsd_*`(같은 요일유형 직전 날, ≤14일)는 D−1도 D−7도 아니라 시퀀스의 어느 한 날에 대응하지 않는다 —
`full`이 아닌 모든 시나리오에서 뺀다. 그래서 `d1_only`·`d7_only`의 LightGBM은 정보량이 시퀀스 쪽보다
약간 적을 수 있고, 이 비대칭은 RESULTS.md에 적어 둔다.

## 같은 행 집합

lookup 조회 실패 행, 아티팩트에 없는 역, 시차 결측으로 LightGBM이 NaN을 내는 행을 각 계열이 다르게
버리면 평균이 어긋난다. 모든 계열·시나리오의 예측이 유한한 행만 남겨(inner join) 비교한다.

## 서빙과 같은 코드

GRU는 `build_predictor("dl")` → `DLPredictor.predict(패널 창)` 그대로 부른다(파생 전 패널을 받아
내부에서 잔차·시퀀스를 만드는 프로덕션 경로). LightGBM은 파생 캐시 위에서 `CrowdPredictor.predict_derived`를
부르는데, 이건 `predict()`가 파생을 붙인 뒤 호출하는 바로 그 함수다 — 400만 행 파생을 다시 만들지 않기
위한 선택이고 계산은 동일하다(`AI/CLAUDE.md` "실험 실행 효율").

실행:
    cd AI
    python validation/CROWD/dl-resid-check/evaluate_dl.py --gru <아티팩트> --gru-no-trunc <아티팩트>
    python validation/CROWD/dl-resid-check/evaluate_dl.py --scenarios full --grades full --no-preds
예상: DL 2025 전체 추론(CPU) 계열당 2~4분, LightGBM 예측 10초, 등급 변환은 판 하나에 2~3분.
"""

from __future__ import annotations

import argparse
import json
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

from app.core.config import get_settings
from app.CROWD.pipeline.congestion import (
    apply_calibration,
    grade,
    recursive_congestion,
)
from app.CROWD.pipeline.dataset import (
    CROWD_INTERIM,
    CROWD_PROCESSED,
    load_panel,
    resolved_segments,
    time_split,
)
from app.CROWD.pipeline.dl.dataset import load_derived_slim
from app.CROWD.pipeline.features import FEATURE_SETS
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline
from app.CROWD.pipeline.masking import SCENARIOS
from app.CROWD.pipeline.predictor import build_predictor, latest_artifact
from app.CROWD.pipeline.topology import load_capacity

DEPLOY_SET = "festival_selflag_d1sd_d7_resid"
CALIBRATION_NAME = "crowd_congestion_calibration.parquet"
EVAL_START = pd.Timestamp("2025-01-01")
GRADE_THRESHOLDS = [50.0, 100.0]
CELL_KEY = ["date", "station_no", "direction", "time_slot_30min"]
OUT_DIR = CROWD_INTERIM / "validation"

# 시나리오 → LightGBM에서 NaN으로 만들 시차 컬럼 접두(143 `nolag_loss.mask_lags` 규칙의 확장)
LGB_MASK: dict[str, tuple[str, ...]] = {
    "full": (),
    "d7_only": ("lag1d_", "lagsd_"),
    "d1_only": ("lag7d_", "lagsd_"),
    "no_lag": ("lag1d_", "lag7d_", "lagsd_"),
}
# 파생 캐시에서 읽을 열 = 키·슬라이스 축·실측 + 배포 세트 피처(이미 키에 있는 범주 2열은 빼고)
DERIVED_COLS = ["date", "station_no", "line", "time_slot", "day_type", *TARGETS] + [
    c for c in FEATURE_SETS[DEPLOY_SET] if c not in ("station_no", "time_slot")
]


def _append_parquet(path: Path, frame: pd.DataFrame) -> None:
    """세트가 끝날 때마다 이어 붙인다 — 중단돼도 끝난 세트는 남는다(`AI/CLAUDE.md`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        frame = pd.concat([pd.read_parquet(path), frame], ignore_index=True)
    frame.to_parquet(path, index=False)


# ── 예측 ──
def dl_predictions(
    artifact: Path, window: pd.DataFrame, scenarios: list[str], device: str
) -> dict[str, pd.DataFrame]:
    """`build_predictor("dl")` 경로로 시나리오별 2025 예측. 반환: {시나리오: 키 + *_pred}."""
    predictor = build_predictor("dl", artifact_dir=artifact, device=device)
    out = {}
    for name in scenarios:
        t0 = time.time()
        predictor.scenario = None if name == "full" else name
        pred = predictor.predict(window, segments=[])
        pred = pred[pred["date"] >= EVAL_START]
        out[name] = pred[
            ["date", "station_no", "time_slot", *[f"{t}_pred" for t in TARGETS]]
        ].reset_index(drop=True)
        print(
            f"  [dl:{artifact.name}] {name} {len(out[name]):,}행 · {time.time() - t0:.0f}s",
            flush=True,
        )
    return out


def lgb_predictions(
    artifact: Path, test: pd.DataFrame, scenarios: list[str]
) -> dict[str, pd.DataFrame]:
    """현 배포 LightGBM 아티팩트의 시나리오별 예측(시차 컬럼 마스킹은 143 규칙)."""
    predictor = build_predictor("lightgbm", artifact_dir=artifact)
    inner = predictor._inner
    out = {}
    for name in scenarios:
        t0 = time.time()
        te = test.copy()
        cols = [c for c in FEATURE_SETS[DEPLOY_SET] if c.startswith(LGB_MASK[name])]
        if cols:
            te[cols] = np.nan
        pred = inner.predict_derived(te)
        out[name] = pred[
            ["date", "station_no", "time_slot", *[f"{t}_pred" for t in TARGETS]]
        ].reset_index(drop=True)
        print(f"  [lightgbm] {name} {len(out[name]):,}행 · {time.time() - t0:.0f}s", flush=True)
    return out


def align(test: pd.DataFrame, pred: pd.DataFrame) -> dict[str, np.ndarray]:
    """예측 프레임을 `test` 행 순서에 맞춘 {타깃: 배열}."""
    keys = ["date", "station_no", "time_slot"]
    merged = test[keys].merge(pred, on=keys, how="left")
    return {t: merged[f"{t}_pred"].to_numpy(dtype="float64") for t in TARGETS}


# ── 등급 ──
def grade_agreement(
    test: pd.DataFrame,
    boards: dict[str, dict[str, np.ndarray]],
    segments: list[dict],
    capacity: dict,
    calibration: pd.DataFrame,
) -> pd.DataFrame:
    """승하차 판마다 30분 보정 혼잡도·등급을 만들고 실측 등급과의 일치율을 낸다.

    예측 승하차 음수는 0으로 자른다(재귀식 입력은 인원). 배율표가 없는 셀(2호선 지선·공휴일 등)은
    NaN이라 분모에서 빠진다 — 88의 알려진 결측이고 채우지 않는다.
    """

    def cells(board: pd.DataFrame) -> pd.DataFrame:
        raw = recursive_congestion(board, segments, capacity)
        day_type = board[["date", "station_no", "day_type"]].drop_duplicates(["date", "station_no"])
        raw = raw.merge(day_type, on=["date", "station_no"], how="left")
        cal = apply_calibration(raw, calibration)
        cal["grade"] = grade(cal["congestion_pct_calibrated"], GRADE_THRESHOLDS)
        return cal[[*CELL_KEY, "line", "grade"]]

    truth = cells(test).rename(columns={"grade": "actual"})
    rows = []
    for name, pred in boards.items():
        board = test.copy()
        for t in TARGETS:
            board[t] = np.clip(pred[t], 0.0, None)
        got = cells(board).rename(columns={"grade": "pred"})[[*CELL_KEY, "pred"]]
        m = truth.merge(got, on=CELL_KEY, how="inner").dropna(subset=["actual", "pred"])
        rows.append(
            {
                "run": name,
                "cells": len(m),
                "등급_일치율_%": round(float((m["actual"] == m["pred"]).mean() * 100), 3),
                "보통이상_재현율_%": round(
                    float(
                        ((m["pred"] >= 1) & (m["actual"] >= 1)).sum()
                        / max(int((m["actual"] >= 1).sum()), 1)
                        * 100
                    ),
                    3,
                ),
            }
        )
        print(f"  [등급] {name}: {rows[-1]['등급_일치율_%']}% ({len(m):,}셀)", flush=True)
    return pd.DataFrame(rows)


# ── 하루치 추론 시간 ──
def time_one_day(artifact: Path, panel: pd.DataFrame, target: pd.Timestamp, device: str) -> dict:
    """운영 기준(145: 하루 10분) 대비 하루치 추론 시간. 배치와 같은 창(이력 + 대상일)을 쓴다."""
    predictor = build_predictor("dl", artifact_dir=artifact, device=device)
    days = predictor.required_history_days
    window = panel[
        (panel["date"] >= target - pd.Timedelta(days=days)) & (panel["date"] <= target)
    ].reset_index(drop=True)
    t0 = time.time()
    pred = predictor.predict(window, segments=[])
    elapsed = time.time() - t0
    rows = int((pred["date"] == target).sum())
    print(f"[추론 시간] {target:%Y-%m-%d} {rows:,}행 · {elapsed:.1f}s ({device})", flush=True)
    return {
        "artifact": artifact.name,
        "device": device,
        "target_date": str(target.date()),
        "history_days": int(days),
        "target_rows": rows,
        "seconds": round(elapsed, 2),
    }


# ── 실행 ──
def run(args) -> pd.DataFrame:
    settings = get_settings()
    models_dir = Path(settings.crowd_models_dir)
    gru = Path(args.gru) if args.gru else latest_artifact(models_dir, prefix="dl_gru_s", kind="dl")
    gru_nt = Path(args.gru_no_trunc) if args.gru_no_trunc else None
    lstm = Path(args.lstm) if args.lstm else None
    lgb = Path(args.lightgbm) if args.lightgbm else latest_artifact(models_dir, kind="lightgbm")
    scenarios = args.scenarios or list(SCENARIOS)
    metrics_path = Path(args.save_metrics)
    preds_path = Path(args.save_preds)
    for p in (metrics_path, preds_path):
        if args.fresh and p.exists():
            p.unlink()

    t0 = time.time()
    panel = load_panel(with_events=True)
    train_raw, _ = time_split(panel)
    lookup = DayTypeLookupBaseline().fit(train_raw)
    derived = load_derived_slim(columns=DERIVED_COLS)
    test = derived[derived["date"] >= EVAL_START]
    if args.eval_days:  # 스모크용 — 평가 구간을 앞쪽 N일로 자른다
        test = test[test["date"] < EVAL_START + pd.Timedelta(days=args.eval_days)]
    test = test.reset_index(drop=True)
    lookup_pred = lookup.predict(test)
    # DL 창: 평가 시작 전 seq_days만큼의 실측을 붙여 2025-01-01부터 이력이 차 있게 한다.
    window = panel[
        (panel["date"] >= EVAL_START - pd.Timedelta(days=args.window_days))
        & (panel["date"] <= test["date"].max())
    ].reset_index(drop=True)
    print(
        f"[준비] 평가 {len(test):,}행 · DL 창 {len(window):,}행 · {time.time() - t0:.0f}s",
        flush=True,
    )

    # 계열별 시나리오 예측
    series: dict[str, dict[str, pd.DataFrame]] = {}
    if lgb:
        series["lightgbm"] = lgb_predictions(lgb, test, scenarios)
    if gru:
        series["gru"] = dl_predictions(gru, window, scenarios, args.device)
    if gru_nt:
        series["gru_no_trunc"] = dl_predictions(gru_nt, window, scenarios, args.device)
    if lstm:
        series["lstm"] = dl_predictions(lstm, window, scenarios, args.device)

    aligned = {
        (name, sc): align(test, frame)
        for name, runs in series.items()
        for sc, frame in runs.items()
    }

    # 같은 행 집합 — 모든 계열·시나리오·타깃이 유한한 행만
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
    common = test[finite].reset_index(drop=True)
    common_lookup = lookup_pred[finite].reset_index(drop=True)

    rows: list[dict] = []
    # lookup 자신은 기준선이라 개선율 0 — 시나리오와 무관하게 한 번만 넣는다.
    for (name, sc), preds in aligned.items():
        cut = {t: preds[t][finite] for t in TARGETS}
        chunk = metrics_rows(common, common_lookup, cut, f"{name}|{sc}")
        for r in chunk:
            r["series"], r["scenario"] = name, sc
        rows += chunk
        tot = [r for r in chunk if r["axis"] == "전체"]
        print(
            f"[{name}|{sc}] RMSE 개선율 승 {tot[0]['RMSE_개선율_%']} / 하 {tot[1]['RMSE_개선율_%']}"
            f" · MAE {tot[0]['MAE_개선율_%']} / {tot[1]['MAE_개선율_%']}",
            flush=True,
        )
        _append_parquet(metrics_path, pd.DataFrame(chunk))

    # 예측 표본 저장 — 전체 2025를 계열×시나리오로 남기면 수백 MB라 7일 간격 날짜만 남긴다.
    if not args.no_preds:
        sample_dates = sorted(common["date"].unique())[:: args.preds_every]
        sel = common["date"].isin(sample_dates).to_numpy()
        sample = common.loc[
            sel, ["date", "station_no", "line", "time_slot", "day_type", *TARGETS]
        ].copy()
        for t in TARGETS:
            sample[f"{t}_lookup"] = common_lookup.loc[sel, t].to_numpy()
        for (name, sc), preds in aligned.items():
            for t in TARGETS:
                sample[f"{t}_{name}_{sc}"] = preds[t][finite][sel]
        preds_path.parent.mkdir(parents=True, exist_ok=True)
        sample.to_parquet(preds_path, index=False)
        print(f"[저장] 예측 표본 {len(sample):,}행 → {preds_path.name}", flush=True)

    # 등급 일치율 — 판 하나에 2~3분이라 지정한 시나리오만 돈다.
    grade_rows = []
    if args.grades:
        segments, _ = resolved_segments(common)
        capacity = load_capacity()
        calibration = pd.read_parquet(CROWD_PROCESSED / CALIBRATION_NAME)
        boards = {"lookup": {t: common_lookup[t].to_numpy(dtype="float64") for t in TARGETS}}
        for (name, sc), preds in aligned.items():
            if sc in args.grades:
                boards[f"{name}|{sc}"] = {t: preds[t][finite] for t in TARGETS}
        g = grade_agreement(common, boards, segments, capacity, calibration)
        grade_rows = g.to_dict("records")
        (metrics_path.parent / "dl_resid_grades.json").write_text(
            json.dumps(grade_rows, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    timing = None
    if gru and not args.no_timing:
        timing = time_one_day(gru, panel, pd.Timestamp(args.timing_date), "cpu")
        (metrics_path.parent / "dl_resid_timing.json").write_text(
            json.dumps(timing, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    print(f"[완료] {time.time() - t0:.0f}s · 지표 {metrics_path}", flush=True)
    return pd.DataFrame(rows)


def summarize(res: pd.DataFrame, scenarios: list[str]) -> list[tuple[str, pd.DataFrame]]:
    out = []
    tot = res[res["axis"] == "전체"]
    for metric in ("RMSE_개선율_%", "MAE_개선율_%"):
        piv = tot.pivot_table(index="series", columns=["scenario", "target"], values=metric)
        piv = piv.reindex(columns=[(s, t) for s in scenarios for t in TARGETS])
        piv.columns = [f"{s}_{t}" for s, t in piv.columns]
        out.append(
            (f"전체 — lookup 대비 {metric} (양수 = lookup보다 좋음)", piv.reset_index().round(2))
        )
    abs_piv = tot.pivot_table(index="series", columns=["scenario", "target"], values="rmse")
    abs_piv = abs_piv.reindex(columns=[(s, t) for s in scenarios for t in TARGETS])
    abs_piv.columns = [f"{s}_{t}" for s, t in abs_piv.columns]
    out.append(("전체 — 절대 RMSE(명)", abs_piv.reset_index().round(2)))
    for axis, title in (("day_type", "요일유형별"), ("line", "호선별")):
        sub = res[(res["axis"] == axis) & (res["target"] == "boarding")]
        piv = sub.pivot_table(index="group", columns=["series", "scenario"], values="RMSE_개선율_%")
        piv.columns = [f"{a}|{b}" for a, b in piv.columns]
        out.append((f"{title} RMSE 개선율(승차, %)", piv.reset_index().round(2)))
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--gru", default=None, help="models/CROWD/dl_gru_... (생략 시 최신 dl 아티팩트)"
    )
    ap.add_argument("--gru-no-trunc", default=None, help="절단 증강 없는 대조군 아티팩트")
    ap.add_argument(
        "--lstm", default=None, help="셀만 LSTM으로 바꾼 1회 실험 아티팩트(계획 보정 7)"
    )
    ap.add_argument("--lightgbm", default=None, help="비교할 LightGBM 아티팩트(생략 시 최신)")
    ap.add_argument(
        "--scenarios", default=None, type=lambda s: s.split(","), help=f"{','.join(SCENARIOS)}"
    )
    ap.add_argument("--device", default="cpu", help="DL 추론 장치(기본 cpu = 서빙과 같은 조건)")
    ap.add_argument("--window-days", type=int, default=14)
    ap.add_argument(
        "--eval-days", type=int, default=None, help="평가 구간을 2025 앞쪽 N일로(스모크)"
    )
    ap.add_argument("--grades", default="full", type=lambda s: [x for x in s.split(",") if x])
    ap.add_argument("--no-preds", action="store_true")
    ap.add_argument("--preds-every", type=int, default=7, help="예측 표본으로 남길 날짜 간격(일)")
    ap.add_argument("--no-timing", action="store_true")
    ap.add_argument("--timing-date", default="2025-06-02")
    ap.add_argument("--fresh", action="store_true", help="기존 결과 파일을 지우고 새로 쌓는다")
    ap.add_argument("--save-metrics", default=str(OUT_DIR / "dl_resid_metrics.parquet"))
    ap.add_argument("--save-preds", default=str(OUT_DIR / "dl_resid_preds.parquet"))
    ap.add_argument("--out", default=None, help="요약 표를 마크다운으로 저장할 경로")
    args = ap.parse_args(argv)

    res = run(args)
    chunks = []
    for title, tbl in summarize(res, args.scenarios or list(SCENARIOS)):
        print(f"\n### {title}\n{tbl.to_string(index=False)}")
        chunks.append(f"### {title}\n\n{to_markdown(tbl)}\n")
    if args.out:
        Path(args.out).write_text("\n".join(chunks), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
