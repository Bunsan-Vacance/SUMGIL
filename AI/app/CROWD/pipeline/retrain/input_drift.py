"""학습 데이터 분포 모니터 — 학습 패널 대 최근 창의 피처 분포 비교(S15P21A104-341 TD1~TD5).

배포 피처 세트(`features.FEATURE_SETS`)의 수치형 컬럼마다 PSI·KS를 재고, 타깃 분위수 이동과
lag 가용성(full/d1_only/d7_only/no_lag) 비율을 함께 기록한다. 결과는 사이드카 json
(`<out-root>/dt=<date>/part.json`)이고 ops API·Grafana가 읽는다. pandas·numpy만 쓴다(scipy 금지).

표본이 모자라는 컬럼(비결측 < `MIN_SAMPLES`)은 값을 채우지 않고 `level="na"`로 둔다(원칙 8).
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from app.CROWD.pipeline.retrain.common import MONITORING_DIR, now_kst, write_json

PSI_WARN = 0.1
PSI_CRIT = 0.25
TARGET_SHIFT = 0.2  # TD3: 기준 분위수 대비 ±20%
NO_LAG_RISE = 0.2  # TD5: no_lag 비율이 기준보다 0.2 넘게 오르면 경보
MIN_SAMPLES = 30
QUANTILES = (5, 25, 50, 75, 95)
TARGET_COLS = ("boarding", "alighting")
AVAILABILITY_NAMES = ("full", "d1_only", "d7_only", "no_lag")
DEFAULT_OUT_ROOT = MONITORING_DIR / "data_quality" / "features"


# ── 순수 함수 ──
def _clean(x) -> np.ndarray:
    arr = np.asarray(x, dtype="float64").ravel()
    return arr[np.isfinite(arr)]


def psi(expected, actual, bins: int = 10, eps: float = 1e-6) -> float:
    """Population Stability Index. 분위수 경계는 expected 기준이고 NaN은 뺀다.

    경계가 중복되면(이산 피처) 합쳐서 구간 수가 줄어든다. 구간이 하나뿐이면 0.
    """
    e, a = _clean(expected), _clean(actual)
    if e.size == 0 or a.size == 0:
        return float("nan")
    edges = np.unique(np.quantile(e, np.linspace(0, 1, bins + 1)[1:-1]))
    if edges.size == 0:
        return 0.0
    e_cnt = np.bincount(np.searchsorted(edges, e, side="right"), minlength=edges.size + 1)
    a_cnt = np.bincount(np.searchsorted(edges, a, side="right"), minlength=edges.size + 1)
    e_pct = np.maximum(e_cnt / e.size, eps)
    a_pct = np.maximum(a_cnt / a.size, eps)
    return float(np.sum((a_pct - e_pct) * np.log(a_pct / e_pct)))


def ks_statistic(a, b) -> tuple[float, float]:
    """2표본 KS 통계량 D와 점근 p값(Kolmogorov 급수, 소표본 보정 포함)."""
    x, y = np.sort(_clean(a)), np.sort(_clean(b))
    n, m = x.size, y.size
    if n == 0 or m == 0:
        return float("nan"), float("nan")
    grid = np.concatenate([x, y])
    cdf_x = np.searchsorted(x, grid, side="right") / n
    cdf_y = np.searchsorted(y, grid, side="right") / m
    d = float(np.max(np.abs(cdf_x - cdf_y)))
    en = math.sqrt(n * m / (n + m))
    lam = (en + 0.12 + 0.11 / en) * d
    if lam < 1e-9:
        return d, 1.0
    total = 0.0
    for k in range(1, 101):
        term = 2.0 * (-1) ** (k - 1) * math.exp(-2.0 * k * k * lam * lam)
        total += term
        if abs(term) < 1e-12:
            break
    return d, float(min(max(total, 0.0), 1.0))


def quantiles(x, qs=QUANTILES) -> dict[str, float | None]:
    """`{"5": v, ...}` 형태 분위수. 표본이 없으면 값은 None."""
    arr = _clean(x)
    if arr.size == 0:
        return {str(q): None for q in qs}
    vals = np.percentile(arr, list(qs))
    return {str(q): float(v) for q, v in zip(qs, vals, strict=True)}


def js_distance(p, q) -> float:
    """Jensen-Shannon 거리(밑 2, 0~1). 입력은 합이 1이 아니어도 정규화한다."""
    p = np.asarray(p, dtype="float64")
    q = np.asarray(q, dtype="float64")
    if p.sum() <= 0 or q.sum() <= 0:
        return float("nan")
    p, q = p / p.sum(), q / q.sum()
    mid = 0.5 * (p + q)

    def _kl(u: np.ndarray, v: np.ndarray) -> float:
        mask = u > 0
        return float(np.sum(u[mask] * np.log2(u[mask] / v[mask])))

    return float(math.sqrt(max(0.5 * _kl(p, mid) + 0.5 * _kl(q, mid), 0.0)))


def level_for_psi(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "na"
    if value >= PSI_CRIT:
        return "crit"
    if value >= PSI_WARN:
        return "warn"
    return "ok"


def availability_ratio(frame: pd.DataFrame) -> dict[str, float]:
    """lag 컬럼 결측 패턴으로 행별 가용성(`masking` 시나리오 이름)을 가르고 비율을 낸다.

    `lag1d_*`가 하나라도 있으면 d1, `lag7d_*`가 하나라도 있으면 d7. 둘 다 → full, 둘 다 없음 → no_lag.
    lag 컬럼이 아예 없으면 전 행 no_lag.
    """
    n = len(frame)
    if n == 0:
        return {k: 0.0 for k in AVAILABILITY_NAMES}
    d1_cols = [c for c in frame.columns if str(c).startswith("lag1d_")]
    d7_cols = [c for c in frame.columns if str(c).startswith("lag7d_")]
    d1 = frame[d1_cols].notna().any(axis=1).to_numpy() if d1_cols else np.zeros(n, bool)
    d7 = frame[d7_cols].notna().any(axis=1).to_numpy() if d7_cols else np.zeros(n, bool)
    return {
        "full": float(np.mean(d1 & d7)),
        "d1_only": float(np.mean(d1 & ~d7)),
        "d7_only": float(np.mean(~d1 & d7)),
        "no_lag": float(np.mean(~d1 & ~d7)),
    }


# ── 합성 ──
def _with_derived(train: pd.DataFrame, recent: pd.DataFrame, cols: list[str]):
    """파생 컬럼이 필요한데 없으면 학습 패널로 lookup을 맞춰 두 패널에 `add_derived_columns`를 적용한다."""
    from app.CROWD.pipeline.features import needs_derived_columns

    missing = [c for c in cols if c not in train.columns or c not in recent.columns]
    if not (missing and needs_derived_columns(missing)):
        return train, recent
    # 무거운 의존성(topology yaml 등)은 필요할 때만 올린다.
    from app.CROWD.pipeline.dataset import resolved_segments
    from app.CROWD.pipeline.features import add_derived_columns
    from app.CROWD.pipeline.lookup import DayTypeLookupBaseline

    lookup = DayTypeLookupBaseline().fit(train)
    out = []
    for panel in (train, recent):
        segments, _ = resolved_segments(panel)
        out.append(add_derived_columns(panel, lookup, segments))
    return out[0], out[1]


def _numeric_features(feature_set: str) -> list[str]:
    from app.CROWD.pipeline.features import CATEGORICAL_COLS, FEATURE_SETS

    if feature_set not in FEATURE_SETS:
        raise KeyError(f"모르는 피처 세트 {feature_set!r} — {list(FEATURE_SETS)} 중 하나")
    return [c for c in FEATURE_SETS[feature_set] if c not in CATEGORICAL_COLS]


def _target_report(train: pd.DataFrame, recent: pd.DataFrame) -> tuple[dict, list[str]]:
    targets: dict[str, dict] = {}
    shifted_any = False
    for t in TARGET_COLS:
        base = quantiles(train[t]) if t in train.columns else quantiles([])
        cur = quantiles(recent[t]) if t in recent.columns else quantiles([])
        shifted = False
        for q, b in base.items():
            r = cur[q]
            if b is None or r is None or abs(b) < 1e-9:
                continue
            if abs(r - b) / abs(b) > TARGET_SHIFT:
                shifted = True
        targets[t] = {"baseline": base, "recent": cur, "shifted": shifted}
        shifted_any = shifted_any or shifted
    return targets, (["TD3"] if shifted_any else [])


def compute_input_drift(
    train_panel: pd.DataFrame,
    recent_panel: pd.DataFrame,
    feature_set: str,
    *,
    date,
    window: int,
    synthetic: bool = False,
) -> dict:
    """학습 패널 대 최근 `window`일 창의 분포 비교 결과(설계 3절 `features/dt=D/part.json`)."""
    end = pd.Timestamp(date).normalize()
    start = end - pd.Timedelta(days=int(window) - 1)
    cols = _numeric_features(feature_set)
    train, recent = _with_derived(train_panel, recent_panel, cols)
    if "date" in recent.columns:
        days = pd.to_datetime(recent["date"]).dt.normalize()
        recent = recent[(days >= start) & (days <= end)]

    alerts: list[str] = []
    features = []
    for name in cols:
        e_arr = (
            _clean(pd.to_numeric(train[name], errors="coerce")) if name in train else np.array([])
        )
        a_arr = (
            _clean(pd.to_numeric(recent[name], errors="coerce")) if name in recent else np.array([])
        )
        entry = {
            "name": name,
            "psi": None,
            "ks": None,
            "ks_p": None,
            "level": "na",
            "n_train": int(e_arr.size),
            "n_recent": int(a_arr.size),
        }
        if e_arr.size >= MIN_SAMPLES and a_arr.size >= MIN_SAMPLES:
            entry["psi"] = psi(e_arr, a_arr)
            entry["ks"], entry["ks_p"] = ks_statistic(e_arr, a_arr)
            entry["level"] = level_for_psi(entry["psi"])
            if entry["level"] == "crit":
                alerts.append(f"TD1:{name}")
        features.append(entry)

    targets, target_alerts = _target_report(train, recent)
    alerts.extend(target_alerts)

    avail = {"baseline": availability_ratio(train), "recent": availability_ratio(recent)}
    if len(recent) and avail["recent"]["no_lag"] > avail["baseline"]["no_lag"] + NO_LAG_RISE:
        alerts.append("TD5")

    return {
        "date": f"{end:%Y-%m-%d}",
        "window": [f"{start:%Y-%m-%d}", f"{end:%Y-%m-%d}"],
        "window_days": int(window),
        "feature_set": feature_set,
        "features": features,
        "targets": targets,
        "availability_ratio": avail,
        "alerts": alerts,
        "generated_at": now_kst().isoformat(),
        "synthetic": bool(synthetic),
    }


# ── CLI ──
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="학습 데이터 분포 모니터(TD1~TD5)")
    ap.add_argument("--train-panel", required=True, help="학습 와이드 패널 parquet")
    ap.add_argument("--recent-panel", required=True, help="최근 창 와이드 패널 parquet")
    ap.add_argument("--feature-set", required=True)
    ap.add_argument("--date", required=True, help="창 끝 날짜 YYYY-MM-DD")
    ap.add_argument("--window", type=int, required=True, help="창 길이(일)")
    ap.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT))
    ap.add_argument("--mark-synthetic", action="store_true", help="합성 입력이면 표시")
    args = ap.parse_args(argv)

    train_path, recent_path = Path(args.train_panel), Path(args.recent_panel)
    for path in (train_path, recent_path):
        if not path.exists():
            print(f"[입력 분포] 패널이 없다: {path}", file=sys.stderr, flush=True)
            return 2

    result = compute_input_drift(
        pd.read_parquet(train_path),
        pd.read_parquet(recent_path),
        args.feature_set,
        date=args.date,
        window=args.window,
        synthetic=args.mark_synthetic,
    )
    out = Path(args.out_root) / f"dt={result['date']}" / "part.json"
    write_json(out, result)
    crit = [f["name"] for f in result["features"] if f["level"] == "crit"]
    print(
        f"[입력 분포] {result['date']} 피처 {len(result['features'])}개 · crit {len(crit)}개 · "
        f"경보 {result['alerts']} → {out}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
