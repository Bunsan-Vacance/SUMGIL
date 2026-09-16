"""날짜축 멀티소스 모델(B4-2)의 핵심 피처 — D-1/D-7 자기 역 실측 lag.

CROWD의 배포 모델(`app/CROWD/pipeline/MODEL_REGISTRY.md`)이 avg를 이긴 결정적 이유가
날씨·이벤트가 아니라 "자기 역 전날/1주 전 실측 잔차"였다는 걸 벤치마킹해서 BIKE에도
적용했다(`validation/BYC/lightgbm-stock-conversion-check/RESULTS.md`) — 날씨·공휴일·KBO만
넣었을 땐 avg를 못 이겼고, 이 lag를 추가해서야 이겼다(exp_bikes -11.6%, p_full -12.4%).

**실시간 anchor(5분 전 데이터)와 다르다.** "하루/일주일 전체 지난 날"은 배치를 도는
시점엔 항상 이미 확정된 데이터라, "anchor 없는 정적 배치" 설계와 충돌하지 않는다.

**분(minute) 단위가 아니라 time_slot(30분) 단위로 매칭한다.** 원본이 5분 고정 그리드가
아니라 실제 대여·반납이 일어난 시점만 기록된 이벤트성 데이터라(역당 하루 288슬롯 중
실제로는 50~60개뿐), 분까지 정확히 맞추면 매칭률이 30% 밑으로 떨어진다(실측 확인,
`RESULTS.md`) — 30분 단위로 묶어 그 구간 평균을 쓴다.
"""

from __future__ import annotations

import pandas as pd

from app.BIKE.pipeline.dataset import monthly_paths


def build_lag_lookup(months: list[str] | None = None) -> pd.DataFrame:
    """station × date × time_slot → 실측 재고 평균 lookup. D-1/D-7 조인의 재료.

    train/valid/test 경계를 넘어서 조회해야 한다(예: valid 12월 1일의 D-1은 train
    11월 30일에 있음) — 그래서 기본값은 세 split 전체를 다 스캔한다. `months`를 주면
    (YYYYMM 리스트) 그 달들로 좁혀서 소규모 검증에 쓸 수 있다.
    """
    all_paths = []
    for prefix in ("train", "valid", "test"):
        try:
            all_paths += monthly_paths(prefix, months)
        except FileNotFoundError:
            pass  # months가 이 prefix엔 해당 없음(예: valid는 202412 하나뿐)

    frames = []
    for p in all_paths:
        df = pd.read_parquet(
            p,
            columns=[
                "od_station_id",
                "base_time",
                "horizon_min",
                "stock_anchor_hour",
                "target_net_flow",
            ],
        )
        df = df[df["horizon_min"] == 30].dropna(subset=["stock_anchor_hour", "target_net_flow"])
        target_dt = pd.to_datetime(df["base_time"]) + pd.Timedelta(minutes=30)
        lag_time_slot = target_dt.dt.hour * 2 + (target_dt.dt.minute >= 30).astype(int)
        frames.append(
            pd.DataFrame(
                {
                    "od_station_id": df["od_station_id"].to_numpy(),
                    "lag_date": target_dt.dt.normalize(),
                    "lag_time_slot": lag_time_slot.to_numpy(),
                    "lag_stock": (df["stock_anchor_hour"] + df["target_net_flow"]).to_numpy(),
                }
            )
        )
    combined = pd.concat(frames, ignore_index=True)
    return (
        combined.groupby(["od_station_id", "lag_date", "lag_time_slot"])["lag_stock"]
        .mean()
        .reset_index()
    )


def attach_lag(
    df: pd.DataFrame,
    lookup: pd.DataFrame,
    days: int,
    out_col: str,
    date_col: str = "date",
    time_slot_col: str = "time_slot",
) -> pd.DataFrame:
    """`days`일 전 같은 역·같은 30분 슬롯의 실측 평균을 `out_col`(값)과
    `{out_col}_available`(있었는지 여부, 0/1)로 붙인다. 없으면 값은 NaN으로 남기고
    (원칙 8), 호출부가 historical profile 등으로 fallback한다(CROWD의 "이력 없으면
    lookup 대체"와 동일 관례)."""
    key = df[["od_station_id", time_slot_col]].rename(columns={time_slot_col: "lag_time_slot"})
    key["lag_date"] = df[date_col] - pd.Timedelta(days=days)
    merged = key.merge(lookup, on=["od_station_id", "lag_date", "lag_time_slot"], how="left")
    df[out_col] = merged["lag_stock"].to_numpy()
    df[f"{out_col}_available"] = df[out_col].notna().astype("int8")
    return df
