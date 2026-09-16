"""`calibration_holdout.ipynb`을 생성·실행(출력 포함)하는 1회성 스크립트(142 1단계).

셀 목록을 코드로 관리하는 136·144·198의 방식을 그대로 따른다. 노트북 자체가 산출물이고
**출력은 지우지 않는다**(`AI/CLAUDE.md`). `holdout.py`가 남긴 지표·셀 parquet을 다시 읽어
표와 그림으로만 보여준다 — 재계산하지 않는다.

실행:
    cd AI
    python validation/CROWD/calibration-holdout/_build_notebook.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import nbformat as nbf
from nbclient import NotebookClient

HERE = Path(__file__).resolve().parent
AI_ROOT = HERE.parents[2]

PAIRS = ((2023, 2024), (2024, 2025))


def build(pairs: tuple[tuple[int, int], ...]) -> nbf.NotebookNode:
    nb = nbf.v4.new_notebook()
    cells = []

    cells.append(nbf.v4.new_markdown_cell("""# 142 1단계 — 배율표 연도 홀드아웃

수치 원본은 같은 폴더의 [`RESULTS.md`](./RESULTS.md)이고, 어긋나면 그쪽이 맞다. 이 노트북은
`holdout.py`가 남긴 parquet을 **표·그림으로만** 다시 읽는다.

질문 하나다 — 146 §4-B가 인정한 순환 참조(배율표의 분자가 그 스냅샷 자체)를 끊으면
변환 층은 얼마나 맞히나.

    배율표 = A연도 스냅샷 ÷ A연도 재귀식 raw 평균   →   예측(B) = 배율표 × B연도 재귀식 raw 평균

식을 펴면 `예측(B) = 스냅샷(A) × raw평균(B)/raw평균(A)`다. 파이프라인이 전년도 표에 얹는 것은
**연도 변화율 하나**이고, 대조군 `copy_prev`는 그 변화율을 1로 두는 안이다."""))

    cells.append(
        nbf.v4.new_code_cell(
            """import sys
from pathlib import Path

AI_ROOT = Path.cwd()
while not (AI_ROOT / "app" / "CROWD").exists():
    AI_ROOT = AI_ROOT.parent
sys.path.insert(0, str(AI_ROOT))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from DATA_ENGINE.eda import figstyle

figstyle.apply(inline=True)
VALID = AI_ROOT / "data" / "CROWD" / "interim" / "validation"
PAIRS = """
            + repr([list(p) for p in pairs])
            + """
METHODS = ["pipeline", "copy_prev", "scale_only", "scale_const"]

metrics = pd.concat(
    [pd.read_parquet(VALID / f"calibration_holdout_{a}_{b}.parquet") for a, b in PAIRS],
    ignore_index=True,
)
cells = {
    (a, b): pd.read_parquet(VALID / f"calibration_holdout_cells_{a}_{b}.parquet") for a, b in PAIRS
}
print({k: len(v) for k, v in cells.items()})
metrics.head()"""
        )
    )

    cells.append(nbf.v4.new_markdown_cell("""## 1. 전체 — 네 안 비교

`pipeline`(셀별 배율) · `copy_prev`(전년도 표 복사) · `scale_only`·`scale_const`
(방향×요일유형×30분당 계수 1~2개짜리 거친 적합, 146 §4-C와 같은 형태)."""))

    cells.append(nbf.v4.new_code_cell("""total = (
    metrics[metrics["axis"] == "전체"]
    .set_index(["fit_year", "eval_year", "method"])
    .loc[:, ["n", "mae", "rmse", "corr", "grade_agree_%"]]
)
total.round(3)"""))

    cells.append(nbf.v4.new_code_cell("""fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
for ax, (value, label) in zip(axes, [("mae", "셀 MAE (%p, 낮을수록 좋다)"), ("grade_agree_%", "등급 일치율 (%, 높을수록 좋다)")]):
    piv = (
        metrics[metrics["axis"] == "전체"]
        .assign(pair=lambda d: d["fit_year"].astype(str) + "→" + d["eval_year"].astype(str))
        .pivot_table(index="pair", columns="method", values=value)
        .reindex(columns=METHODS)
    )
    piv.plot.bar(ax=ax, rot=0, width=0.78, color=figstyle.PALETTE_NEUTRAL[: len(METHODS)])
    ax.set_title(label)
    ax.set_xlabel("")
    ax.legend(fontsize=8)
fig.suptitle("연도 홀드아웃 — 전체", fontsize=12)
fig.tight_layout()"""))

    cells.append(nbf.v4.new_markdown_cell("""## 2. 파이프라인 vs 전년도 표 복사 — 슬라이스

두 쌍의 전체 부호가 반대다(2023→2024 파이프라인 우세, 2024→2025 열세). 어느 슬라이스가
그 차이를 만드는지 본다."""))

    cells.append(nbf.v4.new_code_cell("""def slice_table(axis, value):
    sub = metrics[(metrics["axis"] == axis) & (metrics["method"].isin(["pipeline", "copy_prev"]))]
    piv = sub.pivot_table(index="group", columns=["fit_year", "method"], values=value)
    for a, b in PAIRS:
        piv[(a, "Δ")] = piv[(a, "pipeline")] - piv[(a, "copy_prev")]
    return piv.sort_index(axis=1).round(3)


slice_table("호선", "mae")"""))

    cells.append(nbf.v4.new_code_cell("""slice_table("요일유형", "mae")"""))

    cells.append(nbf.v4.new_code_cell("""slice_table("방향", "grade_agree_%")"""))

    cells.append(nbf.v4.new_markdown_cell("""## 3. 원천 불연속이 범인이다

셀을 역 단위 **연간 승하차 총량 변화**로 3분류했다 — ±25%를 넘게 변한 역(개통·집계 정의 변화),
그 역과 같은 호선의 다른 역(재귀식은 노선을 따라 누적하므로 오차가 옆으로 번진다), 나머지."""))

    cells.append(nbf.v4.new_code_cell("""cont = (
    metrics[(metrics["axis"] == "원천 연속성") & (metrics["method"].isin(["pipeline", "copy_prev"]))]
    .pivot_table(index=["fit_year", "group"], columns="method", values=["n", "mae", "grade_agree_%"])
)
cont.round(3)"""))

    cells.append(
        nbf.v4.new_code_cell(
            """fig, axes = plt.subplots(1, len(PAIRS), figsize=(11, 3.8), sharey=True)
order = ["연속", "불연속 호선의 다른 역", "불연속 역"]
for ax, (a, b) in zip(np.atleast_1d(axes), PAIRS):
    sub = metrics[
        (metrics["axis"] == "원천 연속성")
        & (metrics["fit_year"] == a)
        & (metrics["method"].isin(["pipeline", "copy_prev"]))
    ]
    piv = sub.pivot_table(index="group", columns="method", values="mae").reindex(order)
    piv.plot.bar(ax=ax, rot=12, width=0.72, color=figstyle.PALETTE_NEUTRAL[:2])
    ax.set_title(f"{a}→{b}")
    ax.set_xlabel("")
    ax.set_ylabel("셀 MAE (%p)")
fig.suptitle("원천이 끊긴 역에서만 파이프라인이 크게 진다", fontsize=12)
fig.tight_layout()"""
        )
    )

    cells.append(nbf.v4.new_code_cell("""top = cells[(2024, 2025)].assign(
    err=lambda d: (d["pred_pipeline"] - d["truth"]).abs(),
    변화율=lambda d: d["raw_eval"] / d["raw_fit"],
).nlargest(10, "err")
top[
    [
        "line",
        "station_no",
        "direction",
        "day_type",
        "time_slot_30min",
        "truth",
        "snap_fit",
        "변화율",
        "pred_pipeline",
        "err",
    ]
].round(2)"""))

    cells.append(nbf.v4.new_markdown_cell("""## 4. 예측–정답 산점도

`pipeline`이 정답(그 해 스냅샷)을 얼마나 따라가는지. 붉은 점이 원천 불연속 역이다."""))

    cells.append(
        nbf.v4.new_code_cell(
            """fig, axes = plt.subplots(1, len(PAIRS), figsize=(10, 4.6), sharex=True, sharey=True)
for ax, (a, b) in zip(np.atleast_1d(axes), PAIRS):
    c = cells[(a, b)]
    ok = c["source_continuity"] == "연속"
    ax.scatter(c.loc[ok, "truth"], c.loc[ok, "pred_pipeline"], s=2, alpha=0.15, color="#3f6fb5")
    ax.scatter(c.loc[~ok & (c["source_continuity"] == "불연속 역"), "truth"],
               c.loc[~ok & (c["source_continuity"] == "불연속 역"), "pred_pipeline"],
               s=6, alpha=0.7, color="#d1495b", label="불연속 역")
    lim = [0, 220]
    ax.plot(lim, lim, lw=1, color="#444", ls="--")
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_title(f"{a} 적합 → {b} 평가")
    ax.set_xlabel(f"{b} 공식 스냅샷 (%p)")
    ax.legend(fontsize=8, loc="upper left")
np.atleast_1d(axes)[0].set_ylabel("파이프라인 예측 (%p)")
fig.tight_layout()"""
        )
    )

    cells.append(nbf.v4.new_markdown_cell("""## 5. 읽은 것

판정 문장은 [`RESULTS.md`](./RESULTS.md) 5절이 원본이다. 그림에서 바로 보이는 것만 적으면:

1. **거친 적합(`scale_only`·`scale_const`)은 셀별 배율의 5~6배 나쁘다.** 역 단위 자유도가
   배율표의 핵심이고, 배율표를 단순화하자는 안(199)은 이 수치를 기준선으로 삼아야 한다.
   상수항은 두 쌍 모두 스케일-only를 이긴다 — 146 §4-C의 "경계 유입이 실재한다"가 전 호선에서 재확인된다.
2. **연속 구간에서는 파이프라인이 근소 우세**(등급 +0.14 / +0.44%p)이고, 전체 부호를 뒤집는 것은
   0.76%에 불과한 **불연속 역 464셀**이다(8호선 암사역사공원 2024-08 개통, 1호선 서울역 +32%).
3. **공식 스냅샷은 해마다 거의 안 움직인다**(`copy_prev` MAE 1.26~2.46%p). 이길 여지 자체가 작다 —
   그래서 판정은 "이기지 못함 → 공식표 재현 수준으로 서술"이다.
4. 산점도의 붉은 점은 전부 대각선 **위쪽**에 있다. 파이프라인이 승하차 증가를 그대로 밀어 올리는데
   공식표는 따라오지 않았다 — 141이 남긴 서울역 집계 정의 변화 의심과 같은 방향이다."""))

    nb["cells"] = cells
    nb.metadata["kernelspec"] = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    return nb


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(HERE / "calibration_holdout.ipynb"))
    args = ap.parse_args()
    nb = build(PAIRS)
    NotebookClient(nb, timeout=600, resources={"metadata": {"path": str(AI_ROOT)}}).execute()
    nbf.write(nb, args.out)
    print(f"[노트북] 저장(출력 포함): {args.out}")


if __name__ == "__main__":
    main()
