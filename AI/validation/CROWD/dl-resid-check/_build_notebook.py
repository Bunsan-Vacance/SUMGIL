"""`dl_resid_check.ipynb`을 생성·실행(출력 포함)하는 1회성 스크립트(144).

노트북 파일을 직접 손으로 편집하기보다 셀 목록을 코드로 관리하는 게 diff 리뷰에 낫다는 136의 방식을
그대로 따른다. 노트북 자체가 산출물이고 **출력은 지우지 않는다**(`AI/CLAUDE.md`).

실행:
    cd AI
    python validation/CROWD/dl-resid-check/_build_notebook.py \
        --gru models/CROWD/dl_gru_s14_20260914-0949 \
        --gru-no-trunc models/CROWD/dl_gru_s14_notrunc_20260914-0950
"""

from __future__ import annotations

import argparse
from pathlib import Path

import nbformat as nbf
from nbclient import NotebookClient

HERE = Path(__file__).resolve().parent
AI_ROOT = HERE.parents[2]


def build(gru: str, gru_no_trunc: str) -> nbf.NotebookNode:
    nb = nbf.v4.new_notebook()
    cells = []

    cells.append(
        nbf.v4.new_markdown_cell(
            """# 144 — GRU 잔차 모델: 학습 곡선과 이력 가용성 4시나리오

수치 원본은 같은 폴더의 [`RESULTS.md`](./RESULTS.md)이고, 어긋나면 그쪽이 맞다. 이 노트북은
`evaluate_dl.py`가 남긴 지표 parquet과 아티팩트 `history.json`을 **그림으로만** 다시 읽는다.

질문은 하나다 — **이력이 짧거나 없을 때 모델이 lookup 아래로 떨어지는가.**
143에서 배포 LightGBM은 시차가 전부 NaN이면 lookup 대비 RMSE −37%였다. 144는 학습 때 이력을
무작위로 잘라(`masking.truncate_history`) "이력이 짧다"를 학습 분포 안에 넣으면 그 붕괴가 사라지는지를 본다."""
        )
    )

    cells.append(nbf.v4.new_code_cell(f"""import json
import sys
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

GRU = AI_ROOT / "{gru}"
GRU_NT = AI_ROOT / "{gru_no_trunc}"
VAL = AI_ROOT / "data" / "CROWD" / "interim" / "validation"

metrics = pd.read_parquet(VAL / "dl_resid_metrics.parquet")
grades = pd.DataFrame(json.loads((VAL / "dl_resid_grades.json").read_text(encoding="utf-8")))
timing = json.loads((VAL / "dl_resid_timing.json").read_text(encoding="utf-8"))
meta = {{p.name: json.loads((p / "meta.json").read_text(encoding="utf-8")) for p in (GRU, GRU_NT)}}
history = {{p.name: pd.DataFrame(json.loads((p / "history.json").read_text(encoding="utf-8"))) for p in (GRU, GRU_NT)}}

SCEN = ["full", "d7_only", "d1_only", "no_lag"]
SERIES = ["lightgbm", "gru", "gru_no_trunc"]
print(f"지표 {{len(metrics):,}}행 · 평가 행 {{metrics['n'].max():,}} · 하루치 CPU 추론 {{timing['seconds']}}s")
pd.DataFrame(
    [{{"아티팩트": k, "증강": v["truncation"], "장치": v["device"], "epochs_run": v["epochs_run"],
       "best_epoch": v["best_epoch"], "best_valid": v["best_valid_loss"], "train_s": v["train_seconds"],
       "결정성_차이_%": v["determinism"]["rel_diff_pct"]}} for k, v in meta.items()]
)"""))

    cells.append(nbf.v4.new_markdown_cell("""## 1. 학습 곡선

`valid`는 **절단 없는 full 이력**, `valid(절단)`은 학습과 같은 분포로 이력을 무작위로 자른 검증 손실이다.
둘을 같이 봐야 "증강이 무엇을 바꿨는지"가 보인다 — full은 거의 그대로고 절단 쪽만 갈린다."""))

    cells.append(
        nbf.v4.new_code_cell("""fig, axes = plt.subplots(1, 2, figsize=(13, 4.5), sharey=True)
for ax, (name, h) in zip(axes, history.items()):
    ax.plot(h["epoch"], h["train_loss"], label="train", lw=2)
    ax.plot(h["epoch"], h["valid_loss"], label="valid (full 이력)", lw=2)
    ax.plot(h["epoch"], h["valid_loss_trunc"], label="valid (절단 혼합)", lw=2, ls="--")
    best = meta[name]["best_epoch"]
    ax.axvline(best, color="0.4", ls=":", lw=1.5)
    ax.annotate(f"best {best}", (best, ax.get_ylim()[1]), xytext=(3, -12),
                textcoords="offset points", fontsize=9, color="0.3")
    ax.set_title(("절단 증강 gru" if meta[name]["truncation"] else "대조군 gru_no_trunc") + f"\\n{name}")
    ax.set_xlabel("에폭")
axes[0].set_ylabel("Huber 손실 (z 단위)")
axes[0].legend()
fig.suptitle("학습 곡선 — 증강은 full 검증을 거의 깎지 않고 절단 검증만 끌어올린다", y=1.02)
fig.tight_layout()
fig""")
    )

    cells.append(nbf.v4.new_markdown_cell("""## 2. 이력 가용성 4시나리오 — lookup 대비 개선율

0선(lookup)이 기준이다. **아래로 내려간 막대는 "차라리 평균을 쓰는 게 나았다"**는 뜻이다."""))

    cells.append(nbf.v4.new_code_cell("""tot = metrics[metrics["axis"] == "전체"]

def bars(metric, ax, target):
    piv = tot[tot["target"] == target].pivot_table(index="scenario", columns="series", values=metric)
    piv = piv.reindex(index=SCEN, columns=SERIES)
    x = np.arange(len(SCEN))
    w = 0.26
    for i, s in enumerate(SERIES):
        ax.bar(x + (i - 1) * w, piv[s], w, label=s)
    ax.axhline(0, color="0.2", lw=1)
    ax.set_xticks(x, SCEN)
    ax.set_title(f"{metric} · {target}")
    return piv

fig, axes = plt.subplots(2, 2, figsize=(13, 8))
for row, metric in enumerate(["RMSE_개선율_%", "MAE_개선율_%"]):
    for col, target in enumerate(["boarding", "alighting"]):
        bars(metric, axes[row][col], target)
axes[0][0].legend(title="계열")
fig.suptitle("이력이 빠질수록 LightGBM은 붕괴하고 절단 증강 GRU는 0선 근처에 머문다", y=1.0)
fig.tight_layout()
fig"""))

    cells.append(nbf.v4.new_code_cell("""tot[tot["target"] == "boarding"].pivot_table(
    index="series", columns="scenario", values=["RMSE_개선율_%", "MAE_개선율_%", "rmse", "mae"]
).round(2).reindex(SERIES)"""))

    cells.append(nbf.v4.new_markdown_cell("""## 3. 등급 일치율 — 서비스가 실제로 보여주는 값

승하차 RMSE 격차가 등급(임계치 50/100, 30분 셀 716만 개)까지 전달되는지 본다.
`full`에서는 세 계열이 사실상 같고, 이력이 빠지면 GRU만 lookup 수준을 지킨다."""))

    cells.append(nbf.v4.new_code_cell("""g = grades[grades["run"] != "lookup"].copy()
g[["series", "scenario"]] = g["run"].str.split("|", expand=True)
piv = g.pivot_table(index="scenario", columns="series", values="등급_일치율_%").reindex(
    index=SCEN, columns=SERIES
)
base = float(grades.loc[grades["run"] == "lookup", "등급_일치율_%"].iloc[0])

fig, ax = plt.subplots(figsize=(9, 4.5))
x = np.arange(len(SCEN))
for i, s in enumerate(SERIES):
    ax.bar(x + (i - 1) * 0.26, piv[s], 0.26, label=s)
ax.axhline(base, color="0.2", ls="--", lw=1.5, label=f"lookup {base:.2f}%")
ax.set_xticks(x, SCEN)
ax.set_ylim(90, 98)
ax.set_ylabel("등급 일치율 (%)")
ax.set_title("등급 일치율 — 이력이 없어도 GRU는 lookup 아래로 내려가지 않는다")
ax.legend()
fig.tight_layout()
piv.round(3)"""))

    cells.append(nbf.v4.new_markdown_cell("""## 4. 호선·요일유형 슬라이스

`full`에서 GRU가 lookup보다 나쁜 유일한 호선이 2호선(순환선·지선 방향 체계)이다.
반대로 8·4호선처럼 규모가 작은 호선에서는 GRU가 LightGBM을 앞선다."""))

    cells.append(nbf.v4.new_code_cell("""fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
for ax, (axis, title) in zip(axes, [("line", "호선별"), ("day_type", "요일유형별")]):
    sub = metrics[(metrics["axis"] == axis) & (metrics["target"] == "boarding")
                  & (metrics["scenario"].isin(["full", "no_lag"]))]
    piv = sub.pivot_table(index="group", columns=["series", "scenario"], values="RMSE_개선율_%")
    piv = piv.reindex(columns=[(s, sc) for s in SERIES for sc in ("full", "no_lag")])
    piv.columns = [f"{s}|{sc}" for s, sc in piv.columns]
    piv.plot.bar(ax=ax, width=0.8, legend=(axis == "line"))
    ax.axhline(0, color="0.2", lw=1)
    ax.set_title(f"{title} 승차 RMSE 개선율 (%)")
    ax.set_xlabel("")
    ax.tick_params(axis="x", rotation=0)
fig.tight_layout()
fig"""))

    cells.append(nbf.v4.new_markdown_cell("""## 5. 읽은 것

1. **`full`에서 GRU는 LightGBM에 RMSE로 크게 진다**(+6.99 vs +23.38, 승차). 판정 기준 (a)(±2%p) 불충족.
   반면 MAE 격차는 5%p 안쪽이고 등급 일치율은 동등하다 — RMSE 격차는 대형 이상치를 못 따라가는 데서 온다.
2. **이력이 빠지면 순위가 뒤집힌다.** `no_lag`에서 LightGBM −36.6%, 대조군 GRU −34.9%, 절단 증강 GRU −7.9%.
   등급으로 보면 절단 증강 GRU만 lookup과 같다(95.34 vs 95.37). 기준 (b)는 "0%p 이상"에는 못 미쳤지만
   **붕괴하지 않는다**는 성질은 확인됐다.
3. **절단 증강의 대가는 작다.** 두 모델의 full 검증 손실은 0.2917 vs 0.2903으로 거의 같고, 2025 `full`에서는
   승차 −3.4%p / 하차 +7.0%p로 방향이 엇갈린다 — 시드 1개로는 (c)를 판정할 수 없다(145에서 시드 반복).
4. **CPU 하루치 추론 0.2초.** 운영 기준(10분) 대비 문제가 되지 않는다.

다음(145): 판정 지표 확정, 가용성별 예측기 3단 선택(LightGBM / GRU / lookup), 손실·정규화 1파라미터 실험,
2호선 열세 원인. 미해결 목록 전체는 [`RESULTS.md`](./RESULTS.md) 5절."""))

    nb["cells"] = cells
    nb.metadata["kernelspec"] = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    return nb


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gru", required=True)
    ap.add_argument("--gru-no-trunc", required=True)
    ap.add_argument("--out", default=str(HERE / "dl_resid_check.ipynb"))
    args = ap.parse_args()

    nb = build(args.gru.replace("\\", "/"), args.gru_no_trunc.replace("\\", "/"))
    NotebookClient(nb, timeout=600, resources={"metadata": {"path": str(AI_ROOT)}}).execute()
    nbf.write(nb, args.out)
    print(f"[노트북] 저장(출력 포함): {args.out}")


if __name__ == "__main__":
    main()
