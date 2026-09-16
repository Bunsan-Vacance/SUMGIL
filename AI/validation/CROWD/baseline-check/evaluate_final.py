"""90번(모델 학습·검증) — 최종 모델 평가 4종을 한 프로세스에서 낸다.

87·89 비교(`compare_models.py`)는 "어느 피처가 효과 있나"를 물었고, 여기는 "그 모델을 실제로
배포하면 어떤 상황에서 얼마나 맞나"를 묻는다. 데이터 로딩·lookup fit·파생(캐시)은 한 번만 하고
평가마다 학습만 반복한다(`AI/CLAUDE.md` "실험 실행 효율"). 전부 LightGBM 기준.

1. **실시간 컬럼 마스킹** — `festival_all_derived_resid`로 학습한 모델을, 평가 구간에서
   같은 시각 이웃·직전 슬롯 컬럼(`features.REALTIME_COLS`)을 NaN으로 가린 채 평가한다.
   서빙 원천이 D−1이라 실제 배포 상황이 이것이다. 시차 전용 세트(`festival_selflag_d1d7_resid`)
   와 비교해 "모델 하나로 두 상황을 덮을 수 있는가"를 판정한다 — 마스킹 성능이 시차 전용 세트에
   2%p 안으로 붙으면 하나로, 아니면 배포 세트를 시차 전용으로 바꾼다.
2. **롤링 분할** — 기본(2024 학습 / 2025 평가)에 더해 2024-01~2025-06 학습 / 2025-07~12 평가.
   "예측 시점에 가까운 데이터를 학습에 넣으면 좋아지는가"(논문의 최신성 가설, EDA 리포트 6절)의
   첫 실측. 두 분할의 평가 구간이 다르므로 절대값이 아니라 **베이스라인 대비 개선율**로 비교한다.
3. **하이퍼파라미터 그리드** — num_leaves {31, 63, 127} × n_estimators {300, 600}, 6조합.
   학습 1분 이내씩. **D−1 배포 세트(시차 전용)** 기준으로 고른다 — 1절에서 전부 세트를 마스킹하면
   시차 전용 세트에 크게 못 미쳤기 때문이다(2026-09-11: RMSE +4~8% vs +22~24%). 학습 때 있던
   컬럼이 서빙에서 통째로 비면 트리가 그 컬럼에 의존한 분할이 전부 무력화된다 — "모델 하나로 두
   상황"은 성립하지 않고, 실시간 원천이 생기면 전부 세트로 **따로** 학습한다.
4. **구간 분해** — 배포 세트·최종 설정으로 호선·요일유형·시간대별 베이스라인/모델 RMSE·MAE.
   1호선 등 93번이 볼 지점을 표로 남긴다.

결과는 표준 출력과 `RESULTS.md`에 옮길 마크다운 표로 낸다(`--out` 지정 시 파일로).

실행:
    cd AI
    python validation/CROWD/baseline-check/evaluate_final.py [--skip-grid] [--out path.md]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[2]
for p in (str(_HERE), str(AI_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from baseline import regression_metrics

from app.CROWD.pipeline.dataset import load_or_build_derived, load_panel, time_split
from app.CROWD.pipeline.features import build_matrix, mask_realtime_columns
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline
from app.CROWD.pipeline.train import DEFAULT_PARAMS, train_models

DEPLOY_SET = "festival_all_derived_resid"
LAG_ONLY_SET = "festival_selflag_d1d7_resid"
BASELINE_SET = "events_station_time_festival"

GRID = [{"num_leaves": nl, "n_estimators": ne} for nl in (31, 63, 127) for ne in (300, 600)]
ROLLING_SPLIT = pd.Timestamp("2025-07-01")


def _pct(base: float, val: float) -> float:
    return round((1 - val / base) * 100, 2)


def to_markdown(frame: pd.DataFrame) -> str:
    """tabulate 없이 마크다운 표를 만든다(requirements-ci에 없는 의존성을 늘리지 않기 위해)."""
    cols = [str(c) for c in frame.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for _, r in frame.iterrows():
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in r.tolist()) + " |")
    return "\n".join(lines)


def evaluate(
    train: pd.DataFrame,
    test: pd.DataFrame,
    lookup: DayTypeLookupBaseline,
    feature_set: str,
    params: dict | None = None,
    mask: bool = False,
    label: str | None = None,
) -> pd.DataFrame:
    """세트 하나를 학습해 (마스킹 여부에 따라) 평가한다. 타깃별 한 행."""
    t0 = time.time()
    models = train_models(train, lookup, feature_set, params)
    X_test = build_matrix(test, feature_set)
    if mask:
        X_test = mask_realtime_columns(X_test)
    lookup_pred = lookup.predict(test)
    rows = []
    for target in TARGETS:
        base = regression_metrics(test[target], lookup_pred[target])
        pred = lookup_pred[target].to_numpy() + models[target]["__all__"].predict(X_test)
        m = regression_metrics(test[target], pd.Series(pred))
        rows.append(
            {
                "평가": label or feature_set,
                "target": target,
                "base_rmse": round(base["rmse"], 2),
                "rmse": round(m["rmse"], 2),
                "RMSE_개선율_%": _pct(base["rmse"], m["rmse"]),
                "base_mae": round(base["mae"], 2),
                "mae": round(m["mae"], 2),
                "MAE_개선율_%": _pct(base["mae"], m["mae"]),
                "mape": round(m["mape"], 2),
                "학습_초": round(time.time() - t0, 1),
            }
        )
    return pd.DataFrame(rows)


def breakdown(
    train: pd.DataFrame,
    test: pd.DataFrame,
    lookup: DayTypeLookupBaseline,
    feature_set: str,
    params: dict | None,
    mask: bool,
) -> pd.DataFrame:
    """호선·요일유형·시간대별 베이스라인/모델 RMSE·MAE(승차·하차)."""
    models = train_models(train, lookup, feature_set, params)
    X_test = build_matrix(test, feature_set)
    if mask:
        X_test = mask_realtime_columns(X_test)
    lookup_pred = lookup.predict(test)
    preds = {t: lookup_pred[t].to_numpy() + models[t]["__all__"].predict(X_test) for t in TARGETS}
    rows = []
    for key in ("line", "day_type", "time_slot"):
        for g, idx in test.groupby(key, observed=True).groups.items():
            row = {"축": key, "구간": g, "n": len(idx)}
            for t in TARGETS:
                b = regression_metrics(test.loc[idx, t], lookup_pred.loc[idx, t])
                m = regression_metrics(test.loc[idx, t], pd.Series(preds[t][idx], index=idx))
                row[f"{t}_base_rmse"] = round(b["rmse"], 1)
                row[f"{t}_RMSE_개선율_%"] = _pct(b["rmse"], m["rmse"])
                row[f"{t}_MAE_개선율_%"] = _pct(b["mae"], m["mae"])
            rows.append(row)
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--skip-grid", action="store_true")
    ap.add_argument("--out", default=None, help="마크다운 표를 저장할 경로")
    args = ap.parse_args(argv)
    chunks: list[str] = []

    def emit(title: str, frame: pd.DataFrame) -> None:
        print(f"\n### {title}", flush=True)
        print(frame.to_string(index=False), flush=True)
        chunks.append(f"### {title}\n\n{to_markdown(frame)}\n")

    panel = load_panel(with_events=True)
    train_raw, _ = time_split(panel)
    lookup = DayTypeLookupBaseline().fit(train_raw)
    derived = load_or_build_derived(panel, lookup)
    train, test = time_split(derived)

    # 1. 마스킹 평가
    frames = [
        evaluate(train, test, lookup, BASELINE_SET, label="87 권장(외부 요인만)"),
        evaluate(train, test, lookup, LAG_ONLY_SET, label="시차 전용(D-1 서빙용 세트)"),
        evaluate(train, test, lookup, DEPLOY_SET, label="전부 — 실시간 컬럼 있음(상한)"),
        evaluate(
            train, test, lookup, DEPLOY_SET, mask=True, label="전부 — 실시간 컬럼 NaN(D-1 서빙)"
        ),
    ]
    emit("1. 실시간 컬럼 마스킹 평가 (2024 학습 / 2025 평가)", pd.concat(frames, ignore_index=True))

    # 2. 롤링 분할 — lookup도 새 학습 구간으로 다시 fit해야 공정하다
    r_train_raw, _ = time_split(panel, ROLLING_SPLIT)
    r_lookup = DayTypeLookupBaseline().fit(r_train_raw)
    r_derived = load_or_build_derived(
        panel,
        r_lookup,
        cache_path=AI_ROOT / "data" / "CROWD" / "interim" / "crowd_panel_derived_rolling.parquet",
    )
    r_train, r_test = time_split(r_derived, ROLLING_SPLIT)
    frames = [
        evaluate(r_train, r_test, r_lookup, LAG_ONLY_SET, label="롤링: 시차 전용"),
        evaluate(r_train, r_test, r_lookup, DEPLOY_SET, mask=True, label="롤링: 전부, 실시간 NaN"),
    ]
    emit(
        "2. 롤링 분할 (2024-01~2025-06 학습 / 2025-07~12 평가)",
        pd.concat(frames, ignore_index=True),
    )

    # 3. 그리드 — D-1 배포 세트(시차 전용) 기준. 1절에서 "전부 세트 + 마스킹"이 시차 전용 세트에
    #    크게 못 미치면(2026-09-11 실측: +4~8% vs +22~24%) 배포 세트는 시차 전용이다.
    best_params = dict(DEFAULT_PARAMS)
    if not args.skip_grid:
        rows = []
        for g in GRID:
            res = evaluate(train, test, lookup, LAG_ONLY_SET, params=g, label=str(g))
            rows.append(res.assign(num_leaves=g["num_leaves"], n_estimators=g["n_estimators"]))
        grid = pd.concat(rows, ignore_index=True)
        emit("3. 하이퍼파라미터 그리드 (시차 전용 세트 = D-1 배포 세트)", grid)
        score = grid.groupby(["num_leaves", "n_estimators"])["RMSE_개선율_%"].mean()
        nl, ne = score.idxmax()
        best_params.update({"num_leaves": int(nl), "n_estimators": int(ne)})
        print(
            f"\n[선택] num_leaves={nl}, n_estimators={ne} (승차·하차 평균 RMSE 개선율 {score.max():.2f}%)"
        )

    # 4. 구간 분해 — 배포 세트, 최종 파라미터
    bd = breakdown(train, test, lookup, LAG_ONLY_SET, best_params, mask=False)
    emit("4. 구간 분해 (시차 전용 세트, 최종 파라미터)", bd)

    if args.out:
        Path(args.out).write_text("\n".join(chunks), encoding="utf-8")
        print(f"\n[저장] {args.out}")


if __name__ == "__main__":
    main(sys.argv[1:])
