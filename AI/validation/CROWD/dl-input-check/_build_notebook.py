"""`dl_input_check.ipynb`을 생성·실행(출력 포함)하는 1회성 스크립트(198).

셀 목록을 코드로 관리하는 136·144의 방식을 그대로 따른다. 노트북 자체가 산출물이고 **출력은
지우지 않는다**(`AI/CLAUDE.md`).

실행:
    cd AI
    python validation/CROWD/dl-input-check/_build_notebook.py \
        --models base_s42=models/CROWD/dl_gru_s14_20260914-0949 \
                 no_events_s42=models/CROWD/dl_gru_s14_noev_s42_20260914-1358 ...
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import nbformat as nbf
from nbclient import NotebookClient

HERE = Path(__file__).resolve().parent
AI_ROOT = HERE.parents[2]


def build(models: dict[str, str]) -> nbf.NotebookNode:
    nb = nbf.v4.new_notebook()
    cells = []

    cells.append(
        nbf.v4.new_markdown_cell("""# 198 — GRU 입력 설계 변형: 안 4개 · 시드 3회 · 손실 1회

수치 원본은 같은 폴더의 [`RESULTS.md`](./RESULTS.md)이고, 어긋나면 그쪽이 맞다. 이 노트북은
`evaluate_dl.py --models …`가 남긴 지표 parquet과 아티팩트 `history.json`을 **그림으로만** 다시 읽는다.

질문은 하나다 — 144에서 GRU가 `full`(이력 완비)에서 LightGBM에 RMSE 16.4%p 진 것이
**시퀀스 모델의 한계인가, 입력 1안의 한계인가.**

| 안 | 시퀀스 채널 | 정적 | 가설 |
| --- | --- | --- | --- |
| `base`(V0) | 7 | 요일 4 + 이벤트 5 | 144 기준 |
| `neighbor`(V1) | 16 | 동일 | 89의 인접역 잔차 효과가 시퀀스에서도 나는가 |
| `events_hist`(V2) | 12 | 동일 | 이력 각 날의 이벤트를 주면 대상일 반응이 좋아지는가 |
| `no_events`(V3) | 7 | 요일 4만 | 대조군 — 이벤트 5열이 실제로 기여하는가 |
| `neighbor_no_events` | 16 | 요일 4만 | 계획 밖 1회 — V1·V3이 겹치는가 |""")
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

MODELS = {json.dumps(models, ensure_ascii=False, indent=4)}
VAL = AI_ROOT / "data" / "CROWD" / "interim" / "validation"

metrics = pd.read_parquet(VAL / "dl_input_metrics.parquet")
grades = pd.DataFrame(json.loads((VAL / "dl_input_grades.json").read_text(encoding="utf-8")))
meta = {{k: json.loads((AI_ROOT / v / "meta.json").read_text(encoding="utf-8")) for k, v in MODELS.items()}}
history = {{k: pd.DataFrame(json.loads((AI_ROOT / v / "history.json").read_text(encoding="utf-8")))
           for k, v in MODELS.items()}}

SCEN = ["full", "d7_only", "d1_only", "no_lag"]
VARIANTS = ["base", "neighbor", "events_hist", "no_events", "neighbor_no_events", "base_hd3"]
print(f"지표 {{len(metrics):,}}행 · 평가 행 {{metrics['n'].max():,}} · 계열 {{metrics['series'].nunique()}}")
pd.DataFrame(
    [{{"계열": k, "채널": v.get("channels"), "정적": v.get("stat_features"), "δ": v.get("huber_delta", 1.0),
       "시드": v["seed"], "장치": v["device"], "epochs_run": v["epochs_run"], "best_epoch": v["best_epoch"],
       "best_valid": v["best_valid_loss"], "train_s": v["train_seconds"]}} for k, v in meta.items()]
).set_index("계열")"""))

    cells.append(nbf.v4.new_markdown_cell("""## 1. 안별 — lookup 대비 RMSE 개선율

0선(lookup)이 기준이고 **아래로 내려간 막대는 "차라리 평균을 쓰는 게 나았다"**는 뜻이다.
회색 점선이 배포 LightGBM의 `full` 값이다 — 판정 3(−5%p 이내)의 잣대."""))

    cells.append(nbf.v4.new_code_cell("""tot = metrics[metrics["axis"] == "전체"].copy()
tot["variant"] = tot["series"].str.replace(r"_s\\d+$", "", regex=True)
s42 = tot[tot["series"].str.endswith("_s42") | (tot["series"] == "lightgbm")]

fig, axes = plt.subplots(1, 2, figsize=(13, 4.5), sharey=True)
for ax, target in zip(axes, ["boarding", "alighting"]):
    piv = s42[s42["target"] == target].pivot_table(
        index="scenario", columns="variant", values="RMSE_개선율_%"
    ).reindex(index=SCEN, columns=[v for v in VARIANTS if v in s42["variant"].unique()])
    x = np.arange(len(SCEN))
    w = 0.8 / len(piv.columns)
    for i, v in enumerate(piv.columns):
        ax.bar(x + (i - (len(piv.columns) - 1) / 2) * w, piv[v], w, label=v)
    lgb_full = float(
        s42[(s42["target"] == target) & (s42["series"] == "lightgbm")
            & (s42["scenario"] == "full")]["RMSE_개선율_%"].iloc[0]
    )
    ax.axhline(lgb_full, color="0.35", ls=":", lw=1.5)
    ax.annotate(f"lightgbm full {lgb_full:.1f}", (len(SCEN) - 1, lgb_full), xytext=(-6, 4),
                textcoords="offset points", ha="right", fontsize=9, color="0.3")
    ax.axhline(0, color="0.2", lw=1)
    ax.set_xticks(x, SCEN)
    ax.set_title(f"RMSE 개선율 · {target}")
    ax.set_ylim(-40, 35)
axes[0].set_ylabel("lookup 대비 개선율 (%)")
axes[0].legend(title="입력 안", ncols=2, fontsize=8)
fig.suptitle("이벤트 5열을 빼면(no_events) full·no_lag이 동시에 올라간다", y=1.01)
fig.tight_layout()
fig"""))

    cells.append(nbf.v4.new_code_cell("""s42[s42["target"] == "boarding"].pivot_table(
    index="variant", columns="scenario", values=["RMSE_개선율_%", "MAE_개선율_%", "rmse"]
).round(2).reindex([v for v in VARIANTS + ["lightgbm"] if v in s42["variant"].unique()])"""))

    cells.append(
        nbf.v4.new_markdown_cell("""## 2. 시드 반복 — 개선폭이 시드 분산보다 큰가

판정 2의 그림이다. 시드 42·43·44 세 번의 `full` 개선율 평균과 표준편차를 오차막대로 그린다.
막대 사이 간격(= 안의 효과)이 오차막대(= 시드 노이즈)보다 크면 그 효과는 시드로 설명되지 않는다.""")
    )

    cells.append(
        nbf.v4.new_code_cell(
            """multi = tot.groupby("variant")["series"].nunique()
multi = [v for v in VARIANTS if multi.get(v, 0) >= 2]
g = tot[tot["variant"].isin(multi)].groupby(["variant", "scenario", "target"])["RMSE_개선율_%"]
stat = g.agg(["mean", "std"]).reset_index()

fig, axes = plt.subplots(1, 2, figsize=(13, 4.5), sharey=True)
for ax, target in zip(axes, ["boarding", "alighting"]):
    sub = stat[stat["target"] == target]
    x = np.arange(len(SCEN))
    w = 0.8 / len(multi)
    for i, v in enumerate(multi):
        row = sub[sub["variant"] == v].set_index("scenario").reindex(SCEN)
        ax.bar(x + (i - (len(multi) - 1) / 2) * w, row["mean"], w, yerr=row["std"],
               capsize=4, label=v)
    ax.axhline(0, color="0.2", lw=1)
    ax.set_xticks(x, SCEN)
    ax.set_title(f"RMSE 개선율 평균 ± 표준편차 · {target}")
axes[0].set_ylabel("lookup 대비 개선율 (%)")
axes[0].legend(title="입력 안(시드 3회)")
fig.suptitle("시드 노이즈(오차막대)보다 안의 효과(막대 차이)가 크다", y=1.01)
fig.tight_layout()
stat.pivot_table(index=["variant", "target"], columns="scenario", values=["mean", "std"]).round(2)"""
        )
    )

    cells.append(nbf.v4.new_markdown_cell("""## 3. 학습 곡선

`valid`는 절단 없는 full 이력, `valid(절단)`은 학습과 같은 분포로 이력을 무작위로 자른 검증 손실이다.
**δ=3 실행은 손실 정의 자체가 달라 같은 축에서 비교하지 않는다**(그래서 곡선에서 뺀다)."""))

    cells.append(nbf.v4.new_code_cell("""fig, ax = plt.subplots(figsize=(9, 4.5))
for name, h in history.items():
    if meta[name].get("huber_delta", 1.0) != 1.0 or not name.endswith("_s42"):
        continue
    line, = ax.plot(h["epoch"], h["valid_loss"], lw=2, label=name.replace("_s42", ""))
    ax.plot(h["epoch"], h["valid_loss_trunc"], lw=1.5, ls="--", color=line.get_color(), alpha=0.6)
    b = meta[name]["best_epoch"]
    ax.plot([b], [h.loc[b - 1, "valid_loss"]], "o", color=line.get_color(), ms=6)
ax.set_xlabel("에폭")
ax.set_ylabel("Huber 손실 (z 단위)")
ax.set_title("검증 손실 — 실선 full 이력 / 점선 절단 혼합, 동그라미가 best 에폭")
ax.legend(title="입력 안", fontsize=9)
fig.tight_layout()
fig"""))

    cells.append(nbf.v4.new_markdown_cell("""## 4. 호선 슬라이스 — 2호선이 풀렸는가

144에서 GRU가 `full`에서도 lookup보다 나쁜 유일한 호선이 2호선(−6.16%)이었다."""))

    cells.append(
        nbf.v4.new_code_cell(
            """line = metrics[(metrics["axis"] == "line") & (metrics["target"] == "boarding")
                & (metrics["scenario"] == "full")].copy()
line["variant"] = line["series"].str.replace(r"_s\\d+$", "", regex=True)
line = line[line["series"].str.endswith("_s42") | (line["series"] == "lightgbm")]
piv = line.pivot_table(index="group", columns="variant", values="RMSE_개선율_%")
piv = piv.reindex(columns=[v for v in VARIANTS + ["lightgbm"] if v in piv.columns])

fig, ax = plt.subplots(figsize=(11, 4.5))
piv.plot.bar(ax=ax, width=0.85)
ax.axhline(0, color="0.2", lw=1)
ax.set_title("호선별 승차 RMSE 개선율(%) — `full`, 시드 42")
ax.set_xlabel("")
ax.tick_params(axis="x", rotation=0)
ax.legend(fontsize=8, ncols=3)
fig.tight_layout()
piv.round(2)"""
        )
    )

    cells.append(nbf.v4.new_markdown_cell("""## 5. 등급 일치율 — 서비스가 실제로 보여주는 값

임계치 50/100, 30분 셀 기준. 판정용 계열 3개만 돌렸다(판 하나에 2~3분)."""))

    cells.append(
        nbf.v4.new_code_cell(
            """grades.set_index("run")[["cells", "등급_일치율_%", "보통이상_재현율_%"]].round(3)"""
        )
    )

    cells.append(nbf.v4.new_markdown_cell("""## 6. 읽은 것

결론·판정 ○× 는 [`RESULTS.md`](./RESULTS.md) 4·5절이 원본이다. 그림에서 바로 보이는 것만 적으면:

1. **이벤트 5열을 빼는 것(V3)이 가장 크게 이긴다.** `full`뿐 아니라 `no_lag`까지 같이 올라가고,
   `no_lag`에서 **DL 계열 최초로 lookup을 넘는다**.
2. **`events_hist`(V2)는 크게 실패한다.** 검증(2024-11~12) 손실은 base와 거의 같은데 2025 평가가 무너진다 —
   이벤트 채널이 2024 이벤트 분포에 과적합됐다는 뜻이고, 1번과 같은 방향을 가리킨다.
3. **`neighbor`(V1)는 작지만 일관되게 좋고 2호선 열세를 없앤다.**
4. 시드 오차막대는 작다 — 위 차이들은 시드 노이즈로 설명되지 않는다."""))

    nb["cells"] = cells
    nb.metadata["kernelspec"] = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    return nb


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", nargs="+", required=True, metavar="이름=경로")
    ap.add_argument("--out", default=str(HERE / "dl_input_check.ipynb"))
    args = ap.parse_args()

    models = {}
    for item in args.models:
        name, _, path = item.partition("=")
        models[name] = path.replace("\\", "/")
    nb = build(models)
    NotebookClient(nb, timeout=600, resources={"metadata": {"path": str(AI_ROOT)}}).execute()
    nbf.write(nb, args.out)
    print(f"[노트북] 저장(출력 포함): {args.out}")


if __name__ == "__main__":
    main()
