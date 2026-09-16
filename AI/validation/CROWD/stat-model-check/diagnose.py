"""145 통계 모형 비교 검증 — 0 클립 비대칭(표 I)·92 표본 대표성(표 J) 진단.

## 왜

`RESULTS.md` 10절 미해결에 남아 있던 두 가지 —

1. 등급 후처리(0 클립)가 LightGBM에 유리한 특혜인가(표 E의 0.08%p 우위 논쟁)
2. 92 표본(50역×30일)이 전체 축과 순위가 뒤집히는 이유가 역 크기 편향인가

— 를 규명한 근거가 임시 스크립트로만 남아 있어 재현이 안 됐다. 이 스크립트가 정식판이다.
`predict_all.py`가 만든 `stat_preds_*.parquet`를 그대로 읽는다(재예측 없음).

## 표

- **I**(`--clip`) — 계열별 음수 예측 빈도·깊이와, 0 클립이 주는 MAE 이득. 배율표·등급 파이프라인이
  실측에만 적합됐다는 199 규약이 지켜졌다면, 클립 이득은 발산이 큰 계열(SARIMA류)에 몰려야 하고
  "LightGBM에 맞춘 후처리" 가설은 기각돼야 한다.
- **J**(`--sample`) — `sim-eval/compare_families.pick_sample(test, 50, 30, seed=0)`과 같은 표본을
  다시 뽑아, 표본 vs 전체 RMSE·역 평균 승차·제곱오차(SSE) 집중도를 비교한다. 표 D(92 표본 점추정)의
  RMSE와 정확히 같아야 재현이 맞다.

기본은 둘 다 실행한다. `--clip`만 또는 `--sample`만 주면 그것만 돈다.

실행(폴더명에 하이픈이 있어 파일 경로로 돈다. `predict_all.py`로 예측을 먼저 만들어야 한다):
    cd AI
    python validation/CROWD/stat-model-check/diagnose.py
    python validation/CROWD/stat-model-check/diagnose.py --clip
    python validation/CROWD/stat-model-check/diagnose.py --sample
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
for _p in (str(AI_ROOT), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import evaluate

from app.CROWD.pipeline.dataset import CROWD_PROCESSED, PANEL_NAME
from app.CROWD.pipeline.lookup import TARGETS

OUT_DIR = evaluate.OUT_DIR
KEY = evaluate.KEY
SPLIT_DATE = evaluate.SPLIT_DATE
CLIP_NAMES = ["lookup", *evaluate.CANDIDATE_SERIES]
SAMPLE_NAMES = ["lookup", "snaive_d7", "ols_series", "sarimax_resid", evaluate.LIGHTGBM]


def _read_predictions(names: list[str], value_suffix: str = "_pred") -> dict[str, pd.DataFrame]:
    """계열별 예측 parquet을 읽어 `{target}__{name}` 컬럼으로 정리한다."""
    frames: dict[str, pd.DataFrame] = {}
    for name in names:
        path = OUT_DIR / f"stat_preds_{name}.parquet"
        frame = pd.read_parquet(path)
        cols = [*KEY] + [c for c in frame.columns if c.endswith(value_suffix)]
        frames[name] = frame[cols].rename(
            columns={f"{t}{value_suffix}": f"{t}__{name}" for t in TARGETS}
        )
    return frames


# ── 표 I: 0 클립 비대칭 ──
def table_i(names: list[str] = CLIP_NAMES) -> pd.DataFrame:
    """계열·타깃별 음수 예측 빈도·평균 깊이와 0 클립의 MAE 이득(공통 유한 행 기준)."""
    frames = _read_predictions(names)
    merged = frames[names[0]]
    for name in names[1:]:
        merged = merged.merge(frames[name], on=KEY, how="inner")

    panel = pd.read_parquet(CROWD_PROCESSED / PANEL_NAME, columns=[*KEY, *TARGETS])
    merged = merged.merge(panel, on=KEY, how="inner")

    ok = np.ones(len(merged), dtype=bool)
    for name in names:
        for t in TARGETS:
            ok &= np.isfinite(merged[f"{t}__{name}"].to_numpy())
    for t in TARGETS:
        ok &= np.isfinite(merged[t].to_numpy())
    merged = merged[ok]
    print(f"[표 I] 공통 유한 행 {len(merged):,}", flush=True)

    rows = []
    for name in names:
        for t in TARGETS:
            y = merged[t].to_numpy(dtype="float64")
            p = merged[f"{t}__{name}"].to_numpy(dtype="float64")
            p_clip = np.clip(p, 0.0, None)
            neg = p < 0
            rows.append(
                {
                    "계열": name,
                    "타깃": t,
                    "음수행": int(neg.sum()),
                    "음수비율_%": round(100 * float(neg.mean()), 3),
                    "음수_평균깊이": round(float(-p[neg].mean()) if neg.any() else 0.0, 1),
                    "RMSE_raw": round(float(np.sqrt(np.mean((y - p) ** 2))), 3),
                    "RMSE_clip": round(float(np.sqrt(np.mean((y - p_clip) ** 2))), 3),
                    "MAE_raw": round(float(np.mean(np.abs(y - p))), 4),
                    "MAE_clip": round(float(np.mean(np.abs(y - p_clip))), 4),
                }
            )
    result = pd.DataFrame(rows)
    result["MAE_이득"] = (result["MAE_raw"] - result["MAE_clip"]).round(4)
    result["MAE_이득_%p"] = (100 * result["MAE_이득"] / result["MAE_raw"]).round(4)
    return result


# ── 표 J: 92 표본 대표성 ──
def table_j(names: list[str] = SAMPLE_NAMES) -> tuple[pd.DataFrame, dict]:
    """92 표본(50역×30일)과 전체 축의 RMSE·역 평균 승차·SSE 집중도 비교(승차 기준)."""
    panel = pd.read_parquet(CROWD_PROCESSED / PANEL_NAME, columns=[*KEY, *TARGETS])
    test = panel[panel["date"] >= SPLIT_DATE]
    # 92·145와 같은 표본이어야 한다 — 반드시 이 함수를 그대로 import해서 쓴다.
    stations, dates = evaluate.compare_families.pick_sample(test, 50, 30, seed=0)

    merged: pd.DataFrame | None = None
    for name in names:
        frame = pd.read_parquet(OUT_DIR / f"stat_preds_{name}.parquet")
        frame = frame[[*KEY, "boarding_pred"]].rename(columns={"boarding_pred": name})
        merged = frame if merged is None else merged.merge(frame, on=KEY, how="inner")
    merged = merged.merge(test, on=KEY, how="inner")
    merged = merged[
        np.isfinite(merged[names].to_numpy()).all(axis=1) & merged["boarding"].notna()
    ].reset_index(drop=True)

    in_sample = (merged["station_no"].isin(stations) & merged["date"].isin(dates)).to_numpy()
    station_means = merged.groupby("station_no")["boarding"].mean()
    summary = {
        "전체_행": len(merged),
        "표본_행": int(in_sample.sum()),
        "표본_비율_%": round(100 * float(in_sample.mean()), 2),
        "표본역_역평균_승차": round(float(station_means.loc[stations].mean()), 1),
        "전체역_역평균_승차": round(float(station_means.mean()), 1),
        "표본_역_수": len(stations),
        "전체_역_수": int(station_means.shape[0]),
    }
    print(
        f"[표 J] 전체 행 {summary['전체_행']:,} / 표본 행 {summary['표본_행']:,} "
        f"({summary['표본_비율_%']}%)",
        flush=True,
    )
    print(
        f"[표 J] 표본 {summary['표본_역_수']}역 역평균 승차 {summary['표본역_역평균_승차']} vs "
        f"전체 {summary['전체_역_수']}역 {summary['전체역_역평균_승차']}",
        flush=True,
    )

    rows = []
    boarding = merged["boarding"].to_numpy(dtype="float64")
    for name in names:
        e2 = (boarding - merged[name].to_numpy(dtype="float64")) ** 2
        order = np.argsort(e2)[::-1]
        sorted_e2 = e2[order]
        total = sorted_e2.sum()
        k = max(1, int(len(sorted_e2) * 0.001))
        top_idx = order[:k]
        captured = 100 * float(in_sample[top_idx].mean())
        rows.append(
            {
                "계열": name,
                "전체RMSE": round(float(np.sqrt(e2.mean())), 1),
                "표본RMSE": round(float(np.sqrt(e2[in_sample].mean())), 1),
                "top0.1%_SSE비중_%": round(100 * float(sorted_e2[:k].sum() / total), 1),
                "표본이_담은_top0.1%_행_%": round(captured, 2),
            }
        )
    return pd.DataFrame(rows), summary


def _save_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[저장] {path.relative_to(AI_ROOT)}", flush=True)


def run(args: argparse.Namespace) -> None:
    t0 = time.time()
    run_clip = args.clip or not (args.clip or args.sample)
    run_sample = args.sample or not (args.clip or args.sample)

    if run_clip:
        table = table_i()
        print(f"\n### 표 I — 0 클립 비대칭\n{table.to_string(index=False)}", flush=True)
        _save_json(OUT_DIR / "diagnose_clip.json", table.to_dict(orient="records"))

    if run_sample:
        table, summary = table_j()
        print(f"\n### 표 J — 92 표본 대표성\n{table.to_string(index=False)}", flush=True)
        _save_json(
            OUT_DIR / "diagnose_sample.json",
            {"summary": summary, "table": table.to_dict(orient="records")},
        )

    print(f"[완료] {time.time() - t0:.0f}s", flush=True)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--clip", action="store_true", help="표 I(0 클립 비대칭)만 실행")
    ap.add_argument("--sample", action="store_true", help="표 J(92 표본 대표성)만 실행")
    args = ap.parse_args(argv)
    run(args)


if __name__ == "__main__":
    main(sys.argv[1:])
