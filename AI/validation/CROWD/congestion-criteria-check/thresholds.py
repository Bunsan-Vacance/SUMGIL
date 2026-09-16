"""146 4단계 — 등급 임계값 후보 3개의 2025 등급 분포·실측 일치율 표. **기본값은 바꾸지 않는다.**

임계값 확정은 팀 논의 A-2의 결정 사항이라(계획 보정 1) 여기서는 판단 재료만 만든다. 코드는 이미
임계값을 설정으로만 받으므로(`CROWD_GRADE_THRESHOLDS`), 결정이 나면 기본값 한 줄과 API 문구만
바꾸면 된다 — 그 반영은 이 티켓 범위 밖이다.

## 입력을 다시 계산하지 않는다

90번 `validation/CROWD/baseline-check/grade_sensitivity.py --save-cells`가 만들어 둔
`data/CROWD/interim/validation/grade_cells.parquet`(2025 셀 764만 개 × 실측/lookup/모델 보정 혼잡도)를
그대로 읽는다. 같은 계산을 두 번 하지 않는다(`AI/CLAUDE.md` 실험 실행 효율) — 재생성이 필요하면
그 스크립트를 다시 돌린다(학습 포함 10분대).

"실측"은 **2025 실측 승하차를 같은 변환기에 넣은 값**이지 스냅샷이 아니다 — 등급 일치율은
"승하차 예측 오차가 등급을 흔드는가"를 보는 축이다.

실행(약 30초):
    cd AI
    python validation/CROWD/congestion-criteria-check/thresholds.py --out thresholds_draft.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[2]
for p in (str(AI_ROOT), str(AI_ROOT / "validation" / "CROWD" / "baseline-check")):
    if p not in sys.path:
        sys.path.insert(0, p)

from evaluate_final import to_markdown

from app.CROWD.pipeline.congestion import grade
from app.CROWD.pipeline.dataset import CROWD_INTERIM

CELLS_PATH = CROWD_INTERIM / "validation" / "grade_cells.parquet"

# 계획에 고정된 후보 3개. 국토부 고시(150/170/190)는 90에서 판별력 없음이 확인돼(99.6%가 한 등급)
# 후보에서 빠졌고, 대신 고시의 첫 경계를 살린 80/130/150이 들어왔다.
CANDIDATES = {
    "현행 50/100": [50.0, 100.0],
    "분포3 50/80/100": [50.0, 80.0, 100.0],
    "완화3 80/130/150": [80.0, 130.0, 150.0],
}


def distribution_rows(cells: pd.DataFrame) -> list[dict]:
    rows = []
    for name, ths in CANDIDATES.items():
        g = grade(cells["actual"], ths)
        share = g.value_counts(normalize=True).sort_index() * 100
        row: dict = {"임계값": name, "등급수": len(ths) + 1}
        for i in range(len(ths) + 1):
            row[f"등급{i}_%"] = round(float(share.get(float(i), 0.0)), 3)
        rows.append(row)
    return rows


def agreement_rows(cells: pd.DataFrame) -> list[dict]:
    rows = []
    for name, ths in CANDIDATES.items():
        g_a, g_l, g_m = (grade(cells[c], ths) for c in ("actual", "lookup", "model"))
        changed = g_l != g_m
        improved = changed & (g_m == g_a)
        worsened = changed & (g_l == g_a)
        rows.append(
            {
                "임계값": name,
                "등급수": len(ths) + 1,
                "최저등급_비율_%": round(float((g_a == 0).mean() * 100), 2),
                "최고등급_비율_%": round(float((g_a == len(ths)).mean() * 100), 4),
                "lookup_일치율_%": round(float((g_l == g_a).mean() * 100), 3),
                "모델_일치율_%": round(float((g_m == g_a).mean() * 100), 3),
                "전달폭_%p": round(float(((g_m == g_a).mean() - (g_l == g_a).mean()) * 100), 3),
                "등급_바뀐_셀_%": round(float(changed.mean() * 100), 3),
                "바뀐_중_개선_%": round(
                    float(improved.sum() / max(int(changed.sum()), 1) * 100), 1
                ),
                "바뀐_중_악화_%": round(
                    float(worsened.sum() / max(int(changed.sum()), 1) * 100), 1
                ),
            }
        )
    return rows


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--cells", default=str(CELLS_PATH))
    ap.add_argument("--out", default=str(_HERE / "thresholds_draft.md"))
    args = ap.parse_args(argv)

    path = Path(args.cells)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} 가 없다 — validation/CROWD/baseline-check/grade_sensitivity.py --save-cells 로 먼저 만든다"
        )
    cells = pd.read_parquet(path, columns=["date", "line", "actual", "lookup", "model"])
    print(
        f"[입력] {len(cells):,}셀 · {cells['date'].min():%Y-%m-%d}~{cells['date'].max():%Y-%m-%d} · "
        f"실측 보정 혼잡도 중위 {np.median(cells['actual']):.1f}%",
        flush=True,
    )

    chunks: list[str] = []

    def emit(title: str, frame: pd.DataFrame) -> None:
        print(f"\n### {title}", flush=True)
        print(frame.to_string(index=False), flush=True)
        chunks.append(f"### {title}\n\n{to_markdown(frame)}\n")

    emit("4-A. 후보별 2025 등급 분포(실측 승하차 기준)", pd.DataFrame(distribution_rows(cells)))
    emit("4-B. 후보별 실측 등급 일치율", pd.DataFrame(agreement_rows(cells)))

    Path(args.out).write_text("\n".join(chunks), encoding="utf-8")
    print(f"\n[저장] {args.out}")


if __name__ == "__main__":
    main(sys.argv[1:])
