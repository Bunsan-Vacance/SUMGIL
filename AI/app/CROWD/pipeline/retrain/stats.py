"""재학습 루프 통계 — 날짜 블록 부트스트랩·Diebold-Mariano 순수 함수.

앞쪽 순수 함수(`resample_dates` ~ `diebold_mariano`)는 `validation/CROWD/significance-check/
bootstrap.py`(출처)에서 그대로 옮겼다 — `app/`은 `validation/`을 import하지 않으므로 복사하고,
`test_crowd_retrain_stats.py`가 원본과 결과가 같은지 대조한다. 뒤쪽은 채점 결과(날짜별 손실)
위에서 쓰는 층화·이동 블록 변형과 개선율 부트스트랩 래퍼다.
"""

from __future__ import annotations

from math import erfc, sqrt

import numpy as np
import pandas as pd


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


# ── 채점 결과 위의 확장 ──
def daily_losses(rows: pd.DataFrame, pred_col: str, actual_col: str) -> pd.DataFrame:
    """행 단위 예측·실측에서 날짜별 충분통계(`date, sse, sae, n`)를 만든다. 날짜당 한 행.

    예측·실측 중 하나라도 유한하지 않은 행은 뺀다.
    """
    pred = rows[pred_col].to_numpy(dtype="float64")
    actual = rows[actual_col].to_numpy(dtype="float64")
    ok = np.isfinite(pred) & np.isfinite(actual)
    err = pred[ok] - actual[ok]
    frame = pd.DataFrame(
        {
            "date": rows["date"].to_numpy()[ok],
            "sse": err**2,
            "sae": np.abs(err),
            "n": 1,
        }
    )
    if frame.empty:
        return pd.DataFrame({"date": [], "sse": [], "sae": [], "n": []})
    return frame.groupby("date", as_index=False).sum().sort_values("date").reset_index(drop=True)


def stratified_resample_dates(strata: np.ndarray, n_boot: int, seed: int) -> np.ndarray:
    """층(예: 요일유형) 안에서만 날짜를 복원추출한다 — 층별 날짜 수가 재표본에서도 유지된다.

    반환은 (n_boot, n_dates) 인덱스 행렬이다. 각 층의 열 위치에 그 층 날짜의 인덱스가 들어가므로
    `resample_counts`에 그대로 넣을 수 있다.
    """
    strata = np.asarray(strata)
    rng = np.random.default_rng(seed)
    out = np.empty((n_boot, strata.size), dtype=np.int64)
    for label in pd.unique(strata):
        pos = np.flatnonzero(strata == label)
        out[:, pos] = pos[rng.integers(0, pos.size, size=(n_boot, pos.size))]
    return out


def block_resample_dates(n_dates: int, n_boot: int, seed: int, block: int = 7) -> np.ndarray:
    """이동 블록 부트스트랩 — 길이 `block`의 연속 구간을 복원추출해 이어 붙이고 n_dates로 자른다.

    wrap-around는 허용하지 않는다(시작점은 `0 ~ n_dates − block`). 날짜 순서가 시간 순이어야
    한다. 요일 주기·자기상관을 블록 안에 보존하려는 변형이다.
    """
    block = max(1, min(block, n_dates))
    n_blocks = -(-n_dates // block)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n_dates - block + 1, size=(n_boot, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_boot, -1)
    return idx[:, :n_dates]


def bootstrap_improvement(
    losses_model: pd.DataFrame,
    losses_base: pd.DataFrame,
    n_boot: int = 1000,
    seed: int = 0,
    *,
    strata: np.ndarray | pd.Series | None = None,
    block: int | None = None,
    metric: str = "rmse",
) -> dict:
    """기준선 대비 개선율(%)의 점추정과 95% 백분위 CI.

    두 손실 표(`daily_losses` 결과)를 `date`로 inner 정렬해 같은 재표본 위에서 쉬움을 상쇄한다.
    `strata`(날짜별 층 라벨, 정렬된 날짜와 같은 길이이거나 날짜를 인덱스로 가진 Series)가 있으면
    층화 재표본, `block`이 있으면 이동 블록 재표본, 둘 다 없으면 `bootstrap.py`와 같은 단순
    날짜 재표본이다. 날짜가 0개면 NaN을 돌려준다.
    """
    if metric not in ("rmse", "mae"):
        raise ValueError(f"metric은 rmse 또는 mae: {metric}")
    merged = losses_model.merge(losses_base, on="date", suffixes=("_m", "_b")).sort_values("date")
    n_dates = len(merged)
    nan = float("nan")
    if n_dates == 0:
        return {"point": nan, "ci_low": nan, "ci_high": nan, "n_dates": 0, "n_rows": 0}

    if strata is not None:
        if isinstance(strata, pd.Series):
            labels = strata.reindex(merged["date"]).to_numpy()
        else:
            labels = np.asarray(strata)
        index_matrix = stratified_resample_dates(labels, n_boot, seed)
    elif block is not None:
        index_matrix = block_resample_dates(n_dates, n_boot, seed, block)
    else:
        index_matrix = resample_dates(n_dates, n_boot, seed)
    counts = resample_counts(index_matrix, n_dates)
    full = np.ones((1, n_dates))

    n_m = merged["n_m"].to_numpy(dtype="float64")
    n_b = merged["n_b"].to_numpy(dtype="float64")
    if metric == "rmse":
        m_vec, b_vec = merged["sse_m"].to_numpy(), merged["sse_b"].to_numpy()
        stat = weighted_rmse
    else:
        m_vec, b_vec = merged["sae_m"].to_numpy(), merged["sae_b"].to_numpy()
        stat = weighted_mae
    boot = improvement_pct(stat(counts, b_vec, n_b), stat(counts, m_vec, n_m))
    point = float(improvement_pct(stat(full, b_vec, n_b), stat(full, m_vec, n_m))[0])
    low, high = percentile_ci(boot)
    return {
        "point": point,
        "ci_low": low,
        "ci_high": high,
        "n_dates": int(n_dates),
        "n_rows": int(n_m.sum()),
    }


def bootstrap_relative_rmse(
    losses_cand: pd.DataFrame,
    losses_champ: pd.DataFrame,
    n_boot: int = 1000,
    seed: int = 0,
    *,
    strata: np.ndarray | pd.Series | None = None,
    block: int | None = None,
    metric: str = "rmse",
) -> dict:
    """챔피언 대비 후보의 상대 RMSE 개선 `(1 − RMSE_cand / RMSE_champ) × 100`과 CI(재학습 게이트용).

    수식은 `bootstrap_improvement`에서 기준선을 챔피언으로 둔 것과 같다.
    """
    return bootstrap_improvement(
        losses_cand,
        losses_champ,
        n_boot,
        seed,
        strata=strata,
        block=block,
        metric=metric,
    )
