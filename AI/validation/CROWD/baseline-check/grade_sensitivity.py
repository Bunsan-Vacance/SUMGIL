"""90번 — 승하차 예측 개선이 **혼잡도 등급**을 실제로 움직이는가.

87 6절이 남긴 질문이다: "RMSE 3명 개선이 서비스에서 의미가 있는지는 승하차 기준으로는 판단할
수 없다 — 혼잡도로 변환해 등급 경계가 움직이는지 봐야 한다." 89·90에서 개선폭이 20%대로
커졌으니 이제 답을 낼 수 있다.

## 방법

2025년 평가 구간에 대해 승하차 판을 세 벌 만든다 — **실측**, **lookup 예측**, **최종 모델 예측**
(D−1 배포 세트 `festival_selflag_d1d7_resid`). 각 판을 같은 변환기에 넣는다.

    승하차 → 재귀식 방향별 재차인원(`build_congestion_label._segment_frame`)
          → 배율표 적용 30분 보정 혼잡도(`build_congestion_label_calibrated.apply_calibration`)
          → 임계치로 등급

그리고 (date, station_no, direction, 30분) 셀마다 **실측 등급과 일치하는 비율**을 lookup·모델에
대해 비교한다. 모델이 lookup보다 일치율이 높으면 승하차 개선이 등급까지 전달된 것이다.
등급이 갈린 셀에서 모델이 실측 쪽으로 옮긴 비율(개선)과 반대로 옮긴 비율(악화)도 낸다.

## 임계치 후보 (팀 논의 A-2 미확정 — 민감도만 낸다)

- `국토부`: 150 / 170 / 190 (고시 제2023-414호 4단계). 1~8호선 보정 혼잡도의 99.94%가 150 미만
  이라 사실상 한 등급이다.
- `분포`: 50 / 100 (중앙값 28, 90분위 60, 99분위 108 — 100%는 좌석+입석 정원).
- `분포3`: 50 / 80 / 100.

## 주의

- 예측 승하차가 음수면 0으로 자른다(재귀식 입력은 인원이라 음수가 없다). 자른 셀 수를 보고한다.
- 재귀식은 세그먼트별 전체 패널 pivot이라 한 판에 2~3분 걸린다. 세 판이면 10분 안쪽.
- 9호선은 2024~2025 패널에 없어 제외(1~8호선). 2호선 지선·공휴일 등 배율표가 없는 셀은 NaN으로
  빠진다(88의 알려진 결측) — 분모에서 제외하고 개수를 보고한다.

실행:
    cd AI
    python validation/CROWD/baseline-check/grade_sensitivity.py [--params '{"num_leaves":63}'] [--out path.md]
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
for p in (str(_HERE), str(AI_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from evaluate_final import to_markdown

from app.CROWD.pipeline.dataset import (
    CROWD_PROCESSED,
    load_or_build_derived,
    load_panel,
    resolved_segments,
    time_split,
)
from app.CROWD.pipeline.features import build_matrix
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline
from app.CROWD.pipeline.train import train_models
from DATA_ENGINE.eda.build_congestion_label import _segment_frame, load_capacity
from DATA_ENGINE.eda.build_congestion_label_calibrated import apply_calibration

# D-1 배포 세트. 전부 세트를 실시간 컬럼 NaN으로 서빙하면 +4~8%에 그쳐(evaluate_final 1절) 시차
# 전용 세트가 배포 세트다.
DEPLOY_SET = "festival_selflag_d1d7_resid"
CALIBRATION_NAME = "crowd_congestion_calibration.parquet"

THRESHOLDS = {
    "국토부(150/170/190)": [150, 170, 190],
    "분포(50/100)": [50, 100],
    "분포3(50/80/100)": [50, 80, 100],
}
CELL_KEY = ["date", "station_no", "direction", "time_slot_30min"]


def recursive_congestion(panel: pd.DataFrame, segments: list[dict], capacity: dict) -> pd.DataFrame:
    """승하차 판 → 재귀식 raw 혼잡도(1시간·방향별)."""
    cols = ["date", "station_no", "time_slot", "boarding", "alighting"]
    frame = panel[cols].copy()
    frame[["boarding", "alighting"]] = frame[["boarding", "alighting"]].fillna(0.0)
    frames = [f for seg in segments if (f := _segment_frame(frame, seg, capacity)) is not None]
    return pd.concat(frames, ignore_index=True)


def calibrated_congestion(raw_labels: pd.DataFrame, calibration: pd.DataFrame) -> pd.DataFrame:
    """raw → 30분 보정 혼잡도. 셀 키 + congestion_pct_calibrated만 남긴다."""
    cal = apply_calibration(raw_labels, calibration)
    return cal[[*CELL_KEY, "line", "congestion_pct_calibrated"]]


def grade(values: pd.Series, thresholds: list[float]) -> pd.Series:
    """임계치 목록으로 0..len 등급. NaN은 NaN 유지."""
    out = pd.Series(
        np.searchsorted(np.asarray(thresholds), values.to_numpy(), side="right"),
        index=values.index,
        dtype="float",
    )
    out[values.isna()] = np.nan
    return out


def replace_targets(test: pd.DataFrame, pred: dict[str, np.ndarray]) -> tuple[pd.DataFrame, int]:
    """평가 패널의 승하차를 예측값으로 바꾼다. 음수는 0으로 자르고 자른 셀 수를 돌려준다."""
    out = test.copy()
    clipped = 0
    for t in TARGETS:
        v = np.asarray(pred[t], dtype=float)
        clipped += int((v < 0).sum())
        out[t] = np.clip(v, 0.0, None)
    return out, clipped


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--params", default=None, help="LightGBM 파라미터 JSON(그리드 결과 반영용)")
    ap.add_argument("--out", default=None)
    ap.add_argument(
        "--save-cells",
        default=None,
        help="셀 표(actual/lookup/model 혼잡도)를 parquet로 저장 — 136 그림 입력",
    )
    args = ap.parse_args(argv)
    params = json.loads(args.params) if args.params else None
    chunks: list[str] = []

    def emit(title: str, frame: pd.DataFrame) -> None:
        print(f"\n### {title}", flush=True)
        print(frame.to_string(index=False), flush=True)
        chunks.append(f"### {title}\n\n{to_markdown(frame)}\n")

    # 1. 학습 → 2025 예측 (D−1 서빙: 실시간 컬럼 NaN)
    panel = load_panel(with_events=True)
    train_raw, _ = time_split(panel)
    lookup = DayTypeLookupBaseline().fit(train_raw)
    derived = load_or_build_derived(panel, lookup)
    train, test = time_split(derived)
    t0 = time.time()
    models = train_models(train, lookup, DEPLOY_SET, params)
    X_test = build_matrix(test, DEPLOY_SET)  # 시차 전용 세트라 실시간 컬럼이 없다
    lookup_pred = lookup.predict(test)
    model_pred = {
        t: lookup_pred[t].to_numpy() + models[t]["__all__"].predict(X_test) for t in TARGETS
    }
    print(f"[학습·예측] {time.time() - t0:.0f}s", flush=True)

    actual_panel = test
    lookup_panel, clipped_l = replace_targets(test, {t: lookup_pred[t].to_numpy() for t in TARGETS})
    model_panel, clipped_m = replace_targets(test, model_pred)
    print(
        f"[음수 클립] lookup {clipped_l:,}셀, 모델 {clipped_m:,}셀 / {len(test) * 2:,}", flush=True
    )

    # 2. 세 판 → 보정 혼잡도
    segments, _ = resolved_segments(panel)
    capacity = load_capacity()
    calibration = pd.read_parquet(CROWD_PROCESSED / CALIBRATION_NAME)
    boards = {}
    for name, pnl in (("실측", actual_panel), ("lookup", lookup_panel), ("모델", model_panel)):
        t0 = time.time()
        boards[name] = calibrated_congestion(
            recursive_congestion(pnl, segments, capacity), calibration
        )
        print(f"[재귀식+배율] {name}: {len(boards[name]):,}셀, {time.time() - t0:.0f}s", flush=True)

    merged = boards["실측"].rename(columns={"congestion_pct_calibrated": "actual"})
    for name, col in (("lookup", "lookup"), ("모델", "model")):
        merged = merged.merge(
            boards[name][[*CELL_KEY, "congestion_pct_calibrated"]].rename(
                columns={"congestion_pct_calibrated": col}
            ),
            on=CELL_KEY,
            how="inner",
        )
    valid = merged.dropna(subset=["actual", "lookup", "model"])
    print(f"[셀] 전체 {len(merged):,}, 배율 있는 셀 {len(valid):,}", flush=True)
    if args.save_cells:
        Path(args.save_cells).parent.mkdir(parents=True, exist_ok=True)
        valid[[*CELL_KEY, "line", "actual", "lookup", "model"]].to_parquet(
            args.save_cells, index=False
        )
        print(f"[저장] {args.save_cells}", flush=True)

    # 3. 혼잡도 % 자체의 오차 (등급 전 단계)
    rows = []
    for col in ("lookup", "model"):
        err = valid[col] - valid["actual"]
        rows.append(
            {
                "예측": col,
                "RMSE_%p": round(float(np.sqrt((err**2).mean())), 2),
                "MAE_%p": round(float(err.abs().mean()), 2),
            }
        )
    emit("A. 보정 혼잡도(%) 오차 — 실측 승하차로 만든 혼잡도 대비", pd.DataFrame(rows))

    # 4. 등급 일치율
    rows = []
    for name, ths in THRESHOLDS.items():
        g_a = grade(valid["actual"], ths)
        g_l = grade(valid["lookup"], ths)
        g_m = grade(valid["model"], ths)
        changed = g_l != g_m
        improved = changed & (g_m == g_a)
        worsened = changed & (g_l == g_a)
        rows.append(
            {
                "임계치": name,
                "등급수": len(ths) + 1,
                "실측_최저등급_비율_%": round(float((g_a == 0).mean() * 100), 2),
                "lookup_일치율_%": round(float((g_l == g_a).mean() * 100), 3),
                "모델_일치율_%": round(float((g_m == g_a).mean() * 100), 3),
                "등급_바뀐_셀_%": round(float(changed.mean() * 100), 3),
                "바뀐_중_개선_%": round(float(improved.sum() / max(changed.sum(), 1) * 100), 1),
                "바뀐_중_악화_%": round(float(worsened.sum() / max(changed.sum(), 1) * 100), 1),
            }
        )
    emit("B. 등급 일치율 — 임계치 후보별", pd.DataFrame(rows))

    # 5. 분포(50/100) 기준 호선별
    ths = THRESHOLDS["분포(50/100)"]
    g_a, g_l, g_m = (grade(valid[c], ths) for c in ("actual", "lookup", "model"))
    per_line = (
        pd.DataFrame({"line": valid["line"], "l": (g_l == g_a), "m": (g_m == g_a), "hi": g_a >= 1})
        .groupby("line")
        .agg(
            n=("l", "size"),
            lookup_일치율=("l", "mean"),
            모델_일치율=("m", "mean"),
            실측_보통이상_비율=("hi", "mean"),
        )
        .reset_index()
    )
    for c in ("lookup_일치율", "모델_일치율", "실측_보통이상_비율"):
        per_line[c] = (per_line[c] * 100).round(2)
    emit("C. 호선별 등급 일치율 (분포 50/100)", per_line)

    if args.out:
        Path(args.out).write_text("\n".join(chunks), encoding="utf-8")
        print(f"\n[저장] {args.out}")


if __name__ == "__main__":
    main(sys.argv[1:])
