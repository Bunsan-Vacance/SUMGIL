"""142 2단계 — 승하차 예측 개선율에 구간 붙이기(날짜 블록 부트스트랩 + Diebold-Mariano).

## 왜

90·93·198이 낸 수치는 전부 **점추정 하나**다("lookup 대비 RMSE +23.38%"). 200만 행이라
표본이 크다고들 하지만 행은 독립이 아니다 — 같은 날의 273역 × 20슬롯은 그날의 날씨·행사·
수집 상태를 공유한다. 그래서 유효 표본은 행 수가 아니라 **날짜 수(365)**에 가깝고, 구간을
붙이려면 그 단위로 재표본해야 한다.

## 방법

- **날짜 블록 부트스트랩.** 평가 구간의 날짜를 복원추출로 다시 뽑되 **한 날짜의 모든 행이
  같이 움직인다.** 날짜 단위 손실 합(제곱오차 합·절대오차 합·행 수)만 있으면 재표본마다
  RMSE·MAE를 정확히 다시 계산할 수 있어(가중 평균), 200만 행을 1,000번 다시 만들 필요가 없다.

      RMSE(재표본) = sqrt( Σ_d c_d · SSE_d / Σ_d c_d · n_d )    c_d = 그 날짜가 뽑힌 횟수

- **개선율**은 두 예측기의 같은 재표본 위에서 계산한다(쌍 비교) — 분자·분모가 같은 날짜
  집합이라 "그 해가 쉬웠나"가 상쇄된다.
- **Diebold-Mariano**는 날짜별 제곱오차 차이 `d_t = MSE_model(t) − MSE_lookup(t)`에 Newey-West
  (HAC) 분산을 써서 1회만 낸다. 표는 CI가 주역이고 DM은 "부호가 우연인가"의 보조 확인이다 —
  1,993,000행짜리 검정의 p는 어차피 0에 붙는다.

## 무엇을 비교하나

| 계열 | 어디서 | 구간의 뜻 |
| --- | --- | --- |
| `lightgbm`(배포 세트 `festival_selflag_d1sd_d7_resid`) | 현 배포 아티팩트 예측을 이 스크립트가 다시 낸다 | **날짜 블록 부트스트랩 95% CI** |
| `gru_v3`(198 채택 구성, 시드 3회) | `dl_input_metrics.parquet`(198) | **시드 3회 평균 ± 표준편차** — 행 단위 예측이 저장돼 있지 않아 부트스트랩이 불가능하다 |

두 구간의 뜻이 다르다는 것을 표에 그대로 적는다. 시드 표준편차는 "같은 데이터에서 학습을
다시 하면 얼마나 흔들리나"이고 부트스트랩 CI는 "다른 해였다면 얼마나 흔들렸을까"다.

실행(폴더명에 하이픈이 있어 파일 경로 호출이다):
    cd AI
    python validation/CROWD/significance-check/bootstrap.py --n 1000 --seed 0
    python validation/CROWD/significance-check/bootstrap.py --n 1000 --rebuild-losses
예상: 손실 집계 1회 2~3분(캐시), 부트스트랩 1,000회 수 초.
"""

from __future__ import annotations

import argparse
import sys
import time
from math import erfc, sqrt
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[2]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from app.CROWD.pipeline.dataset import CROWD_INTERIM, load_panel, time_split
from app.CROWD.pipeline.features import FEATURE_SETS
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline
from app.CROWD.pipeline.predictor import build_predictor, latest_artifact

VALIDATION_DIR = CROWD_INTERIM / "validation"
LOSSES_PATH = VALIDATION_DIR / "significance_daily_losses.parquet"
DL_METRICS_PATH = VALIDATION_DIR / "dl_input_metrics.parquet"
MODELS_DIR = AI_ROOT / "models" / "CROWD"

DEPLOY_SET = "festival_selflag_d1sd_d7_resid"
EVAL_START = pd.Timestamp("2025-01-01")
# 198 채택 구성(V3)의 시드 3회 — 같은 평가 행 집합에서 나온 수치다.
DL_RUN_PREFIX = "no_events_s"
DL_SCENARIO = "full"

# 파생 캐시에서 읽을 열 = 키·슬라이스 축·실측 + 배포 세트 피처(키에 이미 있는 범주 2열 제외)
DERIVED_COLS = ["date", "station_no", "line", "time_slot", "day_type", *TARGETS] + [
    c for c in FEATURE_SETS[DEPLOY_SET] if c not in ("station_no", "time_slot")
]
AXES = {"전체": None, "호선": "line", "요일유형": "day_type"}


# ── 날짜별 손실 집계 ──
def daily_losses(artifact: Path | None = None) -> pd.DataFrame:
    """2025 평가 구간의 (날짜 × 슬라이스 × 타깃) 손실 충분통계.

    부트스트랩에 필요한 것은 행별 예측이 아니라 **날짜별 합**이다(제곱오차 합·절대오차 합·행 수).
    이 세 값만 있으면 어떤 재표본에서도 RMSE·MAE가 정확히 복원된다 — 200만 행 예측을 1,000번
    다시 만들지 않기 위한 선택이고, 계산 결과는 행 단위로 돌린 것과 같다.

    예측은 `dl-resid-check/evaluate_dl.py`의 `full` 시나리오와 같은 경로다(현 배포 아티팩트 +
    파생 캐시 위 `CrowdPredictor.predict_derived`). 그래서 전체 축 개선율은 MODEL_REGISTRY 2절의
    +23.38 / +25.36과 일치해야 한다 — 어긋나면 아티팩트·파생 버전이 바뀐 것이다.
    """
    from app.CROWD.pipeline.dl.dataset import load_derived_slim

    t0 = time.time()
    panel = load_panel(with_events=True)
    train_raw, _ = time_split(panel)
    lookup = DayTypeLookupBaseline().fit(train_raw)

    derived = load_derived_slim(columns=DERIVED_COLS)
    test = derived[derived["date"] >= EVAL_START].reset_index(drop=True)
    lookup_pred = lookup.predict(test)

    artifact = Path(artifact) if artifact else latest_artifact(MODELS_DIR, kind="lightgbm")
    if artifact is None:
        raise SystemExit(
            f"LightGBM 아티팩트가 없다({MODELS_DIR}). "
            "`python -m app.CROWD.pipeline.train`으로 배포 세트를 먼저 학습할 것."
        )
    predictor = build_predictor("lightgbm", artifact_dir=artifact)
    if predictor.feature_set != DEPLOY_SET:
        raise SystemExit(
            f"아티팩트 세트가 배포 세트와 다르다: {predictor.feature_set} != {DEPLOY_SET}. "
            "--artifact로 배포 세트 아티팩트를 지정할 것."
        )
    keys = ["date", "station_no", "time_slot"]
    pred = predictor._inner.predict_derived(test)
    pred = test[keys].merge(pred[[*keys, *[f"{t}_pred" for t in TARGETS]]], on=keys, how="left")
    print(f"[예측] {artifact.name} · {len(test):,}행 · {time.time() - t0:.0f}s", flush=True)

    frame = test[["date", "line", "day_type"]].copy()
    finite = np.ones(len(test), dtype=bool)
    for target in TARGETS:
        truth = test[target].to_numpy(dtype="float64")
        base = lookup_pred[target].to_numpy(dtype="float64")
        model = pred[f"{target}_pred"].to_numpy(dtype="float64")
        finite &= np.isfinite(truth) & np.isfinite(base) & np.isfinite(model)
        frame[f"{target}__err_lookup"] = base - truth
        frame[f"{target}__err_model"] = model - truth
    frame = frame[finite].reset_index(drop=True)
    print(
        f"[공통 행] {int(finite.sum()):,} / {len(test):,} ({finite.mean() * 100:.2f}%)", flush=True
    )

    rows = []
    for axis, col in AXES.items():
        group = pd.Series("전체", index=frame.index) if col is None else frame[col]
        for target in TARGETS:
            err_b = frame[f"{target}__err_lookup"]
            err_m = frame[f"{target}__err_model"]
            agg = (
                pd.DataFrame(
                    {
                        "date": frame["date"],
                        "group": group.astype(str),
                        "n": 1,
                        "sse_lookup": err_b**2,
                        "sae_lookup": err_b.abs(),
                        "sse_model": err_m**2,
                        "sae_model": err_m.abs(),
                    }
                )
                .groupby(["date", "group"], observed=True)
                .sum()
                .reset_index()
                .assign(axis=axis, target=target)
            )
            rows.append(agg)
    out = pd.concat(rows, ignore_index=True)
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    out.to_parquet(LOSSES_PATH, index=False)
    print(f"[손실] 저장: {LOSSES_PATH.name} ({len(out):,}행, {time.time() - t0:.0f}s)", flush=True)
    return out


def load_losses(artifact: Path | None = None, rebuild: bool = False) -> pd.DataFrame:
    if LOSSES_PATH.exists() and not rebuild:
        return pd.read_parquet(LOSSES_PATH)
    return daily_losses(artifact)


# ── 부트스트랩(순수 함수) ──
def resample_dates(n_dates: int, n_boot: int, seed: int) -> np.ndarray:
    """날짜 인덱스를 복원추출한 (n_boot, n_dates) 행렬. 같은 seed면 항상 같다.

    행 단위가 아니라 **날짜 단위**로 뽑는 것이 이 검증의 전부다 — 같은 날의 5,460행은
    날씨·행사·수집 상태를 공유하므로 따로 뽑으면 독립 가정이 깨져 구간이 실제보다 좁아진다.
    """
    rng = np.random.default_rng(seed)
    return rng.integers(0, n_dates, size=(n_boot, n_dates))


def resample_counts(index_matrix: np.ndarray, n_dates: int) -> np.ndarray:
    """재표본 인덱스를 날짜별 등장 횟수 (n_boot, n_dates)로 바꾼다 — 이후는 가중합이다."""
    return np.stack([np.bincount(row, minlength=n_dates) for row in index_matrix]).astype(float)


def weighted_rmse(counts: np.ndarray, sse: np.ndarray, n: np.ndarray) -> np.ndarray:
    """재표본별 RMSE. `counts`는 (n_boot, n_dates), `sse`·`n`은 (n_dates,)."""
    denom = counts @ n
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.sqrt(np.where(denom > 0, (counts @ sse) / denom, np.nan))


def weighted_mae(counts: np.ndarray, sae: np.ndarray, n: np.ndarray) -> np.ndarray:
    denom = counts @ n
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(denom > 0, (counts @ sae) / denom, np.nan)


def improvement_pct(base: np.ndarray, model: np.ndarray) -> np.ndarray:
    """lookup 대비 개선율(%) — 90 이후 모든 문서가 쓰는 정의와 같다."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(base > 0, (1.0 - model / base) * 100.0, np.nan)


def percentile_ci(samples: np.ndarray, level: float = 0.95) -> tuple[float, float]:
    """백분위 신뢰구간. NaN 재표본은 버린다(그 슬라이스에 행이 없는 날짜만 뽑힌 경우)."""
    clean = samples[np.isfinite(samples)]
    if clean.size == 0:
        return float("nan"), float("nan")
    tail = (1.0 - level) / 2.0 * 100.0
    return float(np.percentile(clean, tail)), float(np.percentile(clean, 100.0 - tail))


# ── Diebold-Mariano(순수 함수) ──
def newey_west_variance(x: np.ndarray, lags: int) -> float:
    """장기 분산의 HAC(Newey-West, Bartlett 가중) 추정 — 날짜 손실차의 자기상관을 흡수한다."""
    x = np.asarray(x, dtype="float64")
    n = x.size
    if n < 2:
        return float("nan")
    centered = x - x.mean()
    gamma0 = float(centered @ centered / n)
    total = gamma0
    for lag in range(1, min(lags, n - 1) + 1):
        gamma = float(centered[lag:] @ centered[:-lag] / n)
        total += 2.0 * (1.0 - lag / (lags + 1.0)) * gamma
    return total


def default_lags(n: int) -> int:
    """Newey-West 기본 절단 — 표준 규칙 floor(4·(T/100)^(2/9))."""
    return max(int(4.0 * (n / 100.0) ** (2.0 / 9.0)), 1)


def diebold_mariano(diff: np.ndarray, lags: int | None = None) -> dict[str, float]:
    """날짜별 손실차 `d_t = 손실_model − 손실_lookup`에 대한 DM 통계량과 양측 p.

    음수 통계량 = 모델의 손실이 작다. 정규 근사를 쓰고(표본이 365일), 소표본 보정(Harvey 등)은
    쓰지 않는다 — 표의 주역은 CI이고 DM은 부호 확인용이다.
    """
    d = np.asarray(diff, dtype="float64")
    d = d[np.isfinite(d)]
    n = d.size
    if n < 3:
        return {"n": n, "mean_diff": float("nan"), "stat": float("nan"), "p": float("nan")}
    lags = default_lags(n) if lags is None else lags
    var = newey_west_variance(d, lags)
    stat = float(d.mean() / sqrt(var / n)) if var > 0 else float("nan")
    p = erfc(abs(stat) / sqrt(2.0)) if np.isfinite(stat) else float("nan")
    return {"n": n, "mean_diff": float(d.mean()), "lags": lags, "stat": stat, "p": float(p)}


# ── 실행 ──
def bootstrap_table(losses: pd.DataFrame, n_boot: int, seed: int) -> pd.DataFrame:
    """슬라이스 × 타깃마다 RMSE·MAE 개선율 점추정과 95% CI."""
    dates = np.sort(losses["date"].unique())
    n_dates = len(dates)
    counts = resample_counts(resample_dates(n_dates, n_boot, seed), n_dates)
    date_index = {d: i for i, d in enumerate(dates)}

    rows = []
    for (axis, group, target), sub in losses.groupby(["axis", "group", "target"], observed=True):
        vec = {
            c: np.zeros(n_dates)
            for c in ("n", "sse_lookup", "sae_lookup", "sse_model", "sae_model")
        }
        pos = sub["date"].map(date_index).to_numpy()
        for col, values in vec.items():
            values[pos] = sub[col].to_numpy(dtype="float64")

        boot_rmse = improvement_pct(
            weighted_rmse(counts, vec["sse_lookup"], vec["n"]),
            weighted_rmse(counts, vec["sse_model"], vec["n"]),
        )
        boot_mae = improvement_pct(
            weighted_mae(counts, vec["sae_lookup"], vec["n"]),
            weighted_mae(counts, vec["sae_model"], vec["n"]),
        )
        full = np.ones((1, n_dates))
        point_rmse = improvement_pct(
            weighted_rmse(full, vec["sse_lookup"], vec["n"]),
            weighted_rmse(full, vec["sse_model"], vec["n"]),
        )[0]
        point_mae = improvement_pct(
            weighted_mae(full, vec["sae_lookup"], vec["n"]),
            weighted_mae(full, vec["sae_model"], vec["n"]),
        )[0]
        rmse_lo, rmse_hi = percentile_ci(boot_rmse)
        mae_lo, mae_hi = percentile_ci(boot_mae)

        # DM — 날짜별 평균제곱오차 차이(모델 − lookup). 행이 없는 날짜는 뺀다.
        ok = vec["n"] > 0
        dm = diebold_mariano(
            (vec["sse_model"][ok] - vec["sse_lookup"][ok]) / vec["n"][ok],
        )
        rows.append(
            {
                "series": "lightgbm_d1sd",
                "ci_kind": "날짜 블록 부트스트랩",
                "axis": axis,
                "group": group,
                "target": target,
                "n_rows": int(vec["n"].sum()),
                "n_dates": int(ok.sum()),
                "RMSE_개선율_%": point_rmse,
                "RMSE_CI_low": rmse_lo,
                "RMSE_CI_high": rmse_hi,
                "MAE_개선율_%": point_mae,
                "MAE_CI_low": mae_lo,
                "MAE_CI_high": mae_hi,
                "DM_stat": dm["stat"],
                "DM_p": dm["p"],
                "DM_lags": dm.get("lags"),
            }
        )
    return pd.DataFrame(rows)


def dl_seed_table(path: Path = DL_METRICS_PATH) -> pd.DataFrame:
    """198 채택 구성(V3) 시드 3회의 평균 ± 표준편차 — 부트스트랩이 아니라 시드 산포다.

    행 단위 예측이 저장돼 있지 않아(`evaluate_dl`은 7일 간격 표본만 남긴다) 같은 방식의
    구간을 낼 수 없다. 같은 표에 놓되 `ci_kind`로 구분한다.
    """
    if not path.exists():
        print(f"[안내] {path.name}이 없어 DL 행을 건너뛴다.", flush=True)
        return pd.DataFrame()
    metrics = pd.read_parquet(path)
    sub = metrics[
        metrics["run"].str.startswith(DL_RUN_PREFIX) & (metrics["scenario"] == DL_SCENARIO)
    ].copy()
    sub["axis"] = sub["axis"].map({"전체": "전체", "line": "호선", "day_type": "요일유형"})
    sub = sub.dropna(subset=["axis"])
    agg = (
        sub.groupby(["axis", "group", "target"], observed=True)
        .agg(
            n_rows=("n", "first"),
            seeds=("run", "nunique"),
            rmse_mean=("RMSE_개선율_%", "mean"),
            rmse_sd=("RMSE_개선율_%", "std"),
            mae_mean=("MAE_개선율_%", "mean"),
            mae_sd=("MAE_개선율_%", "std"),
        )
        .reset_index()
    )
    return pd.DataFrame(
        {
            "series": "gru_v3",
            "ci_kind": "시드 3회 표준편차",
            "axis": agg["axis"],
            "group": agg["group"],
            "target": agg["target"],
            "n_rows": agg["n_rows"].astype(int),
            "n_dates": np.nan,
            "RMSE_개선율_%": agg["rmse_mean"],
            "RMSE_CI_low": agg["rmse_mean"] - agg["rmse_sd"],
            "RMSE_CI_high": agg["rmse_mean"] + agg["rmse_sd"],
            "MAE_개선율_%": agg["mae_mean"],
            "MAE_CI_low": agg["mae_mean"] - agg["mae_sd"],
            "MAE_CI_high": agg["mae_mean"] + agg["mae_sd"],
            "DM_stat": np.nan,
            "DM_p": np.nan,
            "DM_lags": np.nan,
        }
    )


def _fmt(row: pd.Series, metric: str) -> str:
    return (
        f"{row[f'{metric}_개선율_%']:+.2f} "
        f"[{row[f'{metric}_CI_low']:+.2f}, {row[f'{metric}_CI_high']:+.2f}]"
    )


def summarize(table: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    out = []
    for axis in ("전체", "호선", "요일유형"):
        sub = table[table["axis"] == axis].copy()
        if sub.empty:
            continue
        sub["RMSE 개선율 % [95% CI]"] = sub.apply(lambda r: _fmt(r, "RMSE"), axis=1)
        sub["MAE 개선율 % [95% CI]"] = sub.apply(lambda r: _fmt(r, "MAE"), axis=1)
        sub["CI가 0을 포함"] = np.where(sub["RMSE_CI_low"] <= 0, "예", "")
        cols = [
            "series",
            "ci_kind",
            "group",
            "target",
            "n_rows",
            "RMSE 개선율 % [95% CI]",
            "MAE 개선율 % [95% CI]",
            "CI가 0을 포함",
        ]
        out.append((axis, sub.sort_values(["group", "target", "series"])[cols]))
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--n", type=int, default=1000, help="부트스트랩 재표본 수")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--artifact", default=None, help="LightGBM 아티팩트 디렉터리(기본: 최신)")
    ap.add_argument("--rebuild-losses", action="store_true", help="날짜별 손실 집계를 다시 만든다")
    ap.add_argument("--no-dl", action="store_true", help="GRU 시드 행을 빼고 낸다")
    ap.add_argument("--save-results", default=str(VALIDATION_DIR / "significance_ci.parquet"))
    args = ap.parse_args(argv)

    losses = load_losses(args.artifact, rebuild=args.rebuild_losses)
    table = bootstrap_table(losses, args.n, args.seed)
    if not args.no_dl:
        table = pd.concat([table, dl_seed_table()], ignore_index=True)

    for axis, frame in summarize(table):
        print(f"\n### {axis}\n{frame.to_string(index=False)}")

    total = table[(table["axis"] == "전체") & (table["series"] == "lightgbm_d1sd")]
    print("\n### Diebold-Mariano (날짜별 MSE 차이, Newey-West HAC)")
    print(
        total[["target", "n_dates", "DM_lags", "DM_stat", "DM_p"]].to_string(index=False),
        flush=True,
    )

    path = Path(args.save_results)
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(path, index=False)
    print(f"저장: {path}")


if __name__ == "__main__":
    main(sys.argv[1:])
