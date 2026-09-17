"""`masking_check.ipynb`을 생성·실행(출력 포함)하는 1회성 스크립트(145 후속 마스킹 LightGBM 비교).

`family-check/_build_notebook.py`와 같은 방식 — 셀 목록을 코드로 관리하고, 노트북 자체가 산출물이라
**출력을 지우지 않는다**(`AI/CLAUDE.md`). GPU가 필요 없다 — `compare.py --window <라벨>`이 남긴
`data/CROWD/interim/validation/masking_check/<라벨>/masking_check_*.parquet`만 그림으로 다시 읽고,
예측·부트스트랩을 다시 계산하지 않는다. 수치 원본은 같은 폴더의 `RESULTS.md`이고, 어긋나면
그쪽이 맞다.

실행:
    cd AI
    python validation/CROWD/masking-check/_build_notebook.py --window w2024
"""

from __future__ import annotations

import argparse
from pathlib import Path

import nbformat as nbf
from nbclient import NotebookClient

HERE = Path(__file__).resolve().parent
AI_ROOT = HERE.parents[2]

# 창(window) 값만 바뀌는 셀은 플레이스홀더 __WINDOW__를 실제 라벨로 치환해 넣는다 — 이 파일 자체는
# f-string이 아니라 평범한 문자열이라(딕셔너리 리터럴의 중괄호가 섞여 있어 f-string이면 이스케이프가
# 번거롭다) 노트북 코드에 그대로 들어갈 f-string(`f"...{WINDOW}..."`)은 노트북 커널이 실행할 때
# 평가되지 그 자체를 여기서 다시 해석하지 않는다.
_SETUP_CODE = """import sys
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

WINDOW = "__WINDOW__"
VAL = AI_ROOT / "data" / "CROWD" / "interim" / "validation" / "masking_check" / WINDOW


def _read(name):
    p = VAL / f"masking_check_{name}.parquet"
    return pd.read_parquet(p) if p.exists() else None


a = _read("A_lookup_대비_개선율_CI")
b = _read("B_lightgbm_쌍차이")
b2 = _read("B2_masked_GRU쌍차이")
c = _read("C_발산처리_적용행")

TARGETS = ["boarding", "alighting"]
KOR = {"boarding": "승차", "alighting": "하차"}
ORDER = ["full", "d7_only", "d1_only", "no_lag"]

tot_a = a[a["axis"] == "전체"]
tot_b = b[b["axis"] == "전체"]
tot_b2 = b2[b2["axis"] == "전체"] if b2 is not None else None
SC = sorted(tot_a["scenario"].unique(), key=lambda s: ORDER.index(s))
xx = np.arange(len(SC))
MASKED = sorted(n for n in tot_a["series"].unique() if n.startswith("lgbm_masked_"))

print(f"윈도우: {WINDOW} · 실행 커밋: {tot_a['git_commit'].iloc[0] if len(tot_a) else '?'}")
print(f"마스킹 후보: {MASKED} · 시나리오: {SC}")
if c is not None:
    print(f"발산 처리: {c['mode'].unique()[0]} · 상한 초과 행 합계 {int(c['상한초과_행'].sum())}")"""

_FIG1_CODE = """fig, axes = plt.subplots(1, 2, figsize=(13, 4.5), sharey=True)
width = 0.8 / (1 + len(MASKED))

for ax, t in zip(axes, TARGETS):
    lgb = tot_a[(tot_a["series"] == "lightgbm") & (tot_a["target"] == t)].set_index("scenario")
    lgb = lgb.reindex(SC)
    point = lgb["RMSE_개선율_%"].to_numpy()
    err = [point - lgb["RMSE_CI_low"].to_numpy(), lgb["RMSE_CI_high"].to_numpy() - point]
    ax.bar(xx - 0.4 + width / 2, point, width, yerr=err, capsize=3, label="lightgbm(배포)",
           color=figstyle.COLOR_MODEL, edgecolor="white", linewidth=0.6,
           error_kw={"ecolor": "#444", "elinewidth": 1.1})
    for i, name in enumerate(MASKED, start=1):
        sub = tot_a[(tot_a["series"] == name) & (tot_a["target"] == t)].set_index("scenario")
        sub = sub.reindex(SC)
        pt = sub["RMSE_개선율_%"].to_numpy()
        e = [pt - sub["RMSE_CI_low"].to_numpy(), sub["RMSE_CI_high"].to_numpy() - pt]
        ax.bar(xx - 0.4 + width * (i + 0.5), pt, width, yerr=e, capsize=3, label=name,
               color=figstyle.PALETTE_NEUTRAL[i % len(figstyle.PALETTE_NEUTRAL)],
               edgecolor="white", linewidth=0.6, error_kw={"ecolor": "#444", "elinewidth": 1.1})
    ax.axhline(0, color="#222", linewidth=1.0)
    ax.set_xticks(xx)
    ax.set_xticklabels(SC)
    ax.set_title(f"{KOR[t]} — RMSE 개선율 (%, 0 = lookup)")
    ax.legend(fontsize=8, loc="lower left")
axes[0].set_ylabel("%")
fig.suptitle("마스킹 학습이 결손·전무 시나리오에서 lookup 위에 남는가", y=1.02)
fig.tight_layout()
_ = figstyle.save(fig, f"masking_scenarios_{WINDOW}")"""

_FIG2_CODE = """DIFF_R = [col for col in tot_b.columns if col.startswith("point_diff_RMSE_%p")][0]

fig, ax = plt.subplots(figsize=(10, 4.5))
for i, name in enumerate(MASKED):
    sub = tot_b[(tot_b["series"] == name) & (tot_b["target"] == "boarding")]
    sub = sub.set_index("scenario").reindex(SC)
    point = sub[DIFF_R].to_numpy()
    lo = point - sub["diff_RMSE_CI_low"].to_numpy()
    hi = sub["diff_RMSE_CI_high"].to_numpy() - point
    ax.errorbar(xx + (i - len(MASKED) / 2) * 0.15, point, yerr=[lo, hi], fmt="o", capsize=3,
                label=name, color=figstyle.PALETTE_NEUTRAL[i % len(figstyle.PALETTE_NEUTRAL)])
ax.axhline(0, color="#222", linewidth=1.0)
ax.axhline(-1.0, color="#C0392B", linewidth=1.0, linestyle="--", label="판정 2 문턱 -1.0%p")
ax.set_xticks(xx)
ax.set_xticklabels(SC)
ax.set_ylabel("%p (마스킹 − LightGBM, 승차 RMSE)")
ax.set_title("표 B — 마스킹 후보와 현행 배포 LightGBM의 쌍 차이")
ax.legend(fontsize=8)
fig.tight_layout()
_ = figstyle.save(fig, f"masking_paired_diff_lightgbm_{WINDOW}")

print(tot_b[tot_b["target"] == "boarding"].set_index(["series", "scenario"])[
    [DIFF_R, "diff_RMSE_CI_low", "diff_RMSE_CI_high"]
].round(2).to_string())"""

_FIG3_CODE = """if tot_b2 is None:
    print("표 B2 없음 — compare.py가 아직 안 돌았다")
else:
    diff_r2 = [col for col in tot_b2.columns if col.startswith("point_diff_RMSE_%p")][0]
    gru_label = diff_r2.split("계열-")[-1].rstrip(")")
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for i, name in enumerate(MASKED):
        sub = tot_b2[(tot_b2["series"] == name) & (tot_b2["target"] == "boarding")]
        sub = sub.set_index("scenario").reindex(SC)
        point = sub[diff_r2].to_numpy()
        lo = point - sub["diff_RMSE_CI_low"].to_numpy()
        hi = sub["diff_RMSE_CI_high"].to_numpy() - point
        ax.errorbar(xx + (i - len(MASKED) / 2) * 0.15, point, yerr=[lo, hi], fmt="D", capsize=3,
                    label=name, color=figstyle.PALETTE_NEUTRAL[i % len(figstyle.PALETTE_NEUTRAL)])
    ax.axhline(0, color="#222", linewidth=1.0)
    ax.axhline(-2.0, color="#C0392B", linewidth=1.0, linestyle="--", label="판정 3 문턱 -2.0%p")
    ax.set_xticks(xx)
    ax.set_xticklabels(SC)
    ax.set_ylabel(f"%p (마스킹 − {gru_label}, 승차 RMSE)")
    ax.set_title("표 B2 — 마스킹 후보와 GRU 기준의 쌍 차이")
    ax.legend(fontsize=8)
    fig.tight_layout()
    _ = figstyle.save(fig, f"masking_paired_diff_gru_{WINDOW}")

    print(tot_b2[tot_b2["target"] == "boarding"].set_index(["series", "scenario"])[
        [diff_r2, "diff_RMSE_CI_low", "diff_RMSE_CI_high"]
    ].round(2).to_string())"""


def build(window: str) -> nbf.NotebookNode:
    nb = nbf.v4.new_notebook()
    cells = []

    cells.append(nbf.v4.new_markdown_cell(f"""# 145 후속 — 마스킹 학습 LightGBM 비교 (`{window}`)

수치 원본은 같은 폴더의 `RESULTS.md`이고, 어긋나면 그쪽이 맞다. 이 노트북은
`compare.py --window {window}`가 남긴 `masking_check_*.parquet`을 **그림으로만** 다시 읽는다 —
GPU도 재계산도 필요 없다.

| 축 | 값 |
| --- | --- |
| 계열 | `lookup` · `lightgbm`(현행 배포) · `lgbm_masked_*`(마스킹 학습 후보) · `gru_s42/43/44` |
| 가용성 | `full` · `d7_only` · `d1_only` · `no_lag` |
| 비교 | 표 A(lookup 대비) · 표 B(LightGBM 쌍차이) · 표 B2(마스킹 후보 대 GRU 기준 쌍차이) |"""))

    cells.append(nbf.v4.new_code_cell(_SETUP_CODE.replace("__WINDOW__", window)))

    cells.append(
        nbf.v4.new_markdown_cell(
            "## 1. 가용성 시나리오별 lookup 대비 개선율 — LightGBM vs 마스킹 후보"
        )
    )
    cells.append(nbf.v4.new_code_cell(_FIG1_CODE))

    cells.append(nbf.v4.new_markdown_cell("""## 2. 마스킹 후보 − LightGBM 쌍 차이 [95% CI]

`full`에서 현행 배포 대비 얼마나 밀리는지(채택 기준 2), 결손·전무에서 얼마나 따라잡는지를
같은 재표본으로 본다."""))
    cells.append(nbf.v4.new_code_cell(_FIG2_CODE))

    cells.append(nbf.v4.new_markdown_cell("""## 3. 마스킹 후보 − GRU 기준 쌍 차이 [95% CI]

결손·전무 시나리오에서 GRU를 대체할 근거(채택 기준 3)가 있는지를 같은 방식으로 본다."""))
    cells.append(nbf.v4.new_code_cell(_FIG3_CODE))

    cells.append(nbf.v4.new_markdown_cell("""## 4. 읽는 법

- **1절**은 채택 기준 1(결손·전무에서 lookup 대비 CI 하한 > 0)을 눈으로 확인한다.
- **2절**은 채택 기준 2(`full`에서 −1.0%p 이내, CI 상한 ≥ 0)를 본다 — 점선을 밑돌면 `full` 성능을
  포기한 것이다.
- **3절**은 채택 기준 3(결손·전무에서 GRU와 동등 이상, −2%p 이내)을 본다.
- 채택 기준 4(방향이 다른 기간 윈도우에서도 유지)는 이 노트북이 답하지 않는다 — `--window w2023`
  등으로 따로 실행한 노트북과 나란히 봐야 한다."""))

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
    ap.add_argument("--window", required=True, help="compare.py --window과 같은 라벨")
    ap.add_argument("--out", default=None, help="생략 시 같은 폴더의 masking_check.ipynb")
    args = ap.parse_args()

    nb = build(args.window)
    out = args.out or str(HERE / "masking_check.ipynb")
    NotebookClient(nb, timeout=900, resources={"metadata": {"path": str(AI_ROOT)}}).execute()
    nbf.write(nb, out)
    print(f"[노트북] 저장(출력 포함): {out}")


if __name__ == "__main__":
    main()
