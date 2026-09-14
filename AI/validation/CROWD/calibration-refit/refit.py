"""199 — 배율표 재적합. 후보를 만들고 `judges.py`의 세 심판으로 채점해 표를 찍는다.

## 단계

| 단계 | 질문 | 후보 |
| --- | --- | --- |
| A | 2호선 지선 546셀/일을 살릴 수 있나 | A3 현행 / **A1 방향 대응표 적용** / (A2 라벨 재정의는 A1 실패 시만) |
| C | 적합 창을 바꿔야 하나 | C1 전체(현행) / C2 스냅샷 연도 / C3 기준일 ±13주 |

B(절단면 경계 셀)는 다음 커밋에서 같은 틀에 붙는다.

채택 규칙은 계획(`.claude/plans/S15P21A104-199-calibration-refit.md`)에 **사전 고정**돼 있고,
판정 문장과 규칙 대비 ○×는 같은 폴더 `RESULTS.md`에 적는다.

실행(전체 5~8분 — 재귀식 raw 평균은 `interim/validation/`에 캐시된다):
    cd AI
    python validation/CROWD/calibration-refit/refit.py --stage all --out RESULTS_draft.md
    python validation/CROWD/calibration-refit/refit.py --stage a      # 단계 하나만
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[2]
for _p in (str(_HERE), str(AI_ROOT), str(AI_ROOT / "validation" / "CROWD" / "baseline-check")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import judges
from evaluate_final import to_markdown
from holdout import HoldoutVariant

from app.core.config import get_settings
from app.CROWD.pipeline.calendar import load_holidays
from app.CROWD.pipeline.dataset import (
    CROWD_INTERIM,
    CROWD_PROCESSED,
    EVENTS_NAME,
    load_panel,
    resolved_segments,
)
from app.CROWD.pipeline.predictor import build_predictor
from app.CROWD.pipeline.topology import load_capacity
from DATA_ENGINE.eda.build_congestion_calibration import (
    CalibrationVariant,
    build_calibration_ratio,
)

STORE = CROWD_INTERIM / "validation"

# 배율표 후보 — 이름이 RESULTS의 행 이름이다.
BASE = CalibrationVariant.current()
A1 = CalibrationVariant()

CALIBRATION_CANDIDATES: dict[str, CalibrationVariant] = {
    "A3 현행(88)": BASE,
    "A1 지선 방향 대응": A1,
    "C2 스냅샷 연도": CalibrationVariant(fit_window="snapshot_year"),
    "C3 기준일 ±13주": CalibrationVariant(fit_window="snapshot_season"),
}

HOLDOUT_CANDIDATES: dict[str, HoldoutVariant] = {
    "A3 현행(88)": HoldoutVariant(branch_map=False),
    "A1 지선 방향 대응": HoldoutVariant(branch_map=True),
    "C1 전체 평균(현행 구조)": HoldoutVariant(fit_window="multi"),
    "C2 스냅샷 연도": HoldoutVariant(fit_window="year"),
    "C3 기준일 ±13주": HoldoutVariant(fit_window="season"),
}

STAGE_CALIBRATION = {
    "a": ["A3 현행(88)", "A1 지선 방향 대응"],
    "c": ["A1 지선 방향 대응", "C2 스냅샷 연도", "C3 기준일 ±13주"],
}
STAGE_HOLDOUT = {
    "a": ["A3 현행(88)", "A1 지선 방향 대응"],
    "c": ["C2 스냅샷 연도", "C1 전체 평균(현행 구조)", "C3 기준일 ±13주"],
}


def build_tables(names: list[str]) -> dict[str, pd.DataFrame]:
    """후보 이름 → 배율표."""
    tables: dict[str, pd.DataFrame] = {}
    for name in names:
        t0 = time.time()
        tables[name], _ = build_calibration_ratio(variant=CALIBRATION_CANDIDATES[name])
        print(f"[표] {name}: {len(tables[name]):,}행 · {time.time() - t0:.0f}s", flush=True)
    return tables


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--stage", default="all", choices=("a", "c", "all"))
    ap.add_argument("--out", default=str(_HERE / "RESULTS_draft.md"))
    ap.add_argument("--skip-status", action="store_true", help="③ data_status 단계를 건너뛴다")
    args = ap.parse_args(argv)

    stages = ["a", "c"] if args.stage == "all" else [args.stage]
    chunks: list[str] = []

    def emit(title: str, frame: pd.DataFrame, index: bool = False) -> None:
        print(f"\n### {title}", flush=True)
        print(frame.to_string(index=index), flush=True)
        chunks.append(f"### {title}\n\n{to_markdown(frame.reset_index() if index else frame)}\n")

    # 현행(88) 표는 언제나 만든다 — 등급 심판이 raw를 복원하는 분모이자 모든 표의 기준행이다.
    cal_names = sorted(
        {"A3 현행(88)"} | {n for s in stages for n in STAGE_CALIBRATION[s]}, key=_order
    )
    hold_names = sorted({n for s in stages for n in STAGE_HOLDOUT[s]}, key=_order)
    tables = build_tables(cal_names)

    # ① 홀드아웃
    scores = judges.holdout_scores({n: HOLDOUT_CANDIDATES[n] for n in hold_names})
    scores.to_parquet(STORE / "calibration_refit_holdout.parquet", index=False)
    emit("①-A. 홀드아웃 전체(pipeline) — 안 × 연도 쌍", judges.holdout_summary(scores), index=True)
    emit("①-B. 호선별 MAE·등급", judges.holdout_axis(scores, "호선"), index=True)
    emit("①-C. 경계 셀", judges.holdout_axis(scores, "경계 셀"), index=True)

    # ② 2025 등급 일치율
    cells, dropped = judges.load_grade_cells(tables["A3 현행(88)"])
    print(f"[등급 셀] {len(cells):,} (배율 0·결측이라 뺀 셀 {dropped:,})", flush=True)
    emit(
        "②. 2025 등급 일치율(50/100) — 배율만 갈아끼운 재계산",
        judges.grade_agreement(cells, tables),
    )
    del cells

    # 표 자체의 변화
    emit("표-A. `ratio` 결측 셀(호선별, 요일유형 3종 합)", judges.nan_by_line(tables))
    for name, table in tables.items():
        if name == "A3 현행(88)":
            continue
        emit(
            f"표-B. 기존에 값이 있던 셀의 배율 변화 — {name}",
            judges.ratio_change(tables["A3 현행(88)"], table),
        )
    for name, table in tables.items():
        share = judges.offset_share(table)
        if len(share):
            emit(f"표-C. 경계 상수가 raw에서 차지하는 비중 — {name}", share)

    # ③ data_status
    if not args.skip_status:
        t0 = time.time()
        settings = get_settings()
        panel = load_panel(with_events=True)
        holidays = load_holidays()
        events_path = CROWD_PROCESSED / EVENTS_NAME
        events = pd.read_parquet(events_path) if events_path.exists() else None
        segments, _ = resolved_segments(panel)
        capacity = load_capacity()
        predictor = build_predictor("lookup", train_panel=panel)
        dist = judges.status_distribution(
            tables,
            panel,
            segments,
            capacity,
            holidays,
            events,
            settings.grade_thresholds,
            predictor,
        )
        dist.to_parquet(STORE / "calibration_refit_status.parquet", index=False)
        emit("③. 기준일 3일 `data_status` 분포", dist)
        print(f"[data_status] {time.time() - t0:.0f}s", flush=True)

    Path(args.out).write_text("\n".join(chunks), encoding="utf-8")
    print(f"\n[저장] {args.out}")


def _order(name: str) -> tuple[int, str]:
    """표에서 현행이 항상 맨 위에 오도록."""
    return (0 if name.startswith("A3") else 1, name)


if __name__ == "__main__":
    main(sys.argv[1:])
