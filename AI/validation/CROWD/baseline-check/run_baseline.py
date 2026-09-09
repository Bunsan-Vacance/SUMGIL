"""베이스라인을 학습·평가하고, 기상·이벤트가 설명할 수 있는 여지를 측정한다.

세 가지를 출력한다.

1. **베이스라인 성능** — 요일유형 × 역 × 시간대 평균 조회의 RMSE/MAE/MAPE
2. **잔차 구조** — 실측 − 베이스라인. 이 분산이 기상·이벤트가 설명할 수 있는 최대치다.
   여기가 작으면 무엇을 넣어도 베이스라인을 크게 못 이긴다는 뜻이라, 87번의 방향 자체를
   다시 봐야 한다.
3. **잔차와 외부 변수의 상관** — 강수·기온·경기·축제가 실제로 잔차를 설명하는지.
   raw 승하차끼리 상관을 보면 공통 주기 때문에 뭐든 높게 나오므로 반드시 잔차로 본다.

실행:
    cd AI
    python -m validation.CROWD.baseline-check.run_baseline
    (디렉터리명에 하이픈이 있어 -m 이 안 되면: python validation/CROWD/baseline-check/run_baseline.py)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from baseline import DayTypeLookupBaseline, evaluate, residuals
from dataset import load_panel, time_split

WEATHER_COLS = ["temp_c", "precip_mm", "wind_ms", "humidity_pct", "snow_cm"]
EVENT_COLS = ["game_count", "festival_count"]


def residual_variance_share(
    test: pd.DataFrame, resid: pd.DataFrame, target: str
) -> dict[str, float]:
    """전체 분산 대비 잔차 분산의 비중.

    베이스라인이 이미 설명한 몫(1 − 비중)과 남은 몫(비중)을 나눠 본다. 남은 몫이 곧
    기상·이벤트·모델링으로 줄일 수 있는 상한이다.
    """
    total_var = float(test[target].var())
    resid_var = float(resid[f"{target}_resid"].var())
    return {
        "target": target,
        "전체_분산": total_var,
        "잔차_분산": resid_var,
        "베이스라인_설명력_R2": 1 - resid_var / total_var if total_var else float("nan"),
        "남은_여지_%": resid_var / total_var * 100 if total_var else float("nan"),
    }


def residual_correlations(test: pd.DataFrame, resid: pd.DataFrame, target: str) -> pd.DataFrame:
    """잔차와 외부 변수의 상관 — 선형(pearson)과 단조(spearman)를 같이 본다.

    기온-이용량은 U자형이라 피어슨만 보면 0에 가깝게 나올 수 있어 스피어만을 함께 낸다.
    """
    frame = test.copy()
    frame["resid"] = resid[f"{target}_resid"].to_numpy()
    rows = []
    for col in WEATHER_COLS + EVENT_COLS:
        if col not in frame.columns:
            continue
        sub = frame[[col, "resid"]].dropna()
        if len(sub) < 100 or sub[col].nunique() < 2:
            continue
        rows.append(
            {
                "변수": col,
                "n": len(sub),
                "pearson": round(sub[col].corr(sub["resid"]), 4),
                "spearman": round(sub[col].corr(sub["resid"], method="spearman"), 4),
            }
        )
    return pd.DataFrame(rows)


def event_day_effect(test: pd.DataFrame, resid: pd.DataFrame, target: str) -> pd.DataFrame:
    """경기·축제가 있는 날의 잔차가 없는 날과 얼마나 다른가.

    상관계수는 이벤트처럼 대부분 0인 희소 변수에서 작게 나오므로, 있음/없음으로 나눠
    평균 잔차를 직접 비교한다.
    """
    frame = test.copy()
    frame["resid"] = resid[f"{target}_resid"].to_numpy()
    rows = []
    for col in EVENT_COLS:
        if col not in frame.columns:
            continue
        has = frame[frame[col] > 0]["resid"]
        without = frame[frame[col] == 0]["resid"]
        if len(has) < 30:
            continue
        rows.append(
            {
                "이벤트": col,
                "있는날_n": len(has),
                "있는날_평균잔차": round(float(has.mean()), 1),
                "없는날_평균잔차": round(float(without.mean()), 1),
                "차이": round(float(has.mean() - without.mean()), 1),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    panel = load_panel(with_events=True)
    train, test = time_split(panel)
    print(
        f"[분할] 학습 {len(train):,}행 ({train['date'].min():%Y-%m-%d}~{train['date'].max():%Y-%m-%d}) / "
        f"평가 {len(test):,}행 ({test['date'].min():%Y-%m-%d}~{test['date'].max():%Y-%m-%d})"
    )

    model = DayTypeLookupBaseline().fit(train)
    metrics, missing = evaluate(model, test)
    print("\n[베이스라인] 요일유형 × 역 × 시간대 평균 조회")
    print(metrics.round(2).to_string(index=False))
    if missing:
        print(
            f"[경고] 학습 구간에 없는 조합이라 조회 실패한 행 {missing:,}건 — "
            "전체 평균으로 채우지 않고 결측으로 뒀다(지표 계산에서 제외됨)."
        )

    resid = residuals(model, test)
    print("\n[잔차 구조] 남은 여지 = 기상·이벤트가 설명할 수 있는 최대치")
    shares = pd.DataFrame([residual_variance_share(test, resid, t) for t in model.targets])
    print(shares.round(3).to_string(index=False))

    for target in model.targets:
        print(f"\n[잔차 상관] {target}")
        print(residual_correlations(test, resid, target).to_string(index=False))
        effect = event_day_effect(test, resid, target)
        if len(effect):
            print(f"[이벤트 효과] {target}")
            print(effect.to_string(index=False))


if __name__ == "__main__":
    main()
