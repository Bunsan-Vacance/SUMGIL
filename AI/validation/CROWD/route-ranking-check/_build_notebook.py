"""`route_ranking_check.ipynb`을 생성·실행(출력 포함)하는 1회성 스크립트(239 경로 순위 뒤집힘 실험).

`train-window-check/_build_notebook.py`와 같은 방식 — 셀 목록을 코드로 관리하고, 노트북 자체가
산출물이라 **출력을 지우지 않는다**(`AI/CLAUDE.md`). `run_ranking.py`가 이미
`data/CROWD/interim/validation/route_ranking/{candidates.csv, summary.json}`(실행 1)과
`.../run2025/`(실행 2)에 남긴 표를 그림으로만 다시 읽는다 — 재계산 없음. 수치 원본은 같은 폴더의
`RESULTS.md`이고, 어긋나면 그쪽이 맞다(3절 판정은 이 스크립트가 빌드 시점에 그대로 읽어와 노트북에
박아 넣는다 — 손으로 옮겨 적은 사본이 원본과 어긋나는 것을 막기 위해서다).

실행:
    cd AI
    python validation/CROWD/route-ranking-check/_build_notebook.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import nbformat as nbf
from nbclient import NotebookClient

HERE = Path(__file__).resolve().parent
AI_ROOT = HERE.parents[2]
RESULTS_PATH = HERE / "RESULTS.md"


def _extract_verdict_items(results_text: str) -> str:
    """`RESULTS.md` 3절의 번호 매긴 결론 세 개(1.~3.)만 그대로 뽑아온다.

    시작: 첫 `1. **` 줄. 끝: `**설계 반영.**` 문단 직전(그 문단은 결론이 아니라 후속 설계
    지침이라 노트북 8번 셀에는 넣지 않는다).
    """
    start = results_text.index("1. **(a)")
    end = results_text.index("**설계 반영.**")
    return results_text[start:end].strip()


def build() -> nbf.NotebookNode:
    results_text = RESULTS_PATH.read_text(encoding="utf-8")
    verdict_items = _extract_verdict_items(results_text)

    nb = nbf.v4.new_notebook()
    cells = []

    cells.append(
        nbf.v4.new_markdown_cell(
            """# 239 — 경로 순위 뒤집힘 실험: 세 해상도에서 후보 순위가 얼마나 바뀌나

**목적**: 혼잡도가 경로 추천에 "의미 있게" 영향을 주는가를, 세 해상도 — (a) 정적 lookup 표 ·
(b) 30분 모델 표 · (c) 노드×열차 표 — 에서 만든 같은 OD·같은 후보·같은 출발 시각의 순위 변화로
잰다. 수치 원본·실행 조건·재현 명령은 [`RESULTS.md`](./RESULTS.md)에 있고, 이 노트북과 어긋나면
그쪽이 맞다."""
        )
    )

    _SETUP_CODE = """import json
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

RUN_DIRS = {
    "1 d7_only": AI_ROOT / "data" / "CROWD" / "interim" / "validation" / "route_ranking",
    "2 full": AI_ROOT / "data" / "CROWD" / "interim" / "validation" / "route_ranking" / "run2025",
}
RUNS = list(RUN_DIRS)
TIMES = ["08:00", "14:00", "23:00"]
PAIR_ORDER = ["lookup_vs_model", "model_vs_train", "lookup_vs_train"]
PAIR_LABELS = {
    "lookup_vs_model": "(a) lookup\\n→ (b) model",
    "model_vs_train": "(b) model\\n→ (c) train",
    "lookup_vs_train": "(a) lookup\\n→ (c) train",
}

frames = []
summaries = {}
for run, d in RUN_DIRS.items():
    frame = pd.read_csv(d / "candidates.csv")
    frame["run"] = run
    frames.append(frame)
    summaries[run] = json.loads((d / "summary.json").read_text(encoding="utf-8"))
cand = pd.concat(frames, ignore_index=True)

print("행 수(candidates.csv):")
print(cand.groupby("run").size().to_string())

n_cand_by_case = (
    cand[cand["resolution"] == "lookup"]
    .groupby(["run", "date", "time", "od_id"])
    .size()
    .rename("n_cand")
    .reset_index()
)
print("\\n케이스당 후보 수 분포:")
print(n_cand_by_case.groupby(["run", "n_cand"]).size().unstack(fill_value=0).to_string())"""
    cells.append(nbf.v4.new_code_cell(_SETUP_CODE))

    cells.append(nbf.v4.new_markdown_cell("""## 1. 표 R — 상위 1위 경로가 바뀐 비율

`summary.json`의 `pairs`(해상도 쌍별 1위 변경률·95% CI)를 실행 1·2 나란히 놓는다."""))
    _FIG1_CODE = """rows = []
for run, summary in summaries.items():
    for p in summary["pairs"]:
        lo, hi = p["top1_changed_rate_ci95"]
        rows.append(
            {
                "run": run,
                "pair": p["pair"],
                "rate": p["top1_changed_rate"],
                "ci_lo": lo,
                "ci_hi": hi,
                "gap_mean": p["gap_mean_when_changed"],
                "gap_median": p["gap_median_when_changed"],
            }
        )
table_r = pd.DataFrame(rows)
print(table_r[["pair", "run", "rate", "ci_lo", "ci_hi", "gap_mean", "gap_median"]]
      .round(4).to_string(index=False))

x = np.arange(len(PAIR_ORDER))
width = 0.35
fig, ax = plt.subplots(figsize=(9, 5))
for i, run in enumerate(RUNS):
    sub = table_r[table_r["run"] == run].set_index("pair").reindex(PAIR_ORDER)
    point = sub["rate"].to_numpy() * 100
    err = [
        (sub["rate"].to_numpy() - sub["ci_lo"].to_numpy()) * 100,
        (sub["ci_hi"].to_numpy() - sub["rate"].to_numpy()) * 100,
    ]
    ax.bar(x + (i - 0.5) * width, point, width, yerr=err, capsize=3, label=run,
           color=figstyle.PALETTE_NEUTRAL[i], edgecolor="white", linewidth=0.6,
           error_kw={"ecolor": "#444", "elinewidth": 1.0})
ax.set_xticks(x)
ax.set_xticklabels([PAIR_LABELS[p] for p in PAIR_ORDER])
ax.set_ylabel("1위 변경률 (%)")
ax.set_title("Figure 1. 해상도 쌍별 1위 변경률 (95% CI, OD 쌍 단위 부트스트랩)")
ax.legend()
fig.tight_layout()
_ = figstyle.save(fig, "route_ranking_fig1_top1_changed_rate")"""
    cells.append(nbf.v4.new_code_cell(_FIG1_CODE))

    cells.append(nbf.v4.new_markdown_cell("""## 2. 시간대별 1위 변경률

08:00·14:00·23:00 각각에서 (a)→(b), (b)→(c) 변경률이 실행 1·2에서 어떻게 갈리는지 본다."""))
    _FIG2_CODE = """time_rows = []
for run, summary in summaries.items():
    for t in TIMES:
        for p in summary["by_time"][t]:
            lo, hi = p["top1_changed_rate_ci95"]
            time_rows.append(
                {"run": run, "time": t, "pair": p["pair"], "rate": p["top1_changed_rate"],
                 "ci_lo": lo, "ci_hi": hi}
            )
time_df = pd.DataFrame(time_rows)

LINE_PAIRS = ["lookup_vs_model", "model_vs_train"]
xt = np.arange(len(TIMES))
fig, axes = plt.subplots(1, len(RUNS), figsize=(11, 4.5), sharey=True)
for ax, run in zip(axes, RUNS):
    sub_run = time_df[time_df["run"] == run]
    for i, pair in enumerate(LINE_PAIRS):
        sub = sub_run[sub_run["pair"] == pair].set_index("time").reindex(TIMES)
        point = sub["rate"].to_numpy() * 100
        err = [
            (sub["rate"].to_numpy() - sub["ci_lo"].to_numpy()) * 100,
            (sub["ci_hi"].to_numpy() - sub["rate"].to_numpy()) * 100,
        ]
        ax.errorbar(xt + (i - 0.5) * 0.06, point, yerr=err, fmt="o-", capsize=3,
                    label=PAIR_LABELS[pair].replace("\\n", " "), color=figstyle.PALETTE_NEUTRAL[i])
    ax.set_xticks(xt)
    ax.set_xticklabels(TIMES)
    ax.set_title(run)
axes[0].set_ylabel("1위 변경률 (%)")
axes[-1].legend(fontsize=8, loc="upper left")
fig.suptitle("Figure 2. 시간대별 1위 변경률 (95% CI)", y=1.02)
fig.tight_layout()
_ = figstyle.save(fig, "route_ranking_fig2_by_time")"""
    cells.append(nbf.v4.new_code_cell(_FIG2_CODE))

    cells.append(nbf.v4.new_markdown_cell("""## 3. 같은 후보의 값이 얼마나 움직였나

경로(= `cand_id`)는 그대로 두고 표시 값(`mean_tw`)만 해상도 사이에서 비교한다 —
`(run, date, time, od_id, cand_id)`로 피벗해 `|model − lookup|`, `|train − model|`을 잰다."""))
    _FIG3_CODE = """piv = cand.pivot_table(
    index=["run", "date", "time", "od_id", "cand_id"], columns="resolution", values="mean_tw"
)
piv["diff_model_lookup"] = (piv["model"] - piv["lookup"]).abs()
piv["diff_train_model"] = (piv["train"] - piv["model"]).abs()

DIFF_COLS = ["diff_model_lookup", "diff_train_model"]
DIFF_TITLES = ["|model - lookup|", "|train - model|"]
fig, axes = plt.subplots(2, len(RUNS), figsize=(11, 7))
for row, (col, title) in enumerate(zip(DIFF_COLS, DIFF_TITLES)):
    for c, run in enumerate(RUNS):
        ax = axes[row][c]
        vals = piv.xs(run, level="run")[col].dropna()
        ax.hist(vals, bins=40, color=figstyle.PALETTE_NEUTRAL[row], edgecolor="white")
        ax.set_yscale("log")
        if row == 0:
            ax.set_title(run)
        if c == 0:
            ax.set_ylabel(f"{title} (log)")
fig.suptitle("Figure 3. 같은 후보의 값 이동 — |model-lookup|, |train-model|", y=1.02)
fig.tight_layout()
_ = figstyle.save(fig, "route_ranking_fig3_value_shift")

for run in RUNS:
    for col, title in zip(DIFF_COLS, DIFF_TITLES):
        vals = piv.xs(run, level="run")[col].dropna()
        print(f"{run} {title}: 중앙값={vals.median():.2f} p90={vals.quantile(0.9):.2f} "
              f"p99={vals.quantile(0.99):.2f} (n={len(vals)})")

by_date_run2 = (
    piv.xs("2 full", level="run")["diff_model_lookup"].dropna().reset_index()
    .groupby("date")["diff_model_lookup"].median()
)
print("\\n실행 2 날짜별 |model-lookup| 중앙값 (기대: 경기일 3.45 · 평일 0.94 · 공휴일 5.38):")
print(by_date_run2.round(2).to_string())"""
    cells.append(nbf.v4.new_code_cell(_FIG3_CODE))

    cells.append(nbf.v4.new_markdown_cell("""## 4. 근접 케이스 — (b)→(c) 변경이 어디서 나는가

후보 ≥ 2인 케이스만 대상으로, (b) 기준 1·2위 격차(margin)와 (b)→(c) 1위 변경 여부를 같이 본다."""))
    _FIG4_CODE = """model_df = cand[cand["resolution"] == "model"]
n_cand_case = model_df.groupby(["run", "date", "time", "od_id"]).size().rename("n_cand")


def _top1_map(df, resolution):
    sub = df[(df["resolution"] == resolution) & (df["rank"] == 1)]
    sub = sub.drop_duplicates(["run", "date", "time", "od_id"])
    return sub.set_index(["run", "date", "time", "od_id"])["cand_id"]


t_model = _top1_map(cand, "model")
t_train = _top1_map(cand, "train")
top1_joined = pd.concat([t_model.rename("model"), t_train.rename("train")], axis=1).dropna()
top1_joined = top1_joined.join(n_cand_case)
ge2 = top1_joined[top1_joined["n_cand"] >= 2].copy()
ge2["changed"] = ge2["model"] != ge2["train"]

comparable_model = cand[(cand["resolution"] == "model") & (cand["comparable"])]


def _margin_of(group):
    vals = group.sort_values("mean_tw")["mean_tw"].to_numpy()
    return vals[1] - vals[0] if len(vals) >= 2 else np.nan


margins = (
    comparable_model.groupby(["run", "date", "time", "od_id"])
    .apply(_margin_of, include_groups=False)
    .rename("margin")
    .dropna()
)
merged = ge2.join(margins, how="left")

fig, axes = plt.subplots(1, len(RUNS), figsize=(11, 4.5), sharey=True)
for ax, run in zip(axes, RUNS):
    sub = merged.xs(run, level="run")
    all_margin = sub["margin"].dropna()
    flip_margin = sub.loc[sub["changed"], "margin"].dropna()
    ax.hist(all_margin, bins=30, color=figstyle.PALETTE_NEUTRAL[1], label="전체", alpha=0.6)
    ax.hist(flip_margin, bins=30, color=figstyle.COLOR_ACCENT, label="(b)→(c) 변경", alpha=0.85)
    ax.axvline(2.0, color="#222", linestyle="--", linewidth=1.0)
    ax.set_title(run)
    ax.set_xlabel("(b) 1·2위 격차 (%p)")
    ax.legend(fontsize=8)
axes[0].set_ylabel("케이스 수")
fig.suptitle("Figure 4. 근접 케이스 — (b) 1·2위 격차와 (b)→(c) 변경", y=1.02)
fig.tight_layout()
_ = figstyle.save(fig, "route_ranking_fig4_margin")

for run in RUNS:
    sub = merged.xs(run, level="run")
    rate = sub["changed"].mean()
    flip_margin = sub.loc[sub["changed"], "margin"].dropna()
    share_lt2 = (flip_margin < 2).mean()
    pct = sub["margin"].dropna().quantile([0.25, 0.5, 0.75])
    print(f"{run}: 후보>=2 케이스 {len(sub)} · (b)->(c) 변경률={rate:.3f} · "
          f"변경 케이스 중 margin<2%p 비율={share_lt2:.3f}")
    print(f"  전체 케이스 margin 25/50/75%: {pct.round(2).to_list()}")"""
    cells.append(nbf.v4.new_code_cell(_FIG4_CODE))

    cells.append(nbf.v4.new_markdown_cell("""## 5. 편안함 1위 vs 최단시간 1위

(b) 기준으로, 가장 빠른 후보와 가장 덜 붐비는(비교 가능한) 후보가 다른 케이스에서
혼잡도 이득(%p)과 대가(추가 소요 시간, 분)를 본다."""))
    _FIG5_CODE = """model_df = cand[cand["resolution"] == "model"]
fastest = model_df.loc[model_df.groupby(["run", "date", "time", "od_id"])["total_min"].idxmin()]
fastest = fastest.set_index(["run", "date", "time", "od_id"])[["cand_id", "total_min", "mean_tw"]]

top1_comfort = model_df[(model_df["rank"] == 1) & (model_df["comparable"])]
top1_comfort = top1_comfort.drop_duplicates(["run", "date", "time", "od_id"])
top1_comfort = top1_comfort.set_index(["run", "date", "time", "od_id"])[
    ["cand_id", "total_min", "mean_tw"]
]

joined = fastest.join(top1_comfort, lsuffix="_fast", rsuffix="_top1", how="inner")
differ = joined[joined["cand_id_fast"] != joined["cand_id_top1"]].copy()
differ["gain"] = differ["mean_tw_fast"] - differ["mean_tw_top1"]
differ["extra_min"] = differ["total_min_top1"] - differ["total_min_fast"]

fig, axes = plt.subplots(1, len(RUNS), figsize=(11, 5), sharex=True, sharey=True)
for ax, run in zip(axes, RUNS):
    sub = differ.xs(run, level="run")
    ax.scatter(sub["extra_min"], sub["gain"], s=10, alpha=0.35, color=figstyle.PALETTE_NEUTRAL[0])
    ax.axhline(10, color=figstyle.COLOR_ACCENT, linestyle="--", linewidth=1.0)
    ax.axhline(20, color=figstyle.COLOR_ACCENT, linestyle=":", linewidth=1.0)
    ax.set_title(run)
    ax.set_xlabel("추가 소요 시간 (분)")
axes[0].set_ylabel("혼잡도 이득 (%p)")
fig.suptitle("Figure 5. 편안 경로의 대가 — 추가 소요 시간 vs 혼잡도 이득", y=1.02)
fig.tight_layout()
_ = figstyle.save(fig, "route_ranking_fig5_comfort_tradeoff")

for run in RUNS:
    n_total = len(joined.xs(run, level="run"))
    sub = differ.xs(run, level="run")
    q = sub["gain"].quantile([0.25, 0.5, 0.75, 0.9])
    print(f"{run}: 편안 1위 != 최단 1위 {len(sub)}/{n_total}건")
    print(f"  이득(%p) 25/50/75/90% = {q.round(2).to_list()}")
    print(f"  이득>=10%p 비율={(sub['gain'] >= 10).mean():.3f} · "
          f"이득>=20%p 비율={(sub['gain'] >= 20).mean():.3f} · "
          f"추가시간 중앙값={sub['extra_min'].median():.1f}분")"""
    cells.append(nbf.v4.new_code_cell(_FIG5_CODE))

    cells.append(nbf.v4.new_markdown_cell(f"""## 6. 판정 (`RESULTS.md` 3절 원문)

{verdict_items}"""))

    cells.append(nbf.v4.new_markdown_cell("""## 7. 한계

- **BE 그래프가 아니다.** `topology.resolve_segments` + 시각표로 만든 근사 그래프라, 실제 경로
  안내(환승 가중치·도보·버스·자전거)와 후보 집합이 다르다 — 위 비율은 지하철 단독 경로 안의 값이다.
- **열차 표 coverage가 0.92 안팎이다.** 23:00 출발은 막차 이후 탑승 열차를 못 찾는 경우가 있어
  `comparable=False`로 빠지고, 그만큼 (b)→(c) 비교 표본이 준다.
- **후보가 1개뿐인 케이스(약 17%)는 순위가 바뀔 수 없어** 전체 변경률을 낮추는 쪽으로 작용한다 —
  4절 "근접 케이스"는 후보 ≥ 2 케이스로만 다시 잰 값이다.

재현 명령은 `RESULTS.md` 5절을 그대로 따른다(패널·시각표·배치 표를 먼저 만들고
`run_ranking.py`로 `candidates.csv`/`summary.json`을 생성한 뒤, 이 노트북은 그 결과만 그림으로
다시 읽는다)."""))

    nb["cells"] = cells
    nb.metadata["kernelspec"] = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    return nb


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", default=None, help="생략 시 같은 폴더의 route_ranking_check.ipynb")
    args = ap.parse_args()

    nb = build()
    out = args.out or str(HERE / "route_ranking_check.ipynb")
    NotebookClient(nb, timeout=900, resources={"metadata": {"path": str(AI_ROOT)}}).execute()
    # nbf.write()는 Windows에서 텍스트 모드로 열어 LF를 CRLF로 바꾼다 — 저장소 규약(LF)을
    # 지키려 바이트로 직접 쓴다.
    text = nbf.writes(nb)
    if not text.endswith("\n"):
        text += "\n"
    Path(out).write_bytes(text.encode("utf-8"))
    print(f"[노트북] 저장(출력 포함, LF): {out}")


if __name__ == "__main__":
    main()
