"""A1 — anchor 롤포워드 하이브리드 프로토타입.

서빙 표(`bike_stock_pred`)엔 "현재 재고(anchor)"가 없다 — 정적으로 하루 48슬롯(30분 단위)을
전부 채워야 한다. 채택한 하이브리드 전략(2026-09-14 결정):

    각 30분 슬롯(t)의 exp_bikes를 예측할 때, anchor로 **직전 슬롯(t-1)의 avg baseline 값**을
    쓴다(모델 자신의 출력을 48번 이어붙이지 않음 — 오차가 하루 종일 누적되는 것을 막기 위해
    매 슬롯 anchor를 실측 평균으로 "리셋"한다). horizon_min=30으로 LightGBM(v3)에 넣어
    net_flow를 예측하고, exp_bikes_lightgbm(t) = anchor(t-1) + 예측된 net_flow.

**진짜 검증 포인트**: 이렇게 만든 값이 avg baseline 값(train 기간 평균)보다
**test 기간 실측 평균에 더 가까운가**? 안 그러면 LightGBM을 얹는 의미가 없다(그냥 avg 유지).

    ground truth = test(2025-07) 기간 실측 평균 (StockProfileBaseline.fit_streaming, 같은 계산)
    비교 A: train avg baseline 값 자체 vs ground truth       (지금 서빙 중인 것)
    비교 B: LightGBM 롤포워드로 보정한 값 vs ground truth     (이번에 검증하는 것)

소규모(station 5개, dow_type=0/평일만)로 먼저 확인한다.

실행:
    cd AI
    PYTHONPATH=. PYTHONIOENCODING=utf-8 python validation/BYC/lightgbm-stock-conversion-check/src/anchor_rollforward_prototype.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.BIKE.pipeline.calendar import load_holidays
from app.BIKE.pipeline.dataset import monthly_paths, scan_station_ids
from app.BIKE.pipeline.features import (
    MODEL_FEATURE_COLS,
    HistoricalProfileBuilder,
    build_station_dtype,
)
from app.BIKE.pipeline.lookup import StockProfileBaseline

ARTIFACT = "models/BIKE/v3-holiday-tuned_20260913-1558"
N_SLOTS_PER_DAY = 288  # 5분 슬롯 기준(원본 sin_slot/cos_slot과 동일 정의)
DOW_TYPE = 0  # 평일만 우선
SAMPLE_N_STATIONS = 5
# 대표값(합성 anchor라 "직전 실측 읽은 지 몇 분 됐나" 개념이 없음 — 학습 데이터 중앙값으로 근사)
MINUTES_SINCE_ANCHOR_DEFAULT = 30.0
REPRESENTATIVE_DAY_OF_WEEK = 2  # 수요일(dow_type=0/평일 대표), month=7(test 기간과 맞춤)
REPRESENTATIVE_MONTH = 7


def load_profile(artifact: str) -> HistoricalProfileBuilder:
    p = HistoricalProfileBuilder()
    p.full = pd.read_parquet(f"{artifact}/profile_full.parquet")
    p.station_horizon = pd.read_parquet(f"{artifact}/profile_station_horizon.parquet")
    p.global_ = pd.read_parquet(f"{artifact}/profile_global.parquet")
    return p


def build_feature_row(
    station: str,
    time_slot: int,
    anchor: float,
    rack_count: float,
    is_holiday: int,
    profile: HistoricalProfileBuilder,
) -> dict:
    hour = (time_slot * 30) // 60
    minute = (time_slot * 30) % 60
    slot_5m = time_slot * 6  # 그 30분 슬롯의 시작 5분-슬롯
    row = {
        "od_station_id": station,
        "horizon_min": 30,
        "stock_anchor_hour": anchor,
        "stock_ratio_hour": anchor / rack_count if rack_count else np.nan,
        "minutes_since_stock_anchor": MINUTES_SINCE_ANCHOR_DEFAULT,
        "is_empty_anchor": int(anchor <= 0),
        "is_full_anchor": int(anchor >= rack_count),
        "hour": hour,
        "minute": minute,
        "day_of_week": REPRESENTATIVE_DAY_OF_WEEK,
        "is_weekend": 0,
        "month": REPRESENTATIVE_MONTH,
        "sin_hour": np.sin(2 * np.pi * hour / 24),
        "cos_hour": np.cos(2 * np.pi * hour / 24),
        "sin_slot": np.sin(2 * np.pi * slot_5m / N_SLOTS_PER_DAY),
        "cos_slot": np.cos(2 * np.pi * slot_5m / N_SLOTS_PER_DAY),
        "is_holiday": is_holiday,
    }
    frame = pd.DataFrame([row])
    frame = profile.transform(frame)
    return frame


def main() -> None:
    import lightgbm as lgb

    print("[A1] 아티팩트·avg baseline·historical profile 로딩...")
    model = lgb.Booster(model_file=f"{ARTIFACT}/model.txt")
    avg_train = pd.read_parquet(f"{ARTIFACT}/stock_profile_avg.parquet")
    profile = load_profile(ARTIFACT)
    holidays = load_holidays()

    # ── station_code dtype: 학습 시 카테고리와 동일해야 한다 ──
    import json

    with open(f"{ARTIFACT}/meta.json", encoding="utf-8") as f:
        meta = json.load(f)
    n_categories = meta["station_categories"]
    print(f"[A1] 학습 당시 station 카테고리 수(메타): {n_categories}")

    # station_code dtype 복원: train.py가 `sorted(train∪valid∪test station id)`로 만들었으므로
    # (features.py의 build_station_dtype), meta.json에 적힌 그 3개 집합의 월을 그대로 다시 스캔하면
    # 완전히 동일한 CategoricalDtype이 나온다.
    all_paths = (
        monthly_paths("train", meta["train_months"])
        + monthly_paths("valid", meta["valid_months"])
        + monthly_paths("test", meta["test_months"])
    )
    station_dtype = build_station_dtype(scan_station_ids(all_paths))
    assert len(station_dtype.categories) == n_categories, "station dtype 복원이 학습 당시와 다르다"
    print(f"[A1] station_code dtype 복원 완료 ({len(station_dtype.categories)}개, 메타와 일치)")

    # rack_count: raw netflow 파일에서 station별 1개 값만 가져온다(모든 슬롯에서 상수)
    raw = pd.read_parquet(
        monthly_paths("test", ["202507"])[0], columns=["od_station_id", "rack_count"]
    ).drop_duplicates("od_station_id")
    rack_map = dict(zip(raw["od_station_id"], raw["rack_count"], strict=False))

    # ── ground truth: test(2025-07) 실측 평균 ──
    print("[A1] test 기간 실측 평균(ground truth) 계산...")
    gt = StockProfileBaseline().fit_streaming(monthly_paths("test", ["202507"]), holidays).table_
    gt = gt[gt["dow_type"] == DOW_TYPE]

    # ── station 샘플: avg_train과 gt 양쪽에 다 있는 것 중 표본 수 많은 순 ──
    candidates = (
        avg_train[avg_train["dow_type"] == DOW_TYPE]
        .groupby("od_station_id")
        .size()
        .sort_values(ascending=False)
    )
    stations = [s for s in candidates.index if s in set(gt["od_station_id"]) and s in rack_map][
        :SAMPLE_N_STATIONS
    ]
    print(f"[A1] 표본 station: {stations}")

    is_hol_202507 = 0  # 2025-07엔 평일 기준 공휴일 없음(광복절은 8월) — 단순화

    rows = []
    for station in stations:
        avg_s = avg_train[
            (avg_train["od_station_id"] == station) & (avg_train["dow_type"] == DOW_TYPE)
        ]
        avg_by_slot = dict(zip(avg_s["time_slot"], avg_s["exp_bikes"], strict=False))
        gt_s = gt[gt["od_station_id"] == station]
        gt_by_slot = dict(zip(gt_s["time_slot"], gt_s["exp_bikes"], strict=False))
        rack_count = rack_map[station]

        for t in sorted(gt_by_slot):
            if t not in avg_by_slot or (t - 1) % 48 not in avg_by_slot:
                continue
            anchor = avg_by_slot[(t - 1) % 48]
            feat = build_feature_row(station, t, anchor, rack_count, is_hol_202507, profile)
            feat["station_code"] = feat["od_station_id"].astype(station_dtype).cat.codes
            x = feat.reindex(columns=MODEL_FEATURE_COLS)
            pred_net_flow = float(model.predict(x)[0])
            exp_bikes_lgbm = anchor + pred_net_flow

            rows.append(
                {
                    "station": station,
                    "time_slot": t,
                    "avg_train": avg_by_slot[t],
                    "lightgbm": exp_bikes_lgbm,
                    "ground_truth": gt_by_slot[t],
                }
            )

    result = pd.DataFrame(rows)
    result["err_avg"] = (result["avg_train"] - result["ground_truth"]).abs()
    result["err_lgbm"] = (result["lightgbm"] - result["ground_truth"]).abs()

    print(f"\n[A1] 비교 행수: {len(result)}")
    print(f"[A1] MAE(avg_train vs ground_truth)   = {result['err_avg'].mean():.3f}")
    print(f"[A1] MAE(lightgbm 보정 vs ground_truth) = {result['err_lgbm'].mean():.3f}")

    per_station = result.groupby("station")[["err_avg", "err_lgbm"]].mean()
    print("\n[A1] station별 MAE")
    print(per_station.to_string())


if __name__ == "__main__":
    main()
