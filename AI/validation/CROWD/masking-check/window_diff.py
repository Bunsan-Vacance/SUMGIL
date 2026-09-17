"""표 W — 학습 윈도우(창) 간 쌍차이: 같은 계열이 학습 기간이 길어지면 얼마나 나아지는가.

## 왜

`masking-check/compare.py`는 같은 2025 평가 행 위에서 계열들을 비교하지만, `--window`로
**학습 윈도우**(모형을 무엇으로 학습했는지 — `w2024`=2024년 1개년, `w2023`=2023~2024년
2개년)를 바꿔 가며 따로 실행해 `losses_<시나리오>.parquet`를 윈도우 폴더별로 쌓아 둔다.
그런데 "학습 윈도우가 길어지면 같은 계열(lookup·LightGBM·GRU·마스킹 후보)이 얼마나
나아지는가"를 직접 재는 표는 없었다 — 그것을 내는 것이 이 스크립트의 **표 W**다.

## lookup을 공통 분모로 못 쓰는 이유

`lookup`(요일유형별 평균)은 **학습 윈도우 자체가 정의**다 — `w2024`의 lookup은 2024년
평균, `w2023`의 lookup은 2023~2024년 평균이라 서로 다른 예측기다. "lookup 대비 개선율"을
두 윈도우에서 각각 낸 뒤 그 개선율끼리 빼면, 분모(lookup)가 윈도우마다 달라 계열 자체의
변화와 lookup의 변화가 뒤섞인다. 그래서 표 W는 개선율이 아니라 **계열 자체의 RMSE·MAE를
두 윈도우에서 직접** 비교한다 — `lookup`도 계열 중 하나로 포함해, "윈도우가 길어지면
lookup 자체가 얼마나 나아지는가"를 그대로 보여준다(lookup을 기준선에서 빼지 않는다).

## 동일 행 검증 — `AI/CLAUDE.md` "모델 비교는 동등 조건에서만"의 2번(표본/행 집합)

두 윈도우가 같은 2025 평가 행(같은 날짜·역·시간대) 위에서 채점된 것이어야 쌍 비교가
성립한다. `(date, axis, group, target)`별 행 수 `n`이 두 윈도우에서 다르면(공통 행 계산이
윈도우마다 달라졌다는 뜻) `SystemExit`로 멈춘다 — 조용히 다른 표본을 비교하지 않는다.
날짜 집합 자체가 다른 경우도 같은 이유로 막는다.

## 부호 규약

- `diff_*_abs = 값_other − 값_base`(명 단위의 원 차이). RMSE·MAE는 **작을수록 좋다**는 성질을
  그대로 반영한 raw 차이라 부호만으로 "누가 낫다"를 바로 읽을 수 없다 — 그래서 `rel_*_%`를
  같이 낸다.
- `rel_*_% = (값_base − 값_other) / 값_base × 100` — **양수 = other가 낫다**(기본 호출
  `--base w2024 --other w2023`에서는 양수 = 더 긴 윈도우가 낫다), 90 이후 문서가 쓰는
  "개선율" 부호 규약과 같다.
- 둘 다 **날짜 블록 쌍(paired) 부트스트랩**이다 — `(axis, group, target)`마다 같은 재표본
  (같은 날짜 등장 횟수)으로 base·other의 RMSE·MAE를 동시에 계산한 뒤 차·비를 낸다
  (`AI/CLAUDE.md` "두 CI의 차이는 그 차이의 CI가 아니다": 증분 자체를 쌍으로 부트스트랩해야
  한다 — 날짜 블록을 공유해 상관이 있어서다).
- 점추정은 부트스트랩 평균이 아니라 **전체 데이터(재표본 가중치 전부 1)** 위에서 낸다
  (`stat-model-check/evaluate.py`의 `table_a`·`table_b`와 같은 관례).

## 실행

    cd AI
    python validation/CROWD/masking-check/window_diff.py --base w2024 --other w2023 \\
        --out data/CROWD/interim/validation/masking_check/w2023/window_diff_W.md

결과 parquet(`masking_check_W_창간_쌍차이.parquet`)은 `--other` 윈도우 폴더에 쌓인다 —
"other가 base보다 얼마나 나아졌는가"를 묻는 질문이라 최신(대개 더 긴) 윈도우 쪽에 둔다.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
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
    """다른 하이픈 폴더의 검증 스크립트를 파일 경로로 재사용한다(수정 금지, import만 — compare.py와 같은 관례)."""
    spec = importlib.util.spec_from_file_location(name, AI_ROOT / rel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# stat-model-check/evaluate.py가 이미 significance-check/bootstrap.py를 `boot`로 로드해 둔 인스턴스를
# 그대로 쓴다(같은 모듈을 두 번 로드하지 않는다 — masking-check/compare.py와 같은 관례).
# `to_markdown`도 여기서 같이 가져온다.
stat_eval = _load_sibling("validation/CROWD/stat-model-check/evaluate.py", "window_diff_stat_eval")
boot = stat_eval.boot

from app.CROWD.pipeline.masking import SCENARIOS

VALIDATION_DIR = AI_ROOT / "data" / "CROWD" / "interim" / "validation" / "masking_check"
KEY = ["date", "axis", "group", "target"]
OUT_NAME = "masking_check_W_창간_쌍차이.parquet"


def _git_commit() -> str:
    """실행 조건 기록용 짧은 커밋 해시. 깃이 없거나 저장소 밖이면 `unknown`."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=AI_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _load_losses(window: str, scenario: str) -> pd.DataFrame:
    """윈도우 폴더의 시나리오별 날짜 손실 충분통계를 읽는다. 없으면 실행 방법을 안내하고 멈춘다."""
    path = VALIDATION_DIR / window / f"losses_{scenario}.parquet"
    if not path.exists():
        raise SystemExit(
            f"손실 파일이 없다: {path} — "
            f"`python validation/CROWD/masking-check/compare.py --window {window} ...`를 먼저 실행할 것."
        )
    return pd.read_parquet(path)


def _assert_paired(
    base: pd.DataFrame, other: pd.DataFrame, base_label: str, other_label: str
) -> None:
    """두 윈도우가 같은 평가 행 위에 있는지 확인한다 — 다르면 쌍 비교 자체가 성립하지 않는다."""
    base_dates, other_dates = set(base["date"].unique()), set(other["date"].unique())
    if base_dates != other_dates:
        raise SystemExit(
            f"{base_label}·{other_label}의 평가 날짜 집합이 다르다 — 쌍 비교가 성립하지 않는다. "
            f"{base_label}에만 있는 날짜 {len(base_dates - other_dates)}개, "
            f"{other_label}에만 있는 날짜 {len(other_dates - base_dates)}개."
        )
    n_base = base.set_index(KEY)["n"].sort_index()
    n_other = other.set_index(KEY)["n"].sort_index()
    if not n_base.index.equals(n_other.index):
        raise SystemExit(
            f"{base_label}·{other_label}의 (date,axis,group,target) 키 집합이 다르다 — "
            "같은 평가 행이 아니라 쌍 비교가 무효하다."
        )
    mismatched = n_base[n_base != n_other]
    if not mismatched.empty:
        key = mismatched.index[0]
        raise SystemExit(
            f"{base_label}·{other_label}의 평가 행 수 n이 {key}에서 다르다 "
            f"({base_label}={int(n_base.loc[key])}, {other_label}={int(n_other.loc[key])}) — "
            "같은 평가 행이 아니라 쌍 비교가 무효하다(공통 행 계산이 윈도우마다 달라졌을 수 있다)."
        )


# ── 표 W: 쌍(paired) 날짜 블록 부트스트랩 ──
def window_diff_table(
    base: pd.DataFrame, other: pd.DataFrame, scenario: str, n_boot: int, seed: int
) -> pd.DataFrame:
    """시나리오 하나의 base·other 손실에서 계열별 RMSE·MAE 쌍차이 표를 낸다.

    두 윈도우가 같은 평가 행이라는 전제(`_assert_paired`, 호출부에서 먼저 확인) 위에서,
    `(axis, group, target)`마다 **같은 날짜 재표본 가중치**로 base·other의 RMSE·MAE를
    동시에 계산한다 — 그래야 둘의 차이가 "그 재표본이 쉬웠는가"를 상쇄한 쌍(paired)
    비교가 된다. `stat-model-check/evaluate.py`의 `table_a`·`table_b`와 같은 벡터화 방식
    (날짜별 SSE·SAE·n을 `n_dates` 길이 벡터로 펼쳐 부트스트랩 행렬과 내적)이다.
    """
    base_series = {c.split("__", 1)[1] for c in base.columns if c.startswith("sse__")}
    other_series = {c.split("__", 1)[1] for c in other.columns if c.startswith("sse__")}
    series_names = sorted(base_series & other_series)
    if not series_names:
        raise SystemExit(f"[{scenario}] 두 윈도우가 공유하는 계열이 없다.")

    merged = base.merge(other, on=KEY, how="inner", suffixes=("_base", "_other"))
    dates = np.sort(merged["date"].unique())
    n_dates = len(dates)
    date_index = {d: i for i, d in enumerate(dates)}
    counts = boot.resample_counts(boot.resample_dates(n_dates, n_boot, seed), n_dates)
    full = np.ones((1, n_dates))

    rows = []
    for (axis, group, target), sub in merged.groupby(["axis", "group", "target"], observed=True):
        pos = sub["date"].map(date_index).to_numpy()
        n_vec = np.zeros(n_dates)
        n_vec[pos] = sub["n_base"].to_numpy(dtype="float64")
        for name in series_names:
            sse_base = np.zeros(n_dates)
            sae_base = np.zeros(n_dates)
            sse_other = np.zeros(n_dates)
            sae_other = np.zeros(n_dates)
            sse_base[pos] = sub[f"sse__{name}_base"].to_numpy(dtype="float64")
            sae_base[pos] = sub[f"sae__{name}_base"].to_numpy(dtype="float64")
            sse_other[pos] = sub[f"sse__{name}_other"].to_numpy(dtype="float64")
            sae_other[pos] = sub[f"sae__{name}_other"].to_numpy(dtype="float64")

            # 점추정 — 부트스트랩 평균이 아니라 전체 데이터(가중치 전부 1) 위에서 낸다.
            rmse_base_pt = boot.weighted_rmse(full, sse_base, n_vec)[0]
            rmse_other_pt = boot.weighted_rmse(full, sse_other, n_vec)[0]
            mae_base_pt = boot.weighted_mae(full, sae_base, n_vec)[0]
            mae_other_pt = boot.weighted_mae(full, sae_other, n_vec)[0]

            # 쌍 부트스트랩 — base·other가 같은 재표본(같은 날짜 등장 횟수)을 공유한다.
            boot_rmse_base = boot.weighted_rmse(counts, sse_base, n_vec)
            boot_rmse_other = boot.weighted_rmse(counts, sse_other, n_vec)
            boot_mae_base = boot.weighted_mae(counts, sae_base, n_vec)
            boot_mae_other = boot.weighted_mae(counts, sae_other, n_vec)

            with np.errstate(divide="ignore", invalid="ignore"):
                diff_rmse_boot = boot_rmse_other - boot_rmse_base
                rel_rmse_boot = np.where(
                    boot_rmse_base > 0,
                    (boot_rmse_base - boot_rmse_other) / boot_rmse_base * 100.0,
                    np.nan,
                )
                diff_mae_boot = boot_mae_other - boot_mae_base
                rel_mae_boot = np.where(
                    boot_mae_base > 0,
                    (boot_mae_base - boot_mae_other) / boot_mae_base * 100.0,
                    np.nan,
                )
            diff_rmse_lo, diff_rmse_hi = boot.percentile_ci(diff_rmse_boot)
            rel_rmse_lo, rel_rmse_hi = boot.percentile_ci(rel_rmse_boot)
            diff_mae_lo, diff_mae_hi = boot.percentile_ci(diff_mae_boot)
            rel_mae_lo, rel_mae_hi = boot.percentile_ci(rel_mae_boot)

            rel_rmse_pt = (
                (rmse_base_pt - rmse_other_pt) / rmse_base_pt * 100.0
                if rmse_base_pt > 0
                else float("nan")
            )
            rel_mae_pt = (
                (mae_base_pt - mae_other_pt) / mae_base_pt * 100.0
                if mae_base_pt > 0
                else float("nan")
            )
            rows.append(
                {
                    "scenario": scenario,
                    "series": name,
                    "axis": axis,
                    "group": group,
                    "target": target,
                    "rmse_base": rmse_base_pt,
                    "rmse_other": rmse_other_pt,
                    "diff_RMSE_abs": rmse_other_pt - rmse_base_pt,
                    "diff_RMSE_abs_CI_low": diff_rmse_lo,
                    "diff_RMSE_abs_CI_high": diff_rmse_hi,
                    "rel_RMSE_%": rel_rmse_pt,
                    "rel_RMSE_CI_low": rel_rmse_lo,
                    "rel_RMSE_CI_high": rel_rmse_hi,
                    "mae_base": mae_base_pt,
                    "mae_other": mae_other_pt,
                    "diff_MAE_abs": mae_other_pt - mae_base_pt,
                    "diff_MAE_abs_CI_low": diff_mae_lo,
                    "diff_MAE_abs_CI_high": diff_mae_hi,
                    "rel_MAE_%": rel_mae_pt,
                    "rel_MAE_CI_low": rel_mae_lo,
                    "rel_MAE_CI_high": rel_mae_hi,
                }
            )
    return pd.DataFrame(rows)


# ── 실행 ──
def run(args: argparse.Namespace) -> pd.DataFrame:
    t0 = time.time()
    scenarios = args.scenarios or list(SCENARIOS)
    tables = []
    for sc in scenarios:
        base = _load_losses(args.base, sc)
        other = _load_losses(args.other, sc)
        _assert_paired(base, other, args.base, args.other)
        tbl = window_diff_table(base, other, sc, args.n_boot, args.seed)
        tables.append(tbl)

        tot = tbl[tbl["axis"] == "전체"].sort_values(["series", "target"])
        for _, r in tot.iterrows():
            print(
                f"[{sc}] {r['series']}/{r['target']}: "
                f"RMSE {r['diff_RMSE_abs']:+.1f}명 "
                f"({r['rel_RMSE_%']:+.2f}% [{r['rel_RMSE_CI_low']:+.2f}, {r['rel_RMSE_CI_high']:+.2f}]) / "
                f"MAE {r['diff_MAE_abs']:+.1f}명 "
                f"({r['rel_MAE_%']:+.2f}% [{r['rel_MAE_CI_low']:+.2f}, {r['rel_MAE_CI_high']:+.2f}])",
                flush=True,
            )

    table = pd.concat(tables, ignore_index=True).assign(
        base_window=args.base,
        other_window=args.other,
        n_boot=args.n_boot,
        seed=args.seed,
        git_commit=_git_commit(),
    )

    out_dir = VALIDATION_DIR / args.other
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / OUT_NAME
    table.to_parquet(out_path, index=False)
    print(f"[저장] {out_path}", flush=True)

    if args.out:
        head = (
            f"기준 윈도우(base): `{args.base}` · 비교 윈도우(other): `{args.other}` · "
            f"부트스트랩 {args.n_boot}회(seed {args.seed}) · 시나리오 {scenarios} · "
            f"커밋 `{table['git_commit'].iloc[0]}`\n\n"
            "부호 규약: `diff_*_abs = other − base`(명, 원 차이 — RMSE·MAE는 작을수록 좋다는 "
            "성질이라 부호만으로 우열을 읽을 수 없다) · "
            "`rel_*_% = (base − other) / base × 100`(양수 = other가 낫다)\n"
        )
        body = f"### W_창간_쌍차이\n\n{stat_eval.to_markdown(table.round(3))}\n"
        Path(args.out).write_text(head + "\n" + body, encoding="utf-8")
        print(f"[저장] {args.out}", flush=True)

    print(f"[완료] {time.time() - t0:.0f}s", flush=True)
    return table


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--base", required=True, help="기준 윈도우 라벨(예: w2024)")
    ap.add_argument("--other", required=True, help="비교 윈도우 라벨(예: w2023, 대개 더 긴 윈도우)")
    ap.add_argument(
        "--scenarios", nargs="+", default=None, help=f"기본 전부({','.join(SCENARIOS)})"
    )
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None, help="표를 마크다운으로 저장할 경로")
    args = ap.parse_args(argv)
    run(args)


if __name__ == "__main__":
    main(sys.argv[1:])
