"""2단계 — 라벨 정식화.

지금까지(A1, effect_recheck_full 등) `stock_anchor_hour + target_net_flow`로 미래 재고를
매번 즉석 계산했다. 앞으로 3~5단계(피처 조인·모델 학습·평가)에서 반복 재사용할 거라
공식을 여기 한 곳에 고정한다 — 계산이 여러 스크립트에 흩어져 서로 미묘하게 달라지는
사고를 막기 위해서다(`AI/CLAUDE.md` "같은 계산을 두 번 하지 않는다").

    target_stock       = stock_anchor_hour + target_net_flow
    target_stock_ratio = target_stock / rack_count
    is_empty_future    = target_stock <= 0
    is_full_future     = target_stock >= rack_count

검증(B2/effect_recheck_full)에서 이미 이 공식으로 실측 empty/full 발생률을 확인했으므로
새로 검증할 것은 없다 — 여기서는 그 공식을 재사용 가능한 함수로만 옮긴다.

이번 라운드가 끝나고 승격할 때는 `app/BIKE/pipeline/features.py`에 옮긴다(아직 검증 중이라
`validation/`에 둠 — `app/`은 `validation/`을 import하지 않는다는 디렉터리 규약 유지).
"""

from __future__ import annotations

import pandas as pd

REQUIRED_COLS = ["stock_anchor_hour", "target_net_flow", "rack_count"]
LABEL_COLS = ["target_stock", "target_stock_ratio", "is_empty_future", "is_full_future"]


def add_future_stock_labels(df: pd.DataFrame) -> pd.DataFrame:
    """`REQUIRED_COLS`가 있는 프레임에 `LABEL_COLS`를 추가해서 돌려준다(원본 비변경, copy)."""
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise KeyError(f"라벨 계산에 필요한 컬럼이 없음: {missing}")

    df = df.copy()
    df["target_stock"] = df["stock_anchor_hour"] + df["target_net_flow"]
    df["target_stock_ratio"] = df["target_stock"] / df["rack_count"].replace(0, pd.NA)
    df["is_empty_future"] = df["target_stock"] <= 0
    df["is_full_future"] = df["target_stock"] >= df["rack_count"]
    return df


def _smoke_test() -> None:
    """1개월 소규모로 기존 effect_recheck_full.py의 empty/full 발생률과 같은 숫자가
    나오는지 재확인(회귀 방지)."""
    from app.BIKE.pipeline.dataset import monthly_paths

    p = monthly_paths("train", ["202401"])[0]
    df = pd.read_parquet(
        p, columns=["horizon_min", "stock_anchor_hour", "target_net_flow", "rack_count"]
    )
    df = df[df["horizon_min"] == 5].dropna(subset=["stock_anchor_hour", "target_net_flow"])
    labeled = add_future_stock_labels(df)
    print(f"[labels] {len(labeled):,}행 — empty_rate={labeled['is_empty_future'].mean():.4f}, "
          f"full_rate={labeled['is_full_future'].mean():.4f}")


if __name__ == "__main__":
    _smoke_test()
