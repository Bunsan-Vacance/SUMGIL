"""92번 — 모델 계열 비교: lookup+LightGBM(90 배포) vs Chronos zero-shot vs LLM 수치 예측. 같은 표본·같은 D−1.

질문: 같은 조건(2024 학습 창까지의 정보만, 대상 날짜의 20슬롯 승하차 예측)에서 Transformer 시계열 모델과
LLM이 90의 잔차 모델보다 **RMSE·MAE 둘 다 2%p 이상** 나은가? 아니면 90 모델을 확정한다.

비교군(전부 D−1: 대상 날짜 전날까지의 실측만 안다)
- `lookup`       — 요일유형×역×시간대 평균(2024). 기준선.
- `lightgbm`     — lookup + LightGBM 잔차(`festival_selflag_d1d7_resid`, 90 배포 세트).
- `chronos`      — amazon/chronos-t5-small zero-shot. 역×타깃 시계열(20슬롯/일 이어 붙임) 최근 `--context-days`
                   일을 문맥으로 다음 20스텝. 이벤트·요일유형을 모른다.
- `chronos_resid`— 같은 Chronos를 **lookup 잔차 시계열**에 적용 + lookup. 요일유형 정보를 lookup이 대신 준다.
- `llm`          — 최근 7일 시차·요일유형·이벤트를 프롬프트로 주고 20슬롯 JSON을 받는다. `CROWD_LLM_API_KEY`
                   없으면 프롬프트 표본만 저장하고 건너뛴다(미완 표시).

표본: `--n-stations`개 역(seed 고정) × `--n-dates`일(2025 균등 간격) × 2 타깃. Chronos는 CPU에서 역 50 × 30일이면
수 분. 전체 273역으로 늘리기 전에 여기서 시간을 잰다(`AI/CLAUDE.md` 실험 효율).

실행:
    cd AI
    python validation/CROWD/sim-eval/compare_families.py --n-stations 50 --n-dates 30
    python validation/CROWD/sim-eval/compare_families.py --skip-chronos          # LightGBM·lookup만
결과: 표준 출력 + `--out` 마크다운 + data/CROWD/interim/validation/family_compare_{metrics,preds}.parquet
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[2]
for p in (str(AI_ROOT), str(AI_ROOT / "validation" / "CROWD" / "baseline-check")):
    if p not in sys.path:
        sys.path.insert(0, p)

from baseline import regression_metrics
from evaluate_final import to_markdown

from app.CROWD.pipeline.dataset import load_or_build_derived, load_panel, time_split
from app.CROWD.pipeline.features import SLOT_ORDER, build_matrix
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline
from app.CROWD.pipeline.train import train_models

OUT_DIR = AI_ROOT / "data" / "CROWD" / "interim" / "validation"
DEPLOY_SET = "festival_selflag_d1d7_resid"
CHRONOS_MODEL = "amazon/chronos-t5-small"
KEY = ["date", "station_no", "time_slot"]


# ── 표본 ──
def pick_sample(test: pd.DataFrame, n_stations: int, n_dates: int, seed: int = 0):
    rng = np.random.default_rng(seed)
    stations = np.sort(rng.choice(test["station_no"].unique(), size=n_stations, replace=False))
    dates = np.sort(test["date"].drop_duplicates().to_numpy())
    # 2025-02 이후에서 균등 간격(1월은 전날·1주 전 시차가 2024 꼬리를 참조해 경계 효과가 있다)
    dates = dates[dates >= np.datetime64("2025-02-01")]
    idx = np.linspace(0, len(dates) - 1, n_dates).round().astype(int)
    return stations, dates[idx]


# ── 90 배포 모델 ──
def predict_lightgbm(train_d: pd.DataFrame, test_d: pd.DataFrame, lookup: DayTypeLookupBaseline):
    t0 = time.time()
    models = train_models(train_d, lookup, DEPLOY_SET)
    X = build_matrix(test_d, DEPLOY_SET)
    lk = lookup.predict(test_d)
    out = test_d[KEY].copy()
    for t in TARGETS:
        out[f"{t}_lookup"] = lk[t].to_numpy()
        out[f"{t}_lightgbm"] = lk[t].to_numpy() + models[t]["__all__"].predict(X)
    print(f"[lightgbm] 학습+예측 {time.time() - t0:.0f}s", flush=True)
    return out


# ── Chronos zero-shot ──
def _series_matrix(panel: pd.DataFrame, station_no: int, target: str, end_date, days: int):
    """역 하나의 [end_date − days, end_date) 20슬롯/일 시계열 → 1차원 배열(결측 슬롯은 앞 값으로)."""
    start = pd.Timestamp(end_date) - pd.Timedelta(days=days)
    s = panel[
        (panel["station_no"] == station_no) & (panel["date"] >= start) & (panel["date"] < end_date)
    ]
    mat = s.pivot_table(index="date", columns="time_slot", values=target).reindex(
        columns=SLOT_ORDER
    )
    full_idx = pd.date_range(start, pd.Timestamp(end_date) - pd.Timedelta(days=1), freq="D")
    mat = mat.reindex(full_idx).ffill().bfill()
    return mat.to_numpy(dtype=float).ravel()


def predict_chronos(
    panel: pd.DataFrame,
    resid_panel: pd.DataFrame,
    sample_keys: pd.DataFrame,
    context_days: int,
    batch_size: int = 32,
    model_name: str = CHRONOS_MODEL,
) -> pd.DataFrame:
    """(station_no, date) 표본마다 원값·잔차 시계열 두 벌을 Chronos로 20스텝 예측(중앙값)."""
    import torch
    from chronos import ChronosPipeline

    t0 = time.time()
    pipe = ChronosPipeline.from_pretrained(model_name, device_map="cpu", torch_dtype=torch.float32)
    print(f"[chronos] 모델 로드 {time.time() - t0:.0f}s", flush=True)
    rows = []
    jobs = []  # (station, date, target, kind, context)
    for st, d in sample_keys[["station_no", "date"]].itertuples(index=False):
        for t in TARGETS:
            jobs.append((st, d, t, "raw", _series_matrix(panel, st, t, d, context_days)))
            jobs.append(
                (st, d, t, "resid", _series_matrix(resid_panel, st, f"{t}_resid", d, context_days))
            )
    print(f"[chronos] 시계열 {len(jobs):,}개 · 문맥 {context_days}일×20", flush=True)
    for i in range(0, len(jobs), batch_size):
        chunk = jobs[i : i + batch_size]
        ctx = [torch.tensor(j[4]) for j in chunk]
        fc = pipe.predict(ctx, prediction_length=len(SLOT_ORDER), num_samples=20)  # [b, s, 20]
        med = fc.median(dim=1).values.numpy()
        for (st, d, t, kind, _), pred in zip(chunk, med):
            for slot, v in zip(SLOT_ORDER, pred):
                rows.append((d, st, slot, t, kind, float(v)))
        if (i // batch_size) % 20 == 0:
            print(f"[chronos] {i + len(chunk):,}/{len(jobs):,} {time.time() - t0:.0f}s", flush=True)
    long = pd.DataFrame(rows, columns=["date", "station_no", "time_slot", "target", "kind", "pred"])
    wide = long.pivot_table(index=KEY, columns=["target", "kind"], values="pred")
    wide.columns = [
        f"{t}_chronos" if k == "raw" else f"{t}_chronos_residpart" for t, k in wide.columns
    ]
    print(f"[chronos] 완료 {time.time() - t0:.0f}s", flush=True)
    return wide.reset_index()


# ── LLM (키 없으면 프롬프트만 저장) ──
def build_prompt(hist: pd.DataFrame, target_row: pd.Series, target: str) -> str:
    lines = [
        "당신은 서울 지하철 역별 시간대 승하차 인원을 예측한다. 아래는 한 역의 최근 7일 시간대별 값이다.",
        (
            f"역: {target_row['station_name']}({target_row['line']}), "
            f"대상 날짜: {target_row['date']:%Y-%m-%d} ({target_row['day_type']}), "
            f"경기 {int(target_row.get('game_count', 0))}건, "
            f"축제 {int(target_row.get('festival_count', 0))}건."
        ),
        f"타깃: {target}. 시간대 순서: {', '.join(SLOT_ORDER)}.",
    ]
    for d, g in hist.groupby("date"):
        vals = g.set_index("time_slot")[target].reindex(SLOT_ORDER).round().astype("Int64").tolist()
        lines.append(f"{d:%m-%d}({g['day_type'].iloc[0]}): {vals}")
    lines.append("대상 날짜의 20개 시간대 값을 JSON 배열(정수 20개)로만 답하라.")
    return "\n".join(lines)


def predict_llm(
    panel: pd.DataFrame, sample_keys: pd.DataFrame, n_prompt_save: int = 5
) -> pd.DataFrame | None:
    key = os.environ.get("CROWD_LLM_API_KEY")
    prompts = []
    for st, d in sample_keys[["station_no", "date"]].head(n_prompt_save).itertuples(index=False):
        hist = panel[
            (panel["station_no"] == st)
            & (panel["date"] < d)
            & (panel["date"] >= d - pd.Timedelta(days=7))
        ]
        row = panel[(panel["station_no"] == st) & (panel["date"] == d)].iloc[0]
        prompts.append(
            {
                "station_no": int(st),
                "date": f"{d:%Y-%m-%d}",
                "prompt": build_prompt(hist, row, "boarding"),
            }
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "family_compare_llm_prompts.json").write_text(
        json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not key:
        print("[llm] CROWD_LLM_API_KEY 없음 — 프롬프트 표본만 저장, 비교는 미완", flush=True)
        return None
    raise NotImplementedError(
        "LLM 호출은 키 설정 후 연결한다(계획 파일 4단계 — 호출 비용 확인 뒤 실행)"
    )


# ── 실행 ──
def run(n_stations: int, n_dates: int, context_days: int, skip_chronos: bool, seed: int):
    t0 = time.time()
    panel = load_panel(with_events=True)
    train, test = time_split(panel)
    lookup = DayTypeLookupBaseline().fit(train)
    derived = load_or_build_derived(panel, lookup)
    train_d, test_d = time_split(derived)
    stations, dates = pick_sample(test, n_stations, n_dates, seed)
    sample = test_d[test_d["station_no"].isin(stations) & test_d["date"].isin(dates)].reset_index(
        drop=True
    )
    print(
        f"[표본] 역 {len(stations)} × 날짜 {len(dates)} = {len(sample):,}행 · {time.time() - t0:.0f}s",
        flush=True,
    )

    preds = predict_lightgbm(train_d, sample, lookup)
    actual = sample[KEY + TARGETS]
    preds = preds.merge(actual, on=KEY)

    if not skip_chronos:
        resid = lookup.residuals(panel)
        resid_panel = pd.concat([panel[["date", "station_no", "time_slot"]], resid], axis=1)
        keys = sample[["station_no", "date"]].drop_duplicates()
        ch = predict_chronos(panel, resid_panel, keys, context_days)
        preds = preds.merge(ch, on=KEY, how="left")
        for t in TARGETS:
            preds[f"{t}_chronos_resid"] = preds[f"{t}_lookup"] + preds[f"{t}_chronos_residpart"]
            preds[f"{t}_chronos"] = preds[f"{t}_chronos"].clip(lower=0)
            preds[f"{t}_chronos_resid"] = preds[f"{t}_chronos_resid"].clip(lower=0)
    predict_llm(panel, sample[["station_no", "date"]].drop_duplicates())

    families = ["lookup", "lightgbm"] + ([] if skip_chronos else ["chronos", "chronos_resid"])
    rows = []
    for t in TARGETS:
        base = regression_metrics(preds[t], preds[f"{t}_lookup"])
        for f in families:
            m = regression_metrics(preds[t], preds[f"{t}_{f}"])
            rows.append(
                {
                    "target": t,
                    "family": f,
                    "RMSE": round(m["rmse"], 1),
                    "MAE": round(m["mae"], 1),
                    "MAPE_%": round(m["mape"], 1),
                    "RMSE_개선율_%": round((1 - m["rmse"] / base["rmse"]) * 100, 1),
                    "MAE_개선율_%": round((1 - m["mae"] / base["mae"]) * 100, 1),
                    "n": m["n"],
                }
            )
    metrics = pd.DataFrame(rows)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    preds.to_parquet(OUT_DIR / "family_compare_preds.parquet", index=False)
    metrics.to_parquet(OUT_DIR / "family_compare_metrics.parquet", index=False)
    print(
        f"\n### 모델 계열 비교 — 역 {n_stations} × 날짜 {n_dates}, 2025, D−1\n{metrics.to_string(index=False)}"
    )
    print(f"[총 {time.time() - t0:.0f}s]")
    return metrics


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--n-stations", type=int, default=50)
    ap.add_argument("--n-dates", type=int, default=30)
    ap.add_argument("--context-days", type=int, default=28)
    ap.add_argument("--skip-chronos", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    metrics = run(args.n_stations, args.n_dates, args.context_days, args.skip_chronos, args.seed)
    if args.out:
        Path(args.out).write_text(
            f"### 모델 계열 비교 — 역 {args.n_stations} × 날짜 {args.n_dates}, 2025, D−1\n\n{to_markdown(metrics)}\n",
            encoding="utf-8",
        )
        print(f"[저장] {args.out}")


if __name__ == "__main__":
    main(sys.argv[1:])
